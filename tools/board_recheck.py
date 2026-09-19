#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""board_recheck.py — 用更鲁棒的检测器复核"板不在画面"的样本

老倪 2026-09-19: 转手腕后 #5~#8 全部报"板不在画面" → 先分清是**真看不到板**还是**检测器不够强**:
  ① 经典 findChessboardCorners (原判定, 含 FAST_CHECK / 无)
  ② **findChessboardCornersSB** (sector-based, 抗透视/畸变强, 4×3 棋盘首选)
  ③ 无检出时给出画面统计 (亮度/边缘密度/板可能在视场外)
用法: gui-venv311/bin/python tools/board_recheck.py [img ...]
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
print(f"复核 {len(imgs)} 张\n")
pat = (4, 3)
for p in imgs:
    img = cv2.imread(p)
    if img is None:
        continue
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    r1 = r2 = None
    fl = cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_NORMALIZE_IMAGE
    for extra in (cv2.CALIB_CB_FAST_CHECK, 0):
        ok, cs = cv2.findChessboardCorners(g, pat, fl + extra)
        if ok:
            r1 = len(cs)
            break
    try:
        ok2, cs2 = cv2.findChessboardCornersSB(g, pat)
        if ok2:
            r2 = len(cs2)
    except Exception as e:                                                     # noqa: BLE001
        r2 = f"err {type(e).__name__}"
    tag = os.path.basename(p)
    verdict = "✅ SB 检出(原来漏了)" if (r1 is None and r2) else (
        "✅ 两者都检出" if r1 and r2 else ("经典检出/SB无" if r1 and not r2 else "❌ 都没检出(板确实不在视场或太斜)"))
    print(f"{tag}: 经典 {r1 or '—'} · SB {r2 or '—'} → {verdict}")
