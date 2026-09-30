#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""detect_circle_grid.py — 标定圆点阵列检测 + 亚像素级验证（实测配方）

用法:
  python detect_circle_grid.py --image frame.png --box 453 708 448 608
  python detect_circle_grid.py --image frame.png --box ... --depth d.npy --depth-scale 0.1

四个关键点，缺一即检出 0:
  · 分辨率: 圆点像素直径需 ~29px(1280x720 量级); 640x480 下 ~10px 检不出, 放大也救不回
  · 极性  : 白点黑底的板必须先反相(bitwise_not) —— findCirclesGrid 找的是暗斑
  · 模式  : 非对称圆阵列用 CALIB_CB_ASYMMETRIC_GRID; 用对称模式必然失败
  · 坐标  : 检测在放大图上做, 必须映射回全图坐标再配全图内参
            (否则主点错位一整个裁剪偏移量 ⇒ rmse 从 0.3px 虚高到 5px+, 尺寸错 2 倍)
"""
import argparse
import sys

import cv2
import numpy as np


def detect(img, box=None, scale=2.2, pattern=(4, 5), asym=True):
    """返回 (全图坐标点集, 放大图, 裁剪框)。检出失败返回 (None, 放大图, 框)。"""
    h, w = img.shape[:2]
    if box is None:
        x0, y0, x1, y1 = 0, 0, w, h
    else:
        x0, x1, y0, y1 = box
        x0, y0 = max(0, int(x0)), max(0, int(y0))
        x1, y1 = min(w, int(x1)), min(h, int(y1))
    crop = img[y0:y1, x0:x1]
    if crop.size == 0:
        return None, None, (x0, y0, x1, y1)
    big = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
    inv = cv2.bitwise_not(gray)                      # ★ 极性: 白点黑底必须反相
    flags = cv2.CALIB_CB_ASYMMETRIC_GRID if asym else cv2.CALIB_CB_SYMMETRIC_GRID
    ok, centers = cv2.findCirclesGrid(inv, pattern, flags=flags)
    if not ok:
        return None, big, (x0, y0, x1, y1)
    # ★ 坐标: 映射回全图坐标, 否则配全图 K 时主点错位
    pts = centers.reshape(-1, 2).astype(np.float64) / scale + np.array([x0, y0], dtype=np.float64)
    return pts, big, (x0, y0, x1, y1)


def asym_object_points(rows, cols, pitch_mm=1.0):
    """非对称圆阵列物点 (行间错半格)。pitch_mm=1.0 得到单位间距版, 用于自标定。"""
    return np.array([[2 * c + (r % 2), r, 0.0] for r in range(rows) for c in range(cols)],
                    dtype=np.float64) * pitch_mm


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--box", nargs=4, type=int, metavar=("X0", "X1", "Y0", "Y1"),
                    help="板区裁剪框; 不给则用全图")
    ap.add_argument("--scale", type=float, default=2.2)
    ap.add_argument("--pattern", nargs=2, type=int, default=[4, 5])
    ap.add_argument("--symmetric", action="store_true", help="默认按非对称圆阵列检测")
    ap.add_argument("--depth", help="深度 npy(uint16), 用于自标定真实间距")
    ap.add_argument("--depth-scale", type=float, default=0.1, help="mm/单位; D405 实测 0.1")
    ap.add_argument("--fx", type=float, default=655.06)
    ap.add_argument("--fy", type=float, default=654.08)
    ap.add_argument("--cx", type=float, default=637.41)
    ap.add_argument("--cy", type=float, default=357.77)
    ap.add_argument("--out", default="/tmp/grid_detect.jpg")
    a = ap.parse_args()

    img = cv2.imread(a.image)
    if img is None:
        print("读不到图: %s" % a.image)
        return 2
    print("图 %s" % (img.shape,))
    if img.shape[0] < 700:
        print("⚠ 高度 %d < 700: 640x480 量级下圆点仅 ~10px, 极可能检出 0 —— 先换 1280x720 取帧" % img.shape[0])

    pts, big, (x0, y0, x1, y1) = detect(img, a.box, a.scale, tuple(a.pattern), not a.symmetric)
    if pts is None:
        print("✗ 检出 0。按此序查: ①分辨率(量圆点像素直径) ②极性(反相没) ③阵列模式 ④裁剪框")
        return 1
    print("✓ 检出 %d 点 · 全图跨度 %.1f x %.1f px · 中心 (%.1f, %.1f)"
          % (len(pts), float(np.ptp(pts[:, 0])), float(np.ptp(pts[:, 1])),
             pts[:, 0].mean(), pts[:, 1].mean()))

    k = np.array([[a.fx, 0, a.cx], [0, a.fy, a.cy], [0, 0, 1]], dtype=np.float64)
    dist = np.zeros((5, 1))
    rows, cols = a.pattern[1], a.pattern[0]
    obj = asym_object_points(rows, cols, 1.0)
    if a.symmetric:
        obj = np.array([[c, r, 0.0] for r in range(rows) for c in range(cols)], dtype=np.float64)

    ok, rvec, tvec = cv2.solvePnP(obj, pts, k, dist, flags=cv2.SOLVEPNP_ITERATIVE)
    if not ok:
        print("✗ solvePnP 失败")
        return 1
    prj = cv2.projectPoints(obj, rvec, tvec, k, dist)[0].reshape(-1, 2)
    e = np.linalg.norm(prj - pts, axis=1)
    rmse = float(np.sqrt((e ** 2).mean()))
    print("单位间距 PnP: rmse=%.3f px · max=%.3f px  %s"
          % (rmse, e.max(), "(单位间距版 rmse 无意义, 看下面的毫米版)"))

    pitch = 1.0
    if a.depth:
        d = np.load(a.depth).astype(np.float64)
        vals = []
        for fx_, fy_ in pts:
            xi, yi = int(round(fx_)), int(round(fy_))
            patch = d[max(0, yi - 6):yi + 7, max(0, xi - 6):xi + 7]
            p = patch[patch > 0]
            if len(p):
                vals.append(np.median(p))
        if vals:
            z_board = float(np.median(vals)) * a.depth_scale / 1000.0
            r = cv2.Rodrigues(rvec)[0]
            for _ in range(8):                      # 迭代收敛
                obj_mm = obj * pitch
                ok, rvec2, tvec2 = cv2.solvePnP(obj_mm, pts, k, dist, flags=cv2.SOLVEPNP_ITERATIVE)
                r = cv2.Rodrigues(rvec2)[0]
                cen_z = float((r @ obj_mm.mean(0) + tvec2.ravel())[2])
                newp = pitch * z_board / cen_z
                if abs(newp - pitch) < 1e-4:
                    pitch = newp
                    break
                pitch = newp
            print("深度自标定: 板处实测 %.1f mm (%d/%d 点有效) ⇒ **真实间距 = %.2f mm**"
                  % (z_board * 1000, len(vals), len(pts), pitch))
            print("  板面物理尺寸 ≈ %.1f x %.1f mm" % (obj[:, 0].max() * pitch, obj[:, 1].max() * pitch))
        else:
            print("⚠ 深度图上对应位置无有效值, 跳过自标定")

    obj_mm = obj * pitch
    ok, rvec2, tvec2 = cv2.solvePnP(obj_mm, pts, k, dist, flags=cv2.SOLVEPNP_ITERATIVE)
    prj = cv2.projectPoints(obj_mm, rvec2, tvec2, k, dist)[0].reshape(-1, 2)
    e = np.linalg.norm(prj - pts, axis=1)
    rmse = float(np.sqrt((e ** 2).mean()))
    print("毫米尺度 PnP: **rmse=%.3f px** · max=%.3f px · |t|=%.1f mm  %s"
          % (rmse, e.max(), np.linalg.norm(tvec2), "✅ 合格(≤1px)" if rmse <= 1.0 else "⚠ 偏大 ⇒ 先查是不是拿裁剪坐标配了全图内参"))

    vis = big.copy() if big is not None else img.copy()
    cv2.drawChessboardCorners(vis, tuple(a.pattern), (pts - np.array([x0, y0])) * a.scale, True)
    t = "%d pts  pitch=%.2fmm  rmse=%.2fpx" % (len(pts), pitch, rmse)
    cv2.putText(vis, t, (15, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 5)
    cv2.putText(vis, t, (15, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
    cv2.imwrite(a.out, vis, [cv2.IMWRITE_JPEG_QUALITY, 93])
    print("→ %s" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
