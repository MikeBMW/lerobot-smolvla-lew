#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""handeye_verify.py — 独立验证: 用 models/handeye_state.json 的 T_cam2tool 做**全链路重投影**

与解算时的"板在基座系一致性"不同, 这里走完整链路:
  板 → 基座 (Y, 由样本1 定) → 每帧的相机系 (经 工具位姿 G_i 与 X=T_cam2tool) → 投影成像素
与每帧真实检出的 20 个圆点比 → 中位/最大像素误差。这才是不循环论证的判据。
用法: gui-venv311/bin/python tools/handeye_verify.py --session <dir>
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from handeye_diag_solve import detect, load_calib, objp, quat_to_R  # noqa: E402

STATE = "/home/ubuntu/lerobot-smolvla-lew/models/handeye_state.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", required=True)
    a = ap.parse_args()
    Km, dist, _ = load_calib()
    X = np.array(json.load(open(STATE, encoding="utf-8"))["T_cam2tool"], float)
    print("X = T_cam2tool: t = %s m" % np.round(X[:3, 3], 4).tolist())

    views = []
    for line in open(os.path.join(a.session, "poses.jsonl"), encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        img = cv2.imread(r["img"])
        cs, grid = detect(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
        if cs is None:
            continue
        o = objp(grid)
        ok, rvec, tvec = cv2.solvePnP(o, cs, Km, dist, flags=cv2.SOLVEPNP_ITERATIVE)
        views.append({"idx": r["idx"], "cs": cs, "obj": o, "R_cb": cv2.Rodrigues(rvec)[0],
                      "t_cb": tvec.reshape(3), "R_tb": quat_to_R(r["quat"]),
                      "t_tb": np.array(r["tcp"], float)})

    # 板在基座系 (由全部视图最小二乘取平均, 用样本1 的旋转 + 各视图 t 的均值)
    Ys = []
    for v in views:
        G = np.eye(4); G[:3, :3] = v["R_tb"]; G[:3, 3] = v["t_tb"]
        C = np.eye(4); C[:3, :3] = v["R_cb"]; C[:3, 3] = v["t_cb"]
        Ys.append(G @ X @ C)
    Y = np.eye(4)
    Y[:3, :3] = Ys[0][:3, :3]
    Y[:3, 3] = np.mean([y[:3, 3] for y in Ys], axis=0)
    print("板在基座系: t = %s m" % np.round(Y[:3, 3], 4).tolist())

    errs = []
    for v in views:
        G = np.eye(4); G[:3, :3] = v["R_tb"]; G[:3, 3] = v["t_tb"]
        T_cam_base = G @ X
        T_board_cam = np.linalg.inv(T_cam_base) @ Y
        rv = cv2.Rodrigues(T_board_cam[:3, :3])[0]
        proj, _ = cv2.projectPoints(v["obj"], rv, T_board_cam[:3, 3].reshape(3, 1), Km, dist)
        e = np.linalg.norm(proj.reshape(-1, 2) - v["cs"], axis=1)
        errs.append((v["idx"], float(np.median(e)), float(e.max())))
        print("  样本%-3s 中位 %.3fpx · 最大 %.3fpx" % (v["idx"], np.median(e), e.max()))
    med = float(np.median([e[1] for e in errs]))
    mx = float(max(e[2] for e in errs))
    print("\n全链路重投影: 中位 %.3fpx · 最差 %.3fpx · 视图 %d 个" % (med, mx, len(errs)))
    print("结论: %s" % ("✅ 通过 (中位 ≤1.5px)" if med <= 1.5 else "❌ 不通过"))


if __name__ == "__main__":
    main()
