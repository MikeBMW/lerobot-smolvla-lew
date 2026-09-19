"""chk_board_normal.py — 查每个视图的板姿态是否翻转(平面靶标二义性)"""
import glob
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, "/home/ubuntu/lerobot-smolvla-lew/tools")
import handeye_solve_ls as HS

SESS = os.path.dirname(sorted(glob.glob(os.path.expanduser("~/zmax_data/handeye/*/poses.jsonl")))[-1])
Km, _ = HS._K()
VS = HS.load_views(SESS)
obj = HS.obj_points((4, 5), 0.020, transpose=False)
print("会话:", os.path.basename(SESS), "| 视图", len(VS))
for v in VS:
    ok, rv, tv = cv2.solvePnP(obj, v["pts"], Km, None, flags=cv2.SOLVEPNP_ITERATIVE)
    R = cv2.Rodrigues(rv)[0]
    n = R @ np.array([0, 0, 1.0])          # 板法向在相机系
    zc = float(tv[2, 0])
    print(f"  #{v['idx']} z_cam={zc*1000:7.1f}mm  法向·光轴={n[2]:+.3f}  "
          f"{'✅朝向相机' if n[2] < -0.5 else ('⚠️翻转/侧向' if n[2] > 0 else '斜视')}")
    # 每个点对 PnP 的残差
    pr, _ = cv2.projectPoints(obj, rv, tv, Km, None)
    e = np.linalg.norm(pr.reshape(-1, 2) - v["pts"], axis=1)
    print(f"       PnP 残差: 中位 {np.median(e):.3f}px 最大 {e.max():.3f}px")
