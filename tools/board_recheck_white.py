#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""board_recheck_white.py — 数白点 + 反色重试 (白点黑底场景)

老倪 2026-09-19: 「你的视觉语言判断输入的图像, 能看到20个白色圆点」
  → 若板是**白点黑底**, OpenCV findCirclesGrid 需要**反色**才找得到。本脚本:
    ① SimpleBlobDetector 数"亮斑"(blobColor=255) → 看是不是 ~20 个白点
    ② 原图 / 反色图 两种极性都跑 findCirclesGrid(5×4, 4×5; 对称/非对称)
    ③ 报白斑的 圆心/半径/圆度, 便于判断是不是标定板
用法: gui-venv311/bin/python tools/board_recheck_white.py [img ...]
"""
from __future__ import annotations

import glob
import os
import sys

import cv2
import numpy as np

imgs = sys.argv[1:]
if not imgs:
    sess = sorted(glob.glob(os.path.expanduser("~/zmax_data/handeye/*/")))[-1]
    imgs = sorted(glob.glob(os.path.join(sess, "img", "*.png")))
print(f"复核 {len(imgs)} 张 (数白点 + 反色找圆点阵列)\n")


def blob_params(dark=False):
    p = cv2.SimpleBlobDetector_Params()
    p.filterByColor = True
    p.blobColor = 0 if dark else 255
    p.filterByArea = True
    p.minArea = 4
    p.maxArea = 4000
    p.filterByCircularity = True
    p.minCircularity = 0.55
    p.filterByConvexity = True
    p.minConvexity = 0.7
    p.filterByInertia = False
    return p


for p in imgs:
    img = cv2.imread(p)
    if img is None:
        continue
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    det = cv2.SimpleBlobDetector_create(blob_params(False))
    kp = det.detect(g)
    inv = 255 - g
    detd = cv2.SimpleBlobDetector_create(blob_params(True))
    kpd = detd.detect(g)
    hits = []
    for name, src in (("原图", g), ("反色", inv)):
        for pat, pn in ((cv2.CALIB_CB_SYMMETRIC_GRID, "对称"), (cv2.CALIB_CB_ASYMMETRIC_GRID, "非对称")):
            for grid in ((5, 4), (4, 5)):
                try:
                    ok, cs = cv2.findCirclesGrid(src, grid, flags=pat)
                except Exception:                                              # noqa: BLE001
                    ok = False
                if ok:
                    hits.append(f"{name}圆点{grid[0]}x{grid[1]}({pn}) {len(cs)}点")
                    break
            if hits:
                break
        if hits:
            break
    szs = sorted(round(k.size, 1) for k in kp)
    print(f"  {os.path.basename(p)}: 亮斑 {len(kp)} 个 (尺寸 {szs[:6]}{'...' if len(szs) > 6 else ''}) · "
          f"暗斑 {len(kpd)} 个 → " + ("✅ " + "; ".join(hits) if hits else "未成阵列"))
