#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""board_probe_cgb.py — 按 CGB-020 5×4 20mm 规格精确探测标定板

老倪 2026-09-19: 「标定板的标准是 CGB-020 5*4 20mm Version B」

"5*4" 有两种常见解读, 都试:
  ① 5×4 = **内角点**数 (棋盘 6×5 方格)  → findChessboardCorners(5,4)
  ② 5×4 = **方格**数 → 内角点 4×3       → findChessboardCorners(4,3)
  ③ 5×4 = **圆点**阵列 (对称/非对称)     → findCirclesGrid(5,4)/(4,5)
同时对多张图跑 (当前帧 + 已采样本), 任何一张检出即算找到。
用法: gui-venv311/bin/python tools/board_probe_cgb.py [img1 img2 ...]
"""
from __future__ import annotations

import glob
import os
import sys

import cv2
import numpy as np

imgs = sys.argv[1:]
if not imgs:
    cands = [os.path.expanduser("~/zmax_ss_remote/cam_rs.png"),
             os.path.expanduser("~/zmax_ss_remote/cam_fp.png")]
    for d in sorted(glob.glob(os.path.expanduser("~/zmax_data/handeye/*/img")))[-2:]:
        cands += sorted(glob.glob(os.path.join(d, "*.png")))[-3:]
    imgs = [p for p in cands if os.path.exists(p)]
print(f"待检图 {len(imgs)} 张\n")

fl = cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_NORMALIZE_IMAGE
found = {}
for p in imgs:
    img = cv2.imread(p)
    if img is None:
        continue
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    tag = os.path.basename(os.path.dirname(p)) + "/" + os.path.basename(p)
    hits = []
    # ① 棋盘: 多组内角点规格
    for (c, r) in ((5, 4), (4, 5), (4, 3), (3, 4), (6, 5), (5, 6)):
        for use_fast in (True, False):
            f = fl + (cv2.CALIB_CB_FAST_CHECK if use_fast else 0)
            try:
                ok, corners = cv2.findChessboardCorners(g, (c, r), f)
            except Exception:                                                   # noqa: BLE001
                ok = False
            if ok:
                hits.append(f"棋盘内角点 {c}x{r} ({len(corners)} 个角点)")
                cv2.drawChessboardCorners(img, (c, r), corners, ok)
                break
        if hits:
            break
    # ② 圆点阵列
    if not hits:
        for pat, pname in ((cv2.CALIB_CB_SYMMETRIC_GRID, "对称"), (cv2.CALIB_CB_ASYMMETRIC_GRID, "非对称")):
            for (c, r) in ((5, 4), (4, 5)):
                try:
                    ok, centers = cv2.findCirclesGrid(g, (c, r), flags=pat)
                except Exception:                                               # noqa: BLE001
                    ok = False
                if ok:
                    hits.append(f"圆点阵列 {c}x{r} ({pname})")
                    break
            if hits:
                break
    # ③ 团块兜底 (圆点板常用 SimpleBlobDetector)
    if not hits:
        try:
            det = cv2.SimpleBlobDetector_create(cv2.SimpleBlobDetector_Params())
            kp = det.detect(g)
            big = [k for k in kp if k.size > 6]
            if len(big) >= 12:
                hits.append(f"疑似圆点候选 {len(big)} 个 (未成阵列, 需目视确认)")
        except Exception:                                                       # noqa: BLE001
            pass
    print(f"{tag:28s} {g.shape[1]}x{g.shape[0]} 均值{g.mean():5.1f} → "
          + ("✅ " + "; ".join(hits) if hits else "— 无"))
    if hits:
        found[tag] = hits
    cv2.imwrite(os.path.expanduser("~/zmax_data/board_probe_%s.png" % tag.replace("/", "_")), img)

print("\n结论:", ("✅ 检出 → " + str(found)) if found else
      "仍未检出 → 请把相机正对板停 2 秒(说一声), 我立刻再探; 或板上不是标准棋盘/圆点(可拍照给我描述)")
