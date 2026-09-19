#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""board_probe.py — 看一眼真机画面里"标定板"是什么图案 (决定用手眼标定的检测算法)

老倪 2026-09-19: 「相机是固定在协作臂上, 标定板在相机的下面, 相机镜头正对着标定板, 大概 50 厘米」

依次尝试 (全部只读图像, 不动机器人):
  ① ArUco / AprilTag  (cv2.aruco, 多个字典)
  ② 棋盘格 (findChessboardCorners, 常见规格 9x6 / 11x8 / 8x6 / 7x5 / 6x4 / 10x7 ...)
  ③ 圆点阵列 (findCirclesGrid, 对称/非对称)
  ④ 都没有 → 输出图像统计 (尺寸/灰度/边缘密度/最暗最亮块) 供人工判断, 并保存一份放大图给你看
用法: gui-venv311/bin/python tools/board_probe.py [图片路径]
"""
from __future__ import annotations

import os
import sys

import cv2
import numpy as np

IMG = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/zmax_ss_remote/cam_rs.png")

img = cv2.imread(IMG)
if img is None:
    raise SystemExit(f"读不到图像: {IMG}")
h, w = img.shape[:2]
gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
print(f"图像: {IMG}  {w}x{h}  灰度 均值{gray.mean():.1f} 标准差{gray.std():.1f} "
      f"min{gray.min()} max{gray.max()}")

# ① ArUco / AprilTag
found_ar = []
try:
    dicts = [("DICT_4X4_50", cv2.aruco.DICT_4X4_50), ("DICT_5X5_100", cv2.aruco.DICT_5X5_100),
             ("DICT_6X6_250", cv2.aruco.DICT_6X6_250), ("DICT_APRILTAG_36h11", getattr(cv2.aruco, "DICT_APRILTAG_36h11", -1)),
             ("DICT_ARUCO_ORIGINAL", cv2.aruco.DICT_ARUCO_ORIGINAL)]
    for name, did in dicts:
        if did < 0:
            continue
        try:
            dd = cv2.aruco.getPredefinedDictionary(did)
            det = cv2.aruco.ArucoDetector(dd, cv2.aruco.DetectorParameters())
            corners, ids, _ = det.detectMarkers(gray)
        except Exception:                                                       # noqa: BLE001
            if not hasattr(cv2.aruco, "DetectorParameters_create"):
                continue
            corners, ids, _ = cv2.aruco.detectMarkers(gray, dd)
        if ids is not None and len(ids):
            found_ar.extend([(name, int(i)) for i in ids.flatten()])
except Exception as e:                                                          # noqa: BLE001
    print("  (aruco 检测异常:", type(e).__name__, e, ")")
print(f"① ArUco/AprilTag: {'✅ 检出 ' + str(found_ar[:8]) if found_ar else '未检出'}")

# ② 棋盘格
CHESS = [(9, 6), (11, 8), (8, 6), (7, 5), (6, 4), (10, 7), (9, 7), (11, 7), (12, 9), (13, 9)]
flags = cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_NORMALIZE_IMAGE + cv2.CALIB_CB_FAST_CHECK
hit_chess = None
for (c, r) in CHESS:
    ok, _ = cv2.findChessboardCorners(gray, (c, r), flags)
    if ok:
        hit_chess = (c, r)
        break
print(f"② 棋盘格: {'✅ 检出 ' + str(hit_chess) + ' (内角点)' if hit_chess else '未检出 (试过 ' + ', '.join(f'{c}x{r}' for c, r in CHESS) + ')'}")

# ③ 圆点阵列
hit_circ = None
for pat in (cv2.CALIB_CB_SYMMETRIC_GRID, cv2.CALIB_CB_ASYMMETRIC_GRID):
    for (c, r) in ((7, 7), (9, 9), (11, 9), (4, 11), (5, 7)):
        ok, _ = cv2.findCirclesGrid(gray, (c, r), flags=pat)
        if ok:
            hit_circ = (c, r, "对称" if pat == cv2.CALIB_CB_SYMMETRIC_GRID else "非对称")
            break
    if hit_circ:
        break
print(f"③ 圆点阵列: {'✅ 检出 ' + str(hit_circ) if hit_circ else '未检出'}")

# ④ 视觉统计 + 放大图 (人工核对)
edges = cv2.Canny(gray, 60, 160)
print(f"④ 边缘密度: {100.0 * (edges > 0).mean():.2f}%  (格子/文字多 → 偏高)")
gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
mag = np.hypot(gx, gy)
step = h // 6
print("    六条横带梯度能量 (上→下, 找格子密度分布):",
      " ".join(f"{mag[i*step:(i+1)*step].mean():6.1f}" for i in range(6)))
out = os.path.expanduser("~/zmax_data/board_probe_%" +
                         os.path.basename(IMG).replace(".png", "") + "_marks.png")
vis = img.copy()
if found_ar:
    try:
        dd = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        corners, ids, _ = cv2.aruco.ArucoDetector(dd, cv2.aruco.DetectorParameters()).detectMarkers(gray)
        if ids is not None:
            cv2.aruco.drawDetectedMarkers(vis, corners, ids)
    except Exception:                                                          # noqa: BLE001
        pass
cv2.imwrite(out, vis)
print(f"    标注图已存: {out}   (老倪可直接打开看板上图案)")
print("\n结论:", "ArUco/AprilTag 板" if found_ar else
      ("棋盘格板 " + str(hit_chess) if hit_chess else
       ("圆点板 " + str(hit_circ) if hit_circ else "未识别出标准标定板图案 → 需要你告诉我板上是什么 (或拍清楚一点/换个位姿)")))
