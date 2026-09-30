#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""handeye_diag2.py — 判定两件事: ①板图案是对称还是非对称 ②内参 K 到底对不对 (用板图自标定)

老倪 2026-09-19 现场排查: 手眼解算连崩三次 → 嫌疑
  A. 我加载的 K (fx=394, 来自 D405 camera_info) **可能不是**出图那台相机的 → 用板图**自标定 K** 一比就知道
  B. 圆点阵列 5×4 可能是**对称**排布(不是非对称) → 物点坐标生成错 → 解算全崩
做法:
  ① 分别用 对称(5,4)/(4,5) 与 非对称(4,5)/(5,4) 检测, 报哪个成立 + 首行/次行是否半格错位(判别对称/非对称)
  ② cv2.calibrateCamera(20 点物点, 检测点, 640×480) → 自标定 K / 畸变 / 每视图重投影误差
  ③ 与加载的 K 对比 (fx/fy/cx/cy 差异)
用法: gui-venv311/bin/python tools/handeye_diag2.py [--session DIR]
"""
from __future__ import annotations

import argparse
import glob
import json
import os

import cv2
import numpy as np


def obj_sym(grid, s):
    cols, rows = grid
    out = []
    for i in range(rows):
        for j in range(cols):
            out.append([j * s, i * s, 0.0])
    return np.array(out, np.float32)


def obj_asym(grid, s):
    cols, rows = grid
    out = []
    for i in range(rows):
        for j in range(cols):
            out.append([(2 * j + (i % 2)) * s, i * s, 0.0])
    return np.array(out, np.float32)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default=None)
    ap.add_argument("--spacing", type=float, default=20.0)
    a = ap.parse_args()
    sess = a.session or sorted(glob.glob(os.path.expanduser("~/zmax_data/handeye/*/")))[-1]
    rows = [json.loads(l) for l in open(os.path.join(sess, "poses.jsonl"), encoding="utf-8") if l.strip()]
    S = a.spacing

    print(f"会话: {sess}\n")
    # ① 图案类型判定: 用非对称检测跑一次, 看检测点在各行的 x 是否半格错位
    for r in rows[:2]:
        img = cv2.imread(r["img"])
        if img is None:
            continue
        src = 255 - cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        print(f"--- 样本 #{r['idx']} 图案判定 ---")
        for pat, pn in ((cv2.CALIB_CB_ASYMMETRIC_GRID, "非对称"), (cv2.CALIB_CB_SYMMETRIC_GRID, "对称")):
            for grid in ((4, 5), (5, 4)):
                try:
                    ok, cs = cv2.findCirclesGrid(src, grid, flags=pat)
                except Exception:                                              # noqa: BLE001
                    ok = False
                if not ok:
                    print(f"   {pn} {grid[0]}x{grid[1]}: ✗")
                    continue
                pts = cs.reshape(-1, 2)
                # 每行 4 个点 (若 grid=(4,5)): 看行内 x 单调 + 相邻行 x 是否错位半格
                cols, rws = grid
                lines = pts.reshape(rws, cols, 2)
                row0 = np.sort(lines[0][:, 0])
                row1 = np.sort(lines[1][:, 0])
                step = float(np.median(np.diff(row0)))
                off = float(np.median(row1) - np.median(row0))
                kind = "半格错位→非对称" if abs(off) > 0.25 * step else "对齐→对称"
                print(f"   {pn} {grid[0]}x{grid[1]}: ✅ {len(pts)}点 · 行内步长 {step:.1f}px · "
                      f"相邻行偏移 {off:+.1f}px ({off / step:+.2f} 格) → {kind}")

    # ② 自标定 K (用板点, 两种物点都试, 取重投影误差小的)
    img_pts = []
    for r in rows:
        img = cv2.imread(r["img"])
        if img is None:
            continue
        src = 255 - cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        ok, cs = cv2.findCirclesGrid(src, (4, 5), flags=cv2.CALIB_CB_ASYMMETRIC_GRID)
        if ok and len(cs) == 20:
            img_pts.append(cs.reshape(-1, 1, 2))
    print(f"\n--- ② 用 {len(img_pts)} 张板图自标定内参 ---")
    if len(img_pts) < 5:
        print("图太少, 跳过自标定")
        return
    for name, maker in (("非对称", obj_asym), ("对称", obj_sym)):
        obj = maker((4, 5), S).reshape(-1, 1, 3)
        objs = [obj] * len(img_pts)
        try:
            rms, K, dist, rv, tv = cv2.calibrateCamera(objs, img_pts, (640, 480), None, None)
        except Exception as e:                                                 # noqa: BLE001
            print(f"   {name}: 标定失败 {type(e).__name__}: {e}")
            continue
        print(f"   {name}: 重投影 RMS {rms:.3f}px → fx {K[0,0]:.1f} fy {K[1,1]:.1f} "
              f"cx {K[0,2]:.1f} cy {K[1,2]:.1f} · 畸变 {np.round(dist.ravel()[:3], 4).tolist()}")
        # 每视图板距相机 (用自标定 K)
        ds = [round(float(np.linalg.norm(t)), 3) for t in tv[:5]]
        print(f"        各视图板距相机(自标定K): {ds} (单位=mm, 应 ~200~500)")
    print("\n对比: 我加载的 K (D405 camera_info) = fx 394.1 fy 393.5 cx 318.4 cy 238.7")
    print("判读: 若自标定 fx 与 394 差得多 (如 500+ 或 300-), 说明**出图相机不是 D405** → 必须用自标定 K")


if __name__ == "__main__":
    main()
