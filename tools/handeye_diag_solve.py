#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""handeye_diag_solve.py — 手眼数据诊断 + 解算 (自控口径, 不依赖 cv2.calibrateHandEye)

为什么自己写: tools/board_handeye_solve.py 用 cv2.calibrateHandEye 解出"相机到工具 267 米"(物理不可能),
而它的"留出复核 0.037px"是循环论证(用 PnP 自己的位姿投自己) → 判不了真假。
本脚本:
  ① 逐帧重检板 + solvePnP(带畸变) → 打印板在相机系的距离/姿态 + PnP 残差
  ② **纯平移视图的板姿态必须几乎相同**(机械臂只平移, 板相对相机只是平移) → 检查数据自洽性
  ③ 自解 X=T_cam2tool: 以"板在基座系的位姿 Y_i 应完全相同"为目标, scipy 最小二乘多起点求解
     → 残差(mm/°)就是真实质量指标; 残差大=数据不自洽(别落盘)
用法: gui-venv311/bin/python tools/handeye_diag_solve.py --session <dir>
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

import cv2
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation as Rot

PATTERN = (4, 5)
SPACING = 0.020        # ⚠️ 单位必须是**米**: TCP 位姿是米, 物点若用 20(mm) 解出的板距会 ×1000
                       #    (2026-09-21 实测: 用 20 → 板距相机 448m = 真实 0.448m 的 1000 倍; 09-19 那次 256m 同因)


def load_calib():
    p = "/home/ubuntu/lerobot-smolvla-lew/models/real_cam_calib.json"
    d = json.load(open(p, encoding="utf-8"))
    k = d["K"]
    Km = np.array([[k[0], 0, k[2]], [0, k[4], k[5]], [0, 0, 1]], float)
    dist = np.array(d.get("dist") or [0, 0, 0, 0, 0], float).reshape(-1)
    return Km, dist, p


def objp(grid, s=SPACING):
    cols, rows = grid
    o = np.zeros((rows * cols, 3), np.float32)
    k = 0
    for i in range(rows):
        for j in range(cols):
            o[k] = [(2 * j + (i % 2)) * s, i * s, 0]
            k += 1
    return o


def detect(gray):
    src = 255 - gray
    for grid in (PATTERN, (PATTERN[1], PATTERN[0])):
        ok, cs = cv2.findCirclesGrid(src, grid, flags=cv2.CALIB_CB_ASYMMETRIC_GRID)
        if ok:
            return cs.reshape(-1, 2), grid
    return None, None


