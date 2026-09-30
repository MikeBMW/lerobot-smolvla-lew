#!/usr/bin/env python3
"""把渲染图"插入区"放大成彩色分类字符画, 看清 光模块/插槽口/盒体 的像素关系

色类: G=绿(光模块体或hole标记) R=红(block_inner) W=亮(木质外盒/高光) B=偏蓝(半透明碰撞盒) K=暗
用法: gui-venv311/bin/python tools/zoom_insert_region.py <png> [x0 y0 x1 y1]
"""
import sys

import numpy as np
import cv2

png = sys.argv[1]
img = cv2.imread(png) if png != "-" else None
if img is None:
    print("读不到图")
    sys.exit(1)
x0, y0, x1, y1 = (int(v) for v in sys.argv[2:6]) if len(sys.argv) >= 6 else (230, 170, 350, 270)
reg = img[y0:y1, x0:x1]
print(f"{png} 区域 x[{x0}~{x1}] y[{y0}~{y1}]  ({reg.shape[1]}x{reg.shape[0]} px)")
step = max(1, int(min(reg.shape[:2]) / 40))
print(f"每格 {step}x{step} px; 列头是像素 x 的十位/个位滚动")
print("     " + "".join(str((x0 + c * step) // 10 % 10) if c % 5 == 0 else " "
                       for c in range(0, reg.shape[1], step)))
for yy in range(0, reg.shape[0], step):
    line = []
    for xx in range(0, reg.shape[1], step):
        blk = reg[yy:yy + step, xx:xx + step]
        b, g, r = blk[:, :, 0].mean(), blk[:, :, 1].mean(), blk[:, :, 2].mean()
        if g - max(r, b) > 40:
            c = "G"
        elif b - max(r, g) > 8:
            c = "B"
        elif r - max(g, b) > 25:
            c = "R"
        elif (r + g + b) / 3 > 110:
            c = "W"
        else:
            c = "K"
        line.append(c)
    print(f"{y0 + yy:4d} " + "".join(line))
print("\n颜色统计:", {c: int(np.sum(np.all([reg[:, :, 1] - np.maximum(reg[:, :, 2], reg[:, :, 0]) > 40] +
                                           [false] if False else [True] * reg.shape[:2], axis=0)))
                    for c in []} if False else "")
b, g, r = img[:, :, 0].astype(int), img[:, :, 1].astype(int), img[:, :, 2].astype(int)
mG = (g - np.maximum(r, b)) > 40
mB = (b - np.maximum(r, g)) > 8
mR = (r - np.maximum(g, b)) > 25
print(f"全图: 绿 {int(mG.sum())} px · 蓝 {int(mB.sum())} px · 红 {int(mR.sum())} px")
ys, xs = np.nonzero(mB)
if len(ys):
    print(f"蓝像素(半透明碰撞盒/立柱) 范围 x[{xs.min()}~{xs.max()}] y[{ys.min()}~{ys.max()}]"
          f" 质心 ({xs.mean():.0f},{ys.mean():.0f})")
sys.exit(0)
