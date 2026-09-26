#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""a5_offline_analysis.py — 对已存三帧做离线分析 (零动作): 归一化差分 / 边缘差分, 判能否追踪运动中的臂"""
import os
import numpy as np
import cv2

OUT = "/home/ubuntu/zmax_rel/data/handeye"
fs = ["img_diff00.png", "img_diff01.png", "img_diff02.png"]
gs = []
for f in fs:
    p = os.path.join(OUT, f)
    if not os.path.isfile(p):
        print("缺", f)
        continue
    g = cv2.cvtColor(cv2.imread(p), cv2.COLOR_BGR2GRAY).astype(np.float32)
    gs.append((f, g))
    sat = float((g >= 250).mean() * 100)
    print("%s 均值%.1f std%.1f 饱和%.1f%%" % (f, g.mean(), g.std(), sat))

if len(gs) >= 2:
    print("\n=== ① 归一化差分 (z-score, 消除曝光漂移) ===")
    zs = [(f, (g - g.mean()) / (g.std() + 1e-6)) for f, g in gs]
    b = zs[0][1]
    for f, z in zs[1:]:
        d = np.abs(z - b)
        m = (d > 0.5).astype(np.uint8)
        area = int(m.sum())
        pct = area / m.size * 100
        if area > 200:
            ys, xs = np.nonzero(m)
            print("  %s: 变化 %d (%.2f%%) 质心(u,v)=(%.0f,%.0f) x[%d,%d] y[%d,%d]" %
                  (f, area, pct, xs.mean(), ys.mean(), xs.min(), xs.max(), ys.min(), ys.max()))
        else:
            print("  %s: 变化 %d (%.2f%%)" % (f, area))

    print("\n=== ② 边缘差分 (Canny 后比, 对光照最鲁棒) ===")
    es = [(f, cv2.Canny(np.clip(g, 0, 255).astype(np.uint8), 60, 160)) for f, g in gs]
    b2 = es[0][1]
    kern = np.ones((5, 5), np.uint8)
    for f, e in es[1:]:
        m = cv2.dilate(b2, kern)
        new_edge = np.logical_and(e > 0, m == 0).astype(np.uint8)
        area = int(new_edge.sum())
        if area > 100:
            ys, xs = np.nonzero(new_edge)
            print("  %s: 新增边缘 %d · 质心(u,v)=(%.0f,%.0f) x[%d,%d] y[%d,%d]" %
                  (f, area, xs.mean(), ys.mean(), xs.min(), xs.max(), ys.min(), ys.max()))
        else:
            print("  %s: 新增边缘 %d (几乎无结构变化)" % (f, area))
