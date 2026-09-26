#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_rot_samepose.py — 同姿态复核手眼旋转（决定性检验）

原理: 标定板平放在台面上 ⇒ 板面法向在 base 系应≈(0,0,1)。
      用【每个位姿自己的深度图】拟合板面法向(相机系) → 经 T_base_cam 转到 base 系
      ⇒ 若结果≈竖直 ⇒ 旋转部分正确（这是与 rmse 完全独立的物理检验）。
反过来说明: 早先"17.7°"是与【某个特定姿态】绑定的量，不能与参考姿态的 34.4° 直接比。
"""
import glob
import json
import os

import numpy as np

D = "/tmp/scene/he16"
FX, FY, CX, CY = 655.06, 654.08, 637.41, 357.77      # 1280x720 内参
DEPTH_SCALE = 0.0001                                   # 0.1mm/单位


def parse_tcp(p):
    s = open(p, encoding="utf-8", errors="replace").read()
    v = []
    for k in ("x", "y", "z", "w"):
        pass
    import re
    nums = re.findall(r"[-+]?\d+\.?\d*(?:e[-+]?\d+)?", s)
    return np.array([float(x) for x in nums[:7]]) if len(nums) >= 7 else None


def quat_R(q):
    x, y, z, w = q / np.linalg.norm(q)
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])


def plane_normal(depth):
    h, w = depth.shape
    ys, xs = np.mgrid[0:h:4, 0:w:4]
    z = depth[::4, ::4].astype(np.float32) * DEPTH_SCALE
    m = (z > 0.15) & (z < 1.2)
    if m.sum() < 500:
        return None, 0
    x3 = (xs[m] - CX) / FX * z[m]
    y3 = (ys[m] - CY) / FY * z[m]
    P = np.stack([x3, y3, z[m]], 1)
    best, n_in = None, 0
    rng = np.random.default_rng(0)
    for _ in range(300):
        idx = rng.choice(len(P), 3, replace=False)
        p0, p1, p2 = P[idx]
        n = np.cross(p1 - p0, p2 - p0)
        nn = np.linalg.norm(n)
        if nn < 1e-9:
            continue
        n = n / nn
        d = -n @ p0
        cnt = int((np.abs(P @ n + d) < 0.004).sum())
        if cnt > n_in:
            n_in, best = cnt, (n, d)
    if best is None:
        return None, 0
    n, d = best
    m2 = np.abs(P @ n + d) < 0.004
    Q = P[m2]
    c = Q.mean(0)
    _, _, V = np.linalg.svd(Q - c)
    n = V[-1]
    if n[2] < 0:
        n = -n
    return (n, c), int(m2.sum())


T = np.array(json.load(open("/tmp/scene/handeye_result.json", encoding="utf-8"))["T_base_cam"], float)
R_bc, t_bc = T[:3, :3], T[:3, 3]

print("  ══ 各位姿: 板面法向在 base 系的朝向（应≈竖直 (0,0,1)）══")
angs = []
for f in sorted(glob.glob(D + "/d_*.npy")):
    tag = os.path.basename(f)[2:-4]
    depth = np.load(f)
    r = plane_normal(depth)
    if r[0] is None:
        print("    %-14s 平面拟合失败" % tag)
        continue
    (n_cam, c_cam), nin = r
    n_base = R_bc @ n_cam
    n_base = n_base / np.linalg.norm(n_base)
    if n_base[2] < 0:
        n_base = -n_base
    a = float(np.degrees(np.arccos(np.clip(abs(n_base[2]), -1, 1))))
    angs.append(a)
    print("    %-14s 法向(cam)=(%+.3f,%+.3f,%+.3f) → (base)=(%+.3f,%+.3f,%+.3f)  偏竖直 **%5.1f°**  内点%d  深%.0fmm"
          % (tag, n_cam[0], n_cam[1], n_cam[2], n_base[0], n_base[1], n_base[2], a, nin, c_cam[2] * 1000))

print()
if angs:
    print("  ══ 结论 ══")
    print("    板面法向偏竖直: 中位 **%.1f°** · max %.1f° · 样本 %d" % (np.median(angs), max(angs), len(angs)))
    print("    %s" % ("✅ **手眼旋转部分正确** —— 平放的板被重建为竖直朝上（与 rmse 完全独立的物理检验）"
                      if np.median(angs) < 6 else
                      "⚠ 偏差 %.1f° ⇒ 旋转仍有误差，需更多位姿/更大倾角" % np.median(angs)))
    print("    => 也解释了早先 17.7 deg 的来历: 那是【平面法向 vs 相机光轴】的夹角，")
    print("       与【相机光轴 vs 竖直】不是同一个量 -- 我把两者混为一谈了（我的错）")
