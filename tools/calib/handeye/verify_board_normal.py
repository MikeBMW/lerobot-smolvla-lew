#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_board_normal.py — 用【检出的20个圆点】PnP 验证手眼旋转（决定性）

板平放在台面上 ⇒ 板的法向(=target系Z轴)在 base 系必须≈竖直(0,0,1)。
用 findCirclesGrid 检出点做 PnP（不用 RANSAC，无歧义），
再把 R_target2cam 的第三列经 T_base_cam 转到 base 系看是否竖直。
"""
import glob
import json
import math
import os
import re

import cv2
import numpy as np

D = "/tmp/scene/he16"
# CGB-020: 4x5 非对称圆阵列, 20mm 间距
# 非对称阵列标准点序: 行 i(0..4) 列 j(0..3): x=(2j + i%2)*20, y=i*20
OBJ = np.array([[(2 * j + i % 2) * 20.0, i * 20.0, 0.0] for i in range(5) for j in range(4)], np.float32)
K = np.array([[655.06, 0, 637.41], [0, 654.08, 357.77], [0, 0, 1.0]])
DIST = np.zeros(5)

T = np.array(json.load(open("/tmp/scene/handeye_result.json", encoding="utf-8"))["T_base_cam"], float)
R_bc = T[:3, :3]

angs = []
print("  ══ 各位姿: 板法向在 base 系的朝向（板平放 ⇒ 应≈竖直）══")
for f in sorted(glob.glob(D + "/c_*.png")):
    tag = os.path.basename(f)[2:-4]
    img = cv2.imread(f)
    if img is None:
        continue
    H, W = img.shape[:2]
    g0 = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    found = None
    for nm, src, ox, oy in (("全图", g0, 0, 0), ("裁剪", g0[281:668, 153:768], 153, 281)):
        for z in (1.0, 2.2, 3.0):
            gg = cv2.resize(src, None, fx=z, fy=z, interpolation=cv2.INTER_CUBIC) if z != 1.0 else src
            for pol in (cv2.bitwise_not(gg), gg):
                ok, cc = cv2.findCirclesGrid(pol, (4, 5), flags=cv2.CALIB_CB_ASYMMETRIC_GRID)
                if ok:
                    pts = cc.reshape(-1, 2) / z + np.array([ox, oy])
                    found = (pts, nm, z)
                    break
            if found:
                break
        if found:
            break
    if not found:
        print("    %-14s 未检出" % tag)
        continue
    pts, nm, z = found
    ok, rv, tv = cv2.solvePnP(OBJ, pts.astype(np.float64), K, DIST, flags=cv2.SOLVEPNP_ITERATIVE)
    if not ok:
        print("    %-14s PnP 失败" % tag)
        continue
    R_t2c, _ = cv2.Rodrigues(rv)
    z_tgt_cam = R_t2c[:, 2]                       # 板法向(相机系)
    n_base = R_bc @ z_tgt_cam
    n_base = n_base / np.linalg.norm(n_base)
    if n_base[2] < 0:
        n_base = -n_base
    a = float(np.degrees(math.acos(np.clip(abs(n_base[2]), -1, 1))))
    angs.append(a)
    print("    %-14s t_tgt_cam=(%6.1f,%6.1f,%6.1f)mm  法向(base)=(%+.3f,%+.3f,%+.3f)  偏竖直 **%5.1f°**"
          % (tag, tv[0,0]*1000, tv[1,0]*1000, tv[2,0]*1000, n_base[0], n_base[1], n_base[2], a))

print()
if angs:
    print("  ══ 结论 ══")
    print("    板法向偏竖直: 中位 **%.1f°** · max %.1f° · min %.1f° · 样本 %d"
          % (np.median(angs), max(angs), min(angs), len(angs)))
    if np.median(angs) < 8:
        print("    ✅ **手眼旋转部分正确**")
    elif np.median(angs) < 25:
        print("    ⚠ 有偏差但不离谱 ⇒ 位姿还不够，需更多/更大倾角")
    else:
        print("    🔴 偏差大 ⇒ 旋转部分不可信，需要更多位姿（等 he17 的 11 个）")
