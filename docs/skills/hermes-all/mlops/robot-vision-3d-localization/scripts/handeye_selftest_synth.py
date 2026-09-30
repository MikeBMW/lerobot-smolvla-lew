#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""handeye_selftest_synth.py — eye-in-hand 解算器自证 (合成数据, 物理成立, 确定性)

为什么必须有它 (2026-09-19 现场教训):
  真机数据连崩时, 无法区分"解算器坏" vs "数据/单位/约定坏"。
  合成数据把地面真值握在手里 → 3 分钟定位到底哪一层错。
  ⚠️ 两个坑: ① 物点单位必须与机器人位姿一致(都用米); ② 场景必须物理成立 ——
  **板必须在相机前方**(断言 t_z>0), 否则 solvePnP 合理返回镜像解, 表象酷似"解算器坏了"。

用法:
  gui-venv311/bin/python tools/handeye_selftest_synth.py
判据: 真值处残差 ≈1e-6px; 解出 X 与真值差 <2mm / <0.5° / 重投影 <0.5px。
"""
import math
import sys

import cv2
import numpy as np

sys.path.insert(0, "/home/ubuntu/lerobot-smolvla-lew/tools")
import handeye_solve_ls as HS


def main():
    rng = np.random.default_rng(7)
    Km = np.array([[401.8, 0, 317.2], [0, 401.8, 236.5], [0, 0, 1.0]])
    grid, spacing = (4, 5), 20.0
    obj = HS.obj_points(grid, spacing / 1000.0).reshape(-1, 1, 3)     # ⚠️ 米制, 与位姿一致

    # 物理场景: 板放台面 (z 向上), 相机在板上方 ~30cm 俯视
    T_b2base = np.eye(4)
    T_b2base[:3, 3] = [0.45, 0.0, 0.10]
    R_lookdown = cv2.Rodrigues(np.array([math.pi, 0.0, 0.0]))[0]      # 光轴朝下
    X_true = np.eye(4)                                                # 相机→工具
    X_true[:3, :3] = cv2.Rodrigues(np.array([0.04, -0.02, 0.03]))[0]
    X_true[:3, 3] = np.array([0.005, -0.01, 0.09])

    views = []
    for i in range(8):
        T_c2b = np.eye(4)
        T_c2b[:3, :3] = R_lookdown @ cv2.Rodrigues(rng.normal(size=3) * 0.20)[0]
        T_c2b[:3, 3] = T_b2base[:3, 3] + np.array([0, 0, 0.30]) + rng.normal(size=3) * 0.03
        T_t2b = T_c2b @ np.linalg.inv(X_true)                         # 工具位姿(机器人给)
        T_b2c = np.linalg.inv(T_c2b) @ T_b2base
        assert T_b2c[2, 3] > 0, "板必须在相机前方 (物理成立)"
        pr, _ = cv2.projectPoints(obj, cv2.Rodrigues(T_b2c[:3, :3])[0], T_b2c[:3, 3].reshape(3, 1), Km, None)
        views.append({"idx": i + 1, "pts": pr.reshape(-1, 2), "T_tool2base": T_t2b, "grid": grid})

    r = HS.solve(views, Km, grid, spacing)
    if r is None:
        print("❌ 解算返回 None")
        return 1
    Xe = r["X"]
    dt = Xe[:3, 3] - X_true[:3, 3]
    dR = Xe[:3, :3] @ X_true[:3, :3].T
    ang = math.degrees(math.acos(max(-1, min(1, (np.trace(dR) - 1) / 2))))
    print("真值 X: 平移(mm) %s" % np.round(X_true[:3, 3] * 1000, 2))
    print("解出 X: 平移(mm) %s" % np.round(Xe[:3, 3] * 1000, 2))
    print("平移误差 %.2f mm · 旋转误差 %.3f° · 重投影中位 %.4f px"
          % (np.linalg.norm(dt) * 1000, ang, r["median_px"]))
    good = np.linalg.norm(dt) * 1000 < 2 and ang < 0.5 and r["median_px"] < 0.5
    print("判定:", "✅ 解算器可信 (合成数据可复原)" if good else "❌ 解算器有问题")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
