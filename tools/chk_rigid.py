"""chk_rigid.py — 刚体不变量自检(无需 X): 工具位移模长 必须 = 板在相机里的位移模长"""
import glob
import itertools
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
recs = []
for v in VS:
    R, t = HS._board_pose(v["pts"], obj, Km)
    recs.append((v["idx"], v["T_tool2base"], R, t))
print("会话", os.path.basename(SESS))
print(" 对    |Δ工具| mm   |Δ板在相机| mm   差 mm")
for (i, A, _, ta), (j, B, _, tb) in itertools.combinations(recs, 2):
    dt = np.linalg.norm(A[:3, 3] - B[:3, 3]) * 1000
    db = np.linalg.norm(ta - tb) * 1000
    print(f" #{i}-#{j}   {dt:9.1f}      {db:9.1f}      {db - dt:+8.1f}")
