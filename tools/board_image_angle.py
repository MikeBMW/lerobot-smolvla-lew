#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""board_image_angle.py — 纯图像判定: 标定板在画面里的**朝向角**与**尺寸**

用途 (老倪现场, 2026-09-19): 解掉"相机在法兰上但板在画面里不转"的矛盾。
  ① 板朝向角 (deg): 由 20 个点的 PCA 主方向给出 —— **纯图像量, 不依赖任何位姿/内参**
  ② 板在画面里的尺度 (px): 相邻点间距中位 → 反映**板到相机的距离**
  判读:
    · 你只转手腕 (位置不动) → 若"板朝向角"跟着变 ≈ 你的转量 ⇒ 相机确实在法兰上 ✓
                             若朝向角几乎不变 ⇒ 板与相机在**同一刚体**上 (板装在臂上) → 该布局无法标定
    · 你只沿光轴升降 → 朝向角不变但尺度变 ⇒ 正常 (距离变化)
用法: gui-venv311/bin/python tools/board_image_angle.py [--session DIR]
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys

import cv2
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
from handeye_solve_ls import detect   # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default=None)
    a = ap.parse_args()
    sess = a.session or sorted(glob.glob(os.path.expanduser("~/zmax_data/handeye/*/")))[-1]
    rows = [json.loads(l) for l in open(os.path.join(sess, "poses.jsonl"), encoding="utf-8") if l.strip()]
    print(f"会话 {os.path.basename(sess.rstrip('/'))}\n")
    print("样本 | 板朝向角(deg) | 尺度(px, 相邻点间距) | 板质心 | TCP")
    base = None
    for r in rows:
        g = cv2.cvtColor(cv2.imread(r["img"]), cv2.COLOR_BGR2GRAY)
        cs, _ = detect(g)
        if cs is None:
            print(f"  #{r['idx']} | 未检出")
            continue
        c = cs - cs.mean(axis=0)
        u, s, vt = np.linalg.svd(c, full_matrices=False)
        d = vt[0] / (np.linalg.norm(vt[0]) or 1)
        ang = math.degrees(math.atan2(d[1], d[0]))
        ang = (ang + 90) % 180 - 90          # 归一到 (-90, 90]
        # 尺度: 最近邻距离中位
        dd = np.sort(np.linalg.norm(cs[:, None, :] - cs[None, :, :], axis=2), axis=1)[:, 1]
        scale = float(np.median(dd))
        cen = cs.mean(axis=0)
        t = r["tcp"]
        if base is None:
            base = (ang, scale)
        print(f"  #{r['idx']} | {ang:7.2f} (Δ{ang - base[0]:+6.2f}) | {scale:6.1f} (Δ{scale - base[1]:+5.1f}) | "
              f"[{cen[0]:5.1f},{cen[1]:5.1f}] | [{t[0]:.4f}, {t[1]:.4f}, {t[2]:.4f}]")
    print("\n判读: 只转手腕时 '板朝向角' 应跟着变; 只升降时 '尺度' 应变")


if __name__ == "__main__":
    main()