def quat_to_R(q):
    return Rot.from_quat([q[0], q[1], q[2], q[3]]).as_matrix()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", required=True)
    a = ap.parse_args()
    Km, dist, ksrc = load_calib()
    print("内参: %s fx=%.2f fy=%.2f cx=%.2f cy=%.2f · 畸变 %s" % (ksrc, Km[0, 0], Km[1, 1], Km[0, 2], Km[1, 2], np.round(dist, 4)))

    views = []
    for line in open(os.path.join(a.session, "poses.jsonl"), encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        img = cv2.imread(r["img"])
        cs, grid = detect(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
        if cs is None:
            print("  样本%s: 板未检出" % r["idx"])
            continue
        o = objp(grid)
        ok, rvec, tvec = cv2.solvePnP(o, cs, Km, dist, flags=cv2.SOLVEPNP_ITERATIVE)
        proj, _ = cv2.projectPoints(o, rvec, tvec, Km, dist)
        rms = float(np.sqrt(np.mean(np.sum((proj.reshape(-1, 2) - cs) ** 2, axis=1))))
        R = cv2.Rodrigues(rvec)[0]
        views.append({"idx": r["idx"], "R_cb": R, "t_cb": tvec.reshape(3), "rms_px": rms,
                      "R_tb": quat_to_R(r["quat"]), "t_tb": np.array(r["tcp"], float), "grid": grid})
        print("  样本%-3s 板系→相机: 距离 %.3fm · 法向(相机系) %s · PnP 残差 %.3fpx"
              % (r["idx"], np.linalg.norm(tvec), np.round(R[:, 2], 3), rms))

    n = len(views)
    if n < 8:
        raise SystemExit("可用视图不足: %d" % n)

    # ② 纯平移视图自洽性: 机械臂只平移时 板在相机系的**姿态必须相同**
    print("\n[自洽性] 纯平移视图的板姿态对比(应≈相同):")
    base = views[0]
    for v in views:
        dp = np.linalg.norm(v["t_tb"] - base["t_tb"]) * 1000
        dang_tool = math.degrees(np.linalg.norm(Rot.from_matrix(v["R_tb"] @ base["R_tb"].T).as_rotvec()))
        dR_board = math.degrees(np.linalg.norm(Rot.from_matrix(v["R_cb"] @ base["R_cb"].T).as_rotvec()))
        print("  样本%-3s 工具平移 %6.1fmm · 工具转 %5.2f° → 板相对姿态变化 %6.2f° (只平移时应≈0)"
              % (v["idx"], dp, dang_tool, dR_board))

    # ③ 自解 X = T_cam2tool: 目标 使 Y_i = T_tool_base · X · T_board_cam 尽量相同
    def pack(R, t):
        return np.concatenate([t, Rot.from_matrix(R).as_rotvec()])

    def unpack(x):
        t = x[:3]
        R = Rot.from_rotvec(x[3:6]).as_matrix()
        return R, t

    def resid(x):
        Rx, tx = unpack(x[:6])
        Ry, ty = unpack(x[6:12])
        X = np.eye(4); X[:3, :3] = Rx; X[:3, 3] = tx
        Y0 = np.eye(4); Y0[:3, :3] = Ry; Y0[:3, 3] = ty
        out = []
        for v in views:
            G = np.eye(4); G[:3, :3] = v["R_tb"]; G[:3, 3] = v["t_tb"]
            C = np.eye(4); C[:3, :3] = v["R_cb"]; C[:3, 3] = v["t_cb"]
            Y = G @ X @ C
            out.append(Y[:3, 3] - Y0[:3, 3])
            out.append(Rot.from_matrix(Y[:3, :3] @ Y0[:3, :3].T).as_rotvec())
        return np.concatenate(out)

    best = None
    rng = np.random.default_rng(0)
    for trial in range(40):
        x0 = np.zeros(12)
        x0[:3] = rng.uniform(-0.15, 0.15, 3)
        x0[3:6] = rng.uniform(-math.pi, math.pi, 3) * (1.0 if trial else 0.0)
        x0[6:9] = views[0]["t_tb"]
        x0[9:12] = Rot.from_matrix(views[0]["R_cb"]).as_rotvec()
        try:
            r = least_squares(resid, x0, method="lm", max_nfev=20000)
        except Exception:                                                      # noqa: BLE001
            continue
        if best is None or r.cost < best.cost:
            best = r
    Rx, tx = unpack(best.x[:6])
    rms_t = float(np.sqrt(np.mean(best.fun[0::6] ** 2)) * 1000)
    rms_r = float(np.degrees(np.sqrt(np.mean(best.fun[1::6] ** 2))))
    print("\n[自解] X = T_cam2tool: t = %s m (模长 %.1fmm) · 姿态 RPY = %s°"
          % (np.round(tx, 4).tolist(), np.linalg.norm(tx) * 1000,
             np.round(Rot.from_matrix(Rx).as_euler("xyz", degrees=True), 2).tolist()))
    print("[质量] 板在基座系一致性残差: 平移 RMS %.2fmm · 姿态 RMS %.3f°  (判据: ≤3mm 且 ≤0.5°)"
          % (rms_t, rms_r))
    ok = (rms_t <= 3.0 and rms_r <= 0.5)
    print("结论: %s" % ("✅ 数据自洽, 可用" if ok else "❌ 数据不自洽 → 不落盘, 需重采/查因"))
    if ok:
        out = {"ok": True, "T_cam2tool": np.vstack([np.hstack([Rx, tx.reshape(3, 1)]), [0, 0, 0, 1]]).tolist(),
               "t_mm": (tx * 1000).round(2).tolist(), "rpy_deg": Rot.from_matrix(Rx).as_euler("xyz", degrees=True).round(3).tolist(),
               "resid_trans_mm_rms": round(rms_t, 3), "resid_rot_deg_rms": round(rms_r, 4),
               "views": [v["idx"] for v in views], "session": a.session}
        p = "/home/ubuntu/lerobot-smolvla-lew/models/handeye_state.json"
        json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("已落盘: %s" % p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
