#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""diag_aoi_frame.py — 诊断真机 AOI 帧: 结构/亮度分布 → 该选哪个 ROI (2026-09-24)"""
import glob
import os
import sys

import cv2
import numpy as np

CANDS = [
    os.path.expanduser("~/zmax_data/aoi_last_frame.png"),
    os.path.expanduser("~/zmax_data/aoi_v4_20260920/aoi_last_frame.png"),
] + sorted(glob.glob(os.path.expanduser("~/zmax_data/aoi_live/*"))) + \
    sorted(glob.glob(os.path.expanduser("~/lerobot-smolvla-lew/data/orin_live/*")))


def stats(img):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    return g


def main():
    shown = 0
    for p in CANDS:
        if not os.path.isfile(p) or not p.lower().endswith((".png", ".jpg", ".jpeg")):
            continue
        img = cv2.imread(p)
        if img is None:
            continue
        g = stats(img)
        H, W = g.shape
        print(f"\n=== {p}  {W}x{H}  mean={g.mean():.2f} std={g.std():.2f} "
              f"lap={cv2.Laplacian(g, cv2.CV_64F).var():.1f} clip_hi={(g>=250).mean()*100:.2f}%")
        # 3x3 网格结构分布 (梯度能量)
        print("    3x3 网格 梯度能量 (Tenengrad) / 亮度:")
        for r in range(3):
            row = []
            for c in range(3):
                t = g[r * H // 3:(r + 1) * H // 3, c * W // 3:(c + 1) * W // 3]
                gx = cv2.Sobel(t, cv2.CV_64F, 1, 0, ksize=3)
                gy = cv2.Sobel(t, cv2.CV_64F, 0, 1, ksize=3)
                row.append(f"E{np.mean(gx*gx+gy*gy):7.0f}/m{t.mean():5.1f}")
            print("      " + " | ".join(row))
        shown += 1
        if shown >= 3:
            break
    if not shown:
        print("❌ 未找到 AOI/真机帧")


if __name__ == "__main__":
    main()
