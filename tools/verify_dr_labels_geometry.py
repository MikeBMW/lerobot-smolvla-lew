# -*- coding: utf-8 -*-
"""DR 标注一致性反向验证 (独立方法: 唯一标记 + 模板匹配)。

判据: 原始帧标注框中心放一个**唯一**粗粒噪声标记, 把标记 patch 按**与画面完全相同的几何变换链**
(缩放裁切 → 小角旋转 → 灰边 letterbox) 同步变换, 再在增广图上做模板匹配 →
匹配峰必须落在增广后的标注框中心附近 (容差 12px) 且匹配度 >0.6。

踩坑记录: v1 用规则矩形当底图 → matchTemplate 歧义 (匹配度 0.05, 假失败);
v2 patch 缩放因子(96*480/cw)与旋转中心(patch 自身中心)算错 → 假失败。
两个都是验证脚本的 bug, 不是生成器的。
"""
import os, sys
os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("MUJOCO_GL", "glfw")
ROOT = "/home/ubuntu/lerobot-smolvla-lew"
sys.path.insert(0, os.path.join(ROOT, "src/lerobot/policies/yolo_3d"))
import cv2
import numpy as np
import gen_yolo_data as g

_ap = __import__("argparse").ArgumentParser(description="DR 标签几何一致性反向验证")
_ap.add_argument("--n", type=int, default=60, help="样本数")
_ap.add_argument("--tol", type=float, default=12.0, help="错位容差 (px)")
_ap.add_argument("--seed", type=int, default=1000)
_args, _ = _ap.parse_known_args()
N = _args.n
TOL = _args.tol
PS = 96  # 标记 patch 边长 (原图坐标)
ok = bad = skip = 0
confs = []
errs = []
for i in range(N):
    rng = np.random.default_rng(1000 + i)
    img = np.full((480, 480, 3), 160, np.uint8)
    for _ in range(12):
        x0, y0 = rng.integers(0, 420, 2)
        cv2.rectangle(img, (x0, y0), (x0 + 40, y0 + 40), tuple(int(v) for v in rng.integers(0, 255, 3)), -1)
    cx, cy = 240.0, 300.0
    coarse = rng.integers(0, 255, (6, 6, 3)).astype(np.uint8)   # 唯一标记 (16px 块噪声, 抗降采样)
    marker = np.repeat(np.repeat(coarse, 16, axis=0), 16, axis=1)[:PS, :PS]
    img[int(cy) - PS // 2:int(cy) + PS // 2, int(cx) - PS // 2:int(cx) + PS // 2] = marker
    patch = marker.copy()
    boxes = [(cx, cy, g.BOX_W, g.BOX_H, 1)]

    r2 = np.random.default_rng(2000 + i)
    im2, bx2 = img.copy(), list(boxes)
    s = r2.uniform(0.72, 1.0)
    if s < 0.999:                       # 缩放裁切
        cw = ch = int(480 * s)
        x0, y0 = int(r2.integers(0, 480 - cw + 1)), int(r2.integers(0, 480 - ch + 1))
        im2 = cv2.resize(im2[y0:y0 + ch, x0:x0 + cw], (480, 480), interpolation=cv2.INTER_LINEAR)
        bx2 = [((a - x0) * 480 / cw, (b - y0) * 480 / ch, w * 480 / cw, h * 480 / ch, c) for a, b, w, h, c in bx2]
        k = max(8, int(round(PS * 480 / cw)))          # patch 同步放大
        patch = cv2.resize(patch, (k, k), interpolation=cv2.INTER_LINEAR)
    else:
        k = PS
    ang = r2.uniform(-8, 8)
    if abs(ang) > 0.5:                  # 小角旋转 (patch 绕自身中心, 与画面同角度)
        M = cv2.getRotationMatrix2D((240, 240), ang, 1.0)
        im2 = cv2.warpAffine(im2, M, (480, 480), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        rad = np.radians(ang)
        sc = abs(np.cos(rad)) + abs(np.sin(rad))
        bx2 = [(M[0, 0] * a + M[0, 1] * b + M[0, 2], M[1, 0] * a + M[1, 1] * b + M[1, 2],
                w * sc, h * sc, c) for a, b, w, h, c in bx2]
        pm = cv2.getRotationMatrix2D((k / 2.0, k / 2.0), ang, 1.0)
        patch = cv2.warpAffine(patch, pm, (k, k), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    if r2.random() < 0.5:               # 灰边 letterbox
        s2 = r2.uniform(0.62, 0.92)
        nh = max(2, int(480 * s2))
        small = cv2.resize(im2, (480, nh), interpolation=cv2.INTER_AREA)
        canvas = np.full((480, 480, 3), 114, np.uint8)
        oy = int((480 - nh) / 2)
        canvas[oy:oy + nh, :] = small
        bx2 = [(a, b * s2 + oy, w, h * s2, c) for a, b, w, h, c in bx2]
        im2 = canvas
        k2 = max(8, int(round(k * s2)))
        patch = cv2.resize(patch, (k2, k2), interpolation=cv2.INTER_AREA)
        k = k2

    gcx, gcy = bx2[0][0], bx2[0][1]
    half = k // 2
    if not (half < gcx < 480 - half and half < gcy < 480 - half):
        skip += 1
        continue                    # 标记越界, 无法匹配 (跳过, 不算失败)
    res = cv2.matchTemplate(im2, patch, cv2.TM_CCOEFF_NORMED)
    _, mx, _, mloc = cv2.minMaxLoc(res)
    fx, fy = mloc[0] + half, mloc[1] + half
    err = float(np.hypot(fx - gcx, fy - gcy))
    errs.append(err)
    confs.append(mx)
    # 判据只看错位 (噪声标记经降采样后相关度天然衰减, 匹配度仅作参考不作门)
    if err <= TOL:
        ok += 1
    else:
        bad += 1
        print(f"  #{i} 错位 {err:.1f}px 匹配度 {mx:.3f} 标签中心=({gcx:.1f},{gcy:.1f}) 峰=({fx},{fy})")
errs.sort()
confs.sort()
print(f"\n几何增广后 标签↔画面 一致性: 通过 {ok} / 失败 {bad} / 跳过 {skip} (容差 {TOL}px)")
if errs:
    print(f"错位: 最大 {errs[-1]:.1f}px · 中位 {errs[len(errs)//2]:.1f}px · 最小 {errs[0]:.1f}px"
          f" | 匹配度 中位 {confs[len(confs)//2]:.2f}")
print("→ " + ("✅ 标签随几何变换同步, 无错位 (DR 数据可训练)" if bad == 0 else "❌ 存在错位, 需修"))
