#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_focus_metrics.py — 指标行为探针 (2026-09-24): 选 σ 反演形式 + 运动判据阈值, 不靠猜"""
import os
import sys

import cv2
import numpy as np

ROOT = "/home/ubuntu/lerobot-smolvla-lew"
sys.path.insert(0, os.path.join(ROOT, "src", "lerobot", "policies", "left_right", "state_space"))


def load(p):
    cap = cv2.VideoCapture(p); ok, fr = cap.read(); cap.release()
    return cv2.cvtColor(fr, cv2.COLOR_BGR2RGB)


def defocus(img, s):
    if s < 0.1:
        return img.copy()
    k = int(2 * int(np.ceil(3 * s)) + 1)
    return cv2.GaussianBlur(img, (k, k), float(s))


def motion(img, L, ang):
    k = np.zeros((L, L), np.float32); k[L // 2, :] = 1.0
    M = cv2.getRotationMatrix2D((L / 2 - .5, L / 2 - .5), ang, 1.0)
    k = cv2.warpAffine(k, M, (L, L)); k /= (k.sum() + 1e-9)
    return cv2.filter2D(img, -1, k)


def gray(img, frac=0.6):
    H, W = img.shape[:2]
    h, w = int(H * frac), int(W * frac)
    g = cv2.cvtColor(img[(H - h) // 2:(H + h) // 2, (W - w) // 2:(W + w) // 2], cv2.COLOR_RGB2GRAY)
    return g


def lapv(g):
    return float(cv2.Laplacian(g, cv2.CV_64F).var())


def hf_ratio(g, lo_frac=0.25):
    n = min(min(g.shape), 256)
    gs = cv2.resize(g.astype(np.float32), (n, n), interpolation=cv2.INTER_AREA)
    win = np.outer(np.hanning(n), np.hanning(n))
    F = np.abs(np.fft.fftshift(np.fft.fft2((gs - gs.mean()) * win)))
    yy, xx = np.mgrid[0:n, 0:n]; r = np.hypot(yy - n / 2., xx - n / 2.)
    hi = (r > lo_frac * r.max()) & (r < r.max()); lo = (~hi) & (r > 0)
    return float((F[hi] ** 2).sum() / ((F[lo] ** 2).sum() + 1e-9))


def aniso_band(g, frac):
    """角度分布方向性 (在指定高频带内)"""
    n = min(min(g.shape), 192)
    gs = cv2.resize(g.astype(np.float32), (n, n), interpolation=cv2.INTER_AREA)
    win = np.outer(np.hanning(n), np.hanning(n))
    F = np.abs(np.fft.fftshift(np.fft.fft2((gs - gs.mean()) * win)))
    yy, xx = np.mgrid[0:n, 0:n]; r = np.hypot(yy - n / 2., xx - n / 2.)
    mask = r > frac * (n / 2.)
    ang = np.degrees(np.arctan2(yy - n / 2., xx - n / 2.)) % 180.
    prof = [float(F[mask & (np.abs(((ang - a + 90) % 180) - 90) < 2.)].mean()) for a in range(0, 180, 2)]
    p = np.asarray(prof, float)
    return float((np.percentile(p, 90) - np.percentile(p, 10)) / (p.mean() + 1e-9))


sharp = load(os.path.join(ROOT, "data/real_yolo_perception_104.mp4"))
g0 = gray(sharp)
lap0, hf0 = lapv(g0), hf_ratio(g0)
print(f"参考帧: lap={lap0:.1f} hf={hf0:.5f}")

print("\n=== ① σ 反演: 两种形式在 σ_true 0..6px 的表现 ===")
print(f"{'σ_true':>7} {'r_lap':>9} {'σ_lap估计':>10} {'r_hf':>9} {'σ_hf估计(c=0.4)':>15}")
rows = []
for s in [0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0]:
    g = gray(defocus(sharp, s))
    rl, rh = lapv(g) / lap0, hf_ratio(g) / hf0
    s_lap = 0.8 * np.sqrt(max(1.0 / np.sqrt(max(rl, 1e-9)) - 1.0, 0.0))     # 拉普拉斯比反演 (σ0=0.8px)
    s_hf = 0.4 * np.sqrt(max(1.0 / max(rh, 1e-9) - 1.0, 0.0))
    rows.append((s, rl, s_lap, rh, s_hf))
    print(f"{s:7.2f} {rl:9.4f} {s_lap:10.3f} {rh:9.4f} {s_hf:15.3f}")

print("\n=== ② 运动判据: 方向性 vs 运动核长 (不同频带) ===")
print(f"{'核':>10} " + " ".join(f"{lbl:>12}" for lbl in ["带>0.25rmax", "带>0.45rmax", "带>0.60rmax"]))
base = [aniso_band(g0, f) for f in (0.25, 0.45, 0.60)]
print(f"{'清晰基线':>10} " + " ".join(f"{v:12.3f}" for v in base))
for L in (15, 21, 35, 51):
    a = [aniso_band(gray(motion(sharp, L, 30.0)), f) for f in (0.25, 0.45, 0.60)]
    r = [a[i] / (base[i] + 1e-9) for i in range(3)]
    print(f"{f'{L}px@30°':>10} " + " ".join(f"{v:12.3f}" for v in a) + "   ×基线: " + " ".join(f"{x:.2f}" for x in r))
print("\n=== ③ 不同拖影方向 (核 35px) 在 0.45 带 ===")
for ang in (0, 30, 60, 90, 135):
    a = aniso_band(gray(motion(sharp, 35, ang)), 0.45)
    print(f"  {ang:3d}°: aniso={a:.3f} ×基线={a / (base[1] + 1e-9):.2f}")
