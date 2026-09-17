#!/usr/bin/env python3
"""把渲染帧降采样成字符画 (我看不了图, 但能读字符) —— 用于判断"光模块 vs 插槽"在画面里的关系

图例:
  P = 绿色像素 (光模块体, rgba 0.3/1.0/0.3)
  # = 亮结构 (盒子/台面/相机近处)
  · = 中灰 (背景/远台面)
  ' ' = 暗 (阴影/空隙)
每格取 4x4 像素均值; 行首列号=像素 y, 顶部标像素 x 刻度。

用法: DISPLAY=:0 gui-venv311/bin/python tools/ascii_render.py <png|-> [--cols 96]
"""
import argparse
import os
import sys

import numpy as np
import cv2

ap = argparse.ArgumentParser()
ap.add_argument("png")
ap.add_argument("--cols", type=int, default=96)
a = ap.parse_args()

img = cv2.imread(a.png) if a.png != "-" else None
if img is None:
    print("读不到图")
    sys.exit(1)
H, W = img.shape[:2]
cols = a.cols
rows = max(8, int(cols * H / W / 2))            # 字符高宽比 ~2:1
b, g, r = img[:, :, 0].astype(int), img[:, :, 1].astype(int), img[:, :, 2].astype(int)
green = (g - np.maximum(r, b)) > 40

cell_h, cell_w = H / rows, W / cols
print(f"{a.png}  {W}x{H} → {cols}x{rows} 字符")
print("     " + "".join(str((int(c * cell_w) // 100) % 10) if c % 8 == 0 else " "
                       for c in range(cols)))
for rr in range(rows):
    y0, y1 = int(rr * cell_h), max(int(rr * cell_h) + 1, int((rr + 1) * cell_h))
    line = []
    for cc in range(cols):
        x0, x1 = int(cc * cell_w), max(int(cc * cell_w) + 1, int((cc + 1) * cell_w))
        blk = img[y0:y1, x0:x1]
        gm = green[y0:y1, x0:x1]
        if gm.mean() > 0.25:
            line.append("P")
            continue
        lum = float(blk.mean())
        line.append("#" if lum > 110 else ("·" if lum > 55 else " "))
    print(f"{int(y0):4d} " + "".join(line))
sys.exit(0)
