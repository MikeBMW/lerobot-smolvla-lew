"""handeye_convention_test.py — 判机器人姿态约定(看相对旋转的轴方向, 比转角大小严格)"""
import glob
import math
import os
import sys

import numpy as np

sys.path.insert(0, "/home/ubuntu/lerobot-smolvla-lew/tools")
import cv2
import handeye_solve_ls as HS

SESS = os.path.dirname(sorted(glob.glob(os.path.expanduser("~/zmax_data/handeye/*/poses.jsonl")))[-1])
print("会话:", SESS)
VS = HS.load_views(SESS)
Km, _kpath = HS._K()
obj = HS.obj_points((4, 5), 0.020, transpose=False)
ok = []
for v in VS:
    good, rv, tv = cv2.solvePnP(obj, v["pts"], Km, None, flags=cv2.SOLVEPNP_ITERATIVE)
    if good and 0.05 < np.linalg.norm(tv) < 1.0:
        ok.append({"R_t": v["T_tool2base"][:3, :3], "T_b2c": HS._T(cv2.Rodrigues(rv)[0], tv.ravel())})
print("可用视图:", len(ok))

VAR = {"原序": lambda R: R, "转置": lambda R: R.T}
for k in range(3):
    P = np.eye(3)[:, [k, (k + 1) % 3, (k + 2) % 3]]
    VAR[f"轴置换{k}"] = (lambda P: (lambda R: P @ R @ P.T))(P)

for tag, f in VAR.items():
    A, B = [], []
    for i in range(len(ok) - 1):
        RA = f(ok[i]["R_t"]).T @ f(ok[i + 1]["R_t"])
        RB = ok[i + 1]["T_b2c"][:3, :3] @ ok[i]["T_b2c"][:3, :3].T
        a = cv2.Rodrigues(RA)[0].ravel()
        b = cv2.Rodrigues(RB)[0].ravel()
        if np.linalg.norm(a) > 1e-3 and np.linalg.norm(b) > 1e-3:
            A.append(a); B.append(b)
    if len(A) < 3:
        print(f"  {tag}: 有效对不足"); continue
    A = np.array(A); B = np.array(B)
    U, S, Vt = np.linalg.svd(B.T @ A)
    RX = U @ Vt
    res = [math.degrees(np.linalg.norm(a - RX @ b) / max(1e-9, np.linalg.norm(b))) for a, b in zip(A, B)]
    print(f"  {tag}: 轴残差中位 {np.median(res):.3f}° 最大 {max(res):.3f}° (正确≈0)")
