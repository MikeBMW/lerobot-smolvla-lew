#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""handeye_diag.py — eye-in-hand 数据自检: 工具相对转角 必须等于 板在相机里的相对转角

原理 (硬约束, 与任何解法无关):
  相机在工具上 → 工具相对运动 A 与相机相对运动满足 A = X⁻¹ · C · X (纯旋转部分同样共轭) ⇒ **转角相同**
  又 板静止 ⇒ 板在相机里的相对运动 B 与相机相对运动互为逆 ⇒ **|angle(B)| = |angle(C)| = |angle(A)|
  所以: 对任意两个位姿, |angle(A_ij)| 必须 ≈ |angle(B_ij)|。
  若明显不等 → 姿态数据/四元数顺序/坐标系约定 有问题, 此时**任何解算都会崩**, 先修数据。
用法: gui-venv311/bin/python tools/handeye_diag.py [--session DIR]
"""
from __future__ import annotations

import argparse
import glob
import itertools
import json
import os
import sys

import cv2
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
from handeye_solve_ls import _K, _q2R, _quat_order, _T, detect, obj_points, GRID  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default=None)
    a = ap.parse_args()
    sess = a.session or sorted(glob.glob(os.path.expanduser("~/zmax_data/handeye/*/")))[-1]
    raw = [json.loads(l) for l in open(os.path.join(sess, "poses.jsonl"), encoding="utf-8") if l.strip()]
    order = _quat_order([r["quat"] for r in raw if r.get("quat")])
    Km, _ = _K()
    obj = obj_points(GRID, 20.0)
    rows = []
    for r in raw:
        img = cv2.imread(r["img"])
        if img is None:
            continue
        cs, grid = detect(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
        if cs is None:
            continue
        ok, rv, tv = cv2.solvePnP(obj, cs, Km, None, flags=cv2.SOLVEPNP_ITERATIVE)
        if not ok:
            continue
        rows.append({"idx": r["idx"], "T_t2b": _T(_q2R(r["quat"], order), r["tcp"]),
                     "T_b2c": _T(cv2.Rodrigues(rv)[0], tv.ravel()),
                     "tcp": r["tcp"], "cam_dist_mm": float(np.linalg.norm(tv))})
    print(f"会话 {os.path.basename(sess.rstrip('/'))} · 四元数顺序 {order} · 视图 {len(rows)}")
    print("每视图: 板距相机(mm) / TCP")
    for v in rows:
        print(f"  #{v['idx']}: {v['cam_dist_mm']:6.1f}mm · TCP {[round(x, 4) for x in v['tcp']]}")

    def ang(R):
        return float(np.degrees(np.linalg.norm(cv2.Rodrigues(R)[0])))

    print("\n两两位姿: |工具相对转角| vs |板在相机里相对转角| (应相等)")
    devs = []
    for i, j in itertools.combinations(range(len(rows)), 2):
        A = np.linalg.inv(rows[i]["T_t2b"]) @ rows[j]["T_t2b"]
        B = rows[j]["T_b2c"] @ np.linalg.inv(rows[i]["T_b2c"])
        ga, gb = ang(A[:3, :3]), ang(B[:3, :3])
        devs.append(abs(ga - gb))
        if i < 3 or (i, j) in ((0, len(rows) - 1),):
            print(f"  #{rows[i]['idx']}→#{rows[j]['idx']}: 工具 {ga:6.2f}° · 板 {gb:6.2f}° · 差 {abs(ga - gb):6.2f}°")
    devs = np.array(devs)
    print(f"\n全部 {len(devs)} 对: 差值 中位 {np.median(devs):.2f}° · 均值 {devs.mean():.2f}° · 最大 {devs.max():.2f}°")
    verdict = ("✅ 一致 (数据/约定 OK, 解法问题)" if np.median(devs) < 3.0
               else "❌ 不一致 → 姿态数据或四元数约定有问题 (先修数据, 别解算)")
    print("判定:", verdict)
    # 附加: 工具位移 vs 板在相机里位移 的相关性 (同向反向都应显著)
    print("\n附加: 工具位移 |Δt| 与 板在相机里位移 |Δt| (相关性)")

    def dpos(i, j):
        A = np.linalg.inv(rows[i]["T_t2b"]) @ rows[j]["T_t2b"]
        B = rows[j]["T_b2c"] @ np.linalg.inv(rows[i]["T_b2c"])
        return np.linalg.norm(A[:3, 3]) * 1000, np.linalg.norm(B[:3, 3])
    pairs = list(itertools.combinations(range(len(rows)), 2))[:3]
    for i, j in pairs:
        a1, b1 = dpos(i, j)
        print(f"  #{rows[i]['idx']}→#{rows[j]['idx']}: 工具 {a1:6.1f}mm · 板(相机系) {b1:6.1f}mm")


if __name__ == "__main__":
    main()
