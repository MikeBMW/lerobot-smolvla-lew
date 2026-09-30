#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""board_recheck_circles.py — 用**圆点阵列**检测器复核全部样本 (CGB-020 5×4 = 20 圆点 · 20mm)

老倪 2026-09-19: 「你的视觉语言判断输入的图像, 能看到20个白色圆点」
  → 5×4=20 点 = **圆点标定板**; 之前的"棋盘 4×3=12 角点"极可能是误检 (棋盘检测器把圆点间隙当角点)。
  本脚本对每张样本同时跑: 棋盘(4×3) / 圆点对称(5×4)(4×5) / 圆点非对称(4×11)(5×4) —— 交叉验证。
用法: gui-venv311/bin/python tools/board_recheck_circles.py [img ...]
"""
from __future__ import annotations

import glob
import os
import sys

import cv2

imgs = sys.argv[1:]
if not imgs:
    sess = sorted(glob.glob(os.path.expanduser("~/zmax_data/handeye/*/")))[-1]
    imgs = sorted(glob.glob(os.path.join(sess, "img", "*.png")))
print(f"复核 {len(imgs)} 张 · 圆点板 5×4 (20 点)\n")

sym = cv2.CALIB_CB_SYMMETRIC_GRID
asym = cv2.CALIB_CB_ASYMMETRIC_GRID
summ = {"circle": 0, "chess": 0, "none": 0}
for p in imgs:
    img = cv2.imread(p)
    if img is None:
        continue
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    res = []
    # ① 圆点 (对称 5×4 / 4×5; 非对称 5×4)
    for pat, pname in ((sym, "对称"), (asym, "非对称")):
        for grid in ((5, 4), (4, 5)):
            for blur in (0, 5):
                gg = cv2.GaussianBlur(g, (blur, blur), 0) if blur else g
                try:
                    ok, cs = cv2.findCirclesGrid(gg, grid, flags=pat)
                except Exception:                                              # noqa: BLE001
                    ok = False
                if ok:
                    res.append(f"圆点{grid[0]}x{grid[1]}({pname}{'/blur' if blur else ''}) {len(cs)}点")
                    break
            if res:
                break
        if res:
            break
    # ② 棋盘 (对照)
    fl = cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_NORMALIZE_IMAGE
    for extra in (cv2.CALIB_CB_FAST_CHECK, 0):
        ok, cs = cv2.findChessboardCorners(g, (4, 3), fl + extra)
        if ok:
            res.append(f"棋盘4x3 {len(cs)}角点")
            break
    tag = os.path.basename(p)
    if any(r.startswith("圆点") for r in res):
        summ["circle"] += 1
        verdict = "✅ " + " | ".join(res)
    elif res:
        summ["chess"] += 1
        verdict = "（仅棋盘检出）" + " | ".join(res)
    else:
        summ["none"] += 1
        verdict = "❌ 都无检出"
    print(f"  {tag}: {verdict}")

print(f"\n合计: 圆点检出 {summ['circle']} · 仅棋盘 {summ['chess']} · 都无 {summ['none']}")
