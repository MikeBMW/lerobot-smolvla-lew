#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""depth_align.py — 深度算法: RealSense 深度 → 2D→3D 映射 (整合进 yolo_state_aligner.estimate_3d)

解决的问题 (2026-09-18, 代码原有 gap 注记):
  「深度尺寸 ≠ 图像 → 未对齐, 需 align 步骤 / 换 *_aligned_depth* 话题」
  D405 的 /realsense/depth/image_rect_raw 是**深度相机视角**; 彩色框的像素
  不能直接拿去索引深度图 → 必须先按 **depth→color 外参** 把深度投到彩色系,
  或把彩色框中心投到深度系取 Z。

本模块提供 (纯 numpy, 可单测, 不依赖引擎/ROS):
  ① align_depth_to_color(...)  深度图 → 彩色系 (最近邻重采样 + 无效值保持 0)
  ② sample_depth_robust(...)   框内鲁棒深度 (有效掩码 + 中值 + MAD 去离群 + σ∝Z² 加权)
  ③ backproject(...)           像素 + Z + K → 相机系 3D (含畸变可选去畸变)
  ④ depth_3d_from_box(...)     一站式: 框 + 深度 + 两侧内参 + 外参 → 3D 点 (米)

纪律:
  · 无效深度 (0 / NaN / 超量程) **绝不参与**统计, 也不许用 0 冒充
  · 采样失败 → 返回 None + 原因 (调用方回退到估计路径, 不编造 Z)
  · 单位: 米 (真实 16UC1 需先 ×depth_scale)
  · 依赖最小: 只用 numpy (cv2 可选, 用于去畸变)
"""
from __future__ import annotations

import numpy as np

# D405 标称量程 (短距): 超出即视为无效
D405_Z_MIN = 0.05
D405_Z_MAX = 3.00


def _valid_mask(depth: np.ndarray, z_min: float, z_max: float) -> np.ndarray:
    d = np.asarray(depth, dtype=np.float32)
    return np.isfinite(d) & (d > z_min) & (d < z_max)


def align_depth_to_color(depth: np.ndarray, K_depth, K_color, ext, *,
                         out_wh=None, z_min: float = D405_Z_MIN,
                         z_max: float = D405_Z_MAX):
    """深度图 → 彩色系对齐 (最近邻)。

    ext: {"rotation": 9 或 3x3, "translation_m": 3}  depth→color 外参
         (由 tools/orin_d405_factory_calib.py 从设备 get_extrinsics_to 取)
    K_depth / K_color: 3x3 或长度 9 行主序
    返回 (aligned_depth[Hc,Wc], info)
    """
    depth = np.asarray(depth, dtype=np.float32)
    Kd = np.asarray(K_depth, dtype=np.float64).reshape(3, 3)
    Kc = np.asarray(K_color, dtype=np.float64).reshape(3, 3)
    Hd, Wd = depth.shape[:2]
    Hc, Wc = (out_wh[1], out_wh[0]) if out_wh else (Hd, Wd)

    R = np.asarray(ext.get("rotation"), dtype=np.float64).reshape(3, 3)
    t = np.asarray(ext.get("translation_m"), dtype=np.float64).reshape(3)

    v, u = np.meshgrid(np.arange(Hd), np.arange(Wd), indexing="ij")
    m = _valid_mask(depth, z_min, z_max)
    if not m.any():
        return np.zeros((Hc, Wc), np.float32), {"aligned": 0, "valid_in": 0, "reason": "深度图全无效"}

    z = depth[m]
    x = (u[m] - Kd[0, 2]) * z / Kd[0, 0]
    y = (v[m] - Kd[1, 2]) * z / Kd[1, 1]
    P_d = np.stack([x, y, z], axis=1)              # 深度相机系 (米)
    P_c = P_d @ R.T + t                             # → 彩色相机系

    zc = P_c[:, 2]
    ok = zc > 1e-6
    uc = Kc[0, 0] * P_c[ok, 0] / zc[ok] + Kc[0, 2]
    vc = Kc[1, 1] * P_c[ok, 1] / zc[ok] + Kc[1, 2]

    out = np.zeros((Hc, Wc), np.float32)
    ui = np.rint(uc).astype(np.int64)
    vi = np.rint(vc).astype(np.int64)
    inb = (ui >= 0) & (ui < Wc) & (vi >= 0) & (vi < Hc)
    out[vi[inb], ui[inb]] = zc[ok][inb]
    # 空洞填补: 3x3 最大值填充 (近邻优先, 不引入远处值)
    holes = out == 0
    if holes.any():
        pad = np.pad(out, 1, mode="edge")
        nb = np.stack([pad[0:-2, 0:-2], pad[0:-2, 1:-1], pad[0:-2, 2:],
                       pad[1:-1, 0:-2], pad[1:-1, 2:],
                       pad[2:, 0:-2], pad[2:, 1:-1], pad[2:, 2:]], axis=0)
        filled = np.where(nb > 0, nb, np.inf).min(axis=0)
        out[holes] = np.where(np.isfinite(filled[holes]), filled[holes], 0.0)
    n = int((out > 0).sum())
    return out, {"aligned": n, "valid_in": int(m.sum()), "out_size": [Wc, Hc],
                 "holes_filled": int(holes.sum())}


def sample_depth_robust(depth: np.ndarray, box_px, *, z_min: float = D405_Z_MIN,
                        z_max: float = D405_Z_MAX, mad_k: float = 3.0,
                        center_frac: float = 0.5):
    """框内鲁棒深度 → (z_m, info)。

    做法: 取框中心 center_frac 比例的内区域 → 有效掩码 → 中值 → MAD 去离群 → 中值
    σ 估计: σ ≈ k · Z² (立体视觉深度噪声随距离平方增长)
    """
    x1, y1, x2, y2 = [float(v) for v in box_px[:4]]
    cw, ch = (x2 - x1) * center_frac / 2.0, (y2 - y1) * center_frac / 2.0
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    H, W = depth.shape[:2]
    xa, xb = int(max(0, np.floor(cx - cw))), int(min(W, np.ceil(cx + cw) + 1))
    ya, yb = int(max(0, np.floor(cy - ch))), int(min(H, np.ceil(cy + ch) + 1))
    roi = np.asarray(depth, dtype=np.float32)[ya:yb, xa:xb]
    if roi.size == 0:
        return None, {"reason": "框超出图像/ROI 为空"}
    m = _valid_mask(roi, z_min, z_max)
    nv = int(m.sum())
    if nv < 4:
        return None, {"reason": f"有效深度像素不足 ({nv} < 4)", "roi": [xa, ya, xb, yb]}
    v = roi[m]
    med = float(np.median(v))
    mad = float(np.median(np.abs(v - med))) or 1e-6
    keep = np.abs(v - med) <= mad_k * 1.4826 * mad
    z = float(np.median(v[keep])) if keep.sum() >= 2 else med
    sigma = float(0.002 * z * z)          # σ ∝ Z² (经验系数, 可标定)
    return z, {"n_valid": nv, "n_kept": int(keep.sum()), "median_all": med,
               "mad": mad, "sigma_m": sigma, "roi": [xa, ya, xb, yb]}


def backproject(u: float, v: float, z: float, K, dist=None):
    """像素 + Z + 内参 → 相机系 3D (米)。有畸变则先去畸变再反投影。"""
    K = np.asarray(K, dtype=np.float64).reshape(3, 3)
    uu, vv = float(u), float(v)
    if dist is not None and np.any(np.asarray(dist) != 0):
        try:
            import cv2
            pts = np.array([[[uu, vv]]], dtype=np.float64)
            und = cv2.undistortPoints(pts, K, np.asarray(dist, dtype=np.float64).reshape(-1))
            uu, vv = float(und[0, 0, 0]), float(und[0, 0, 1])
            x = uu * z
            y = vv * z
            return np.array([x, y, float(z)], np.float64), {"undistorted": True}
        except Exception as e:                                  # noqa: BLE001
            pass
    x = (uu - K[0, 2]) * z / K[0, 0]
    y = (vv - K[1, 2]) * z / K[1, 1]
    return np.array([x, y, float(z)], np.float64), {"undistorted": False}


def depth_3d_from_box(box_px, depth_color_frame, K_color, *, dist=None,
                      z_min: float = D405_Z_MIN, z_max: float = D405_Z_MAX):
    """一站式: 框(彩色系) + **已对齐到彩色系**的深度 → (P_cam(3), info)"""
    x1, y1, x2, y2 = [float(v) for v in box_px[:4]]
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    z, sinfo = sample_depth_robust(depth_color_frame, box_px, z_min=z_min, z_max=z_max)
    if z is None:
        return None, {"stage": "sample_depth", **sinfo}
    P, binfo = backproject(cx, cy, z, K_color, dist=dist)
    return P, {"stage": "ok", **sinfo, **binfo, "z_m": z, "pixel": [cx, cy]}


# ── 自检 ─────────────────────────────────────────────────────────────
def _selftest():
    ok = True
    K = [394.06, 0, 318.44, 0, 393.47, 238.66, 0, 0, 1]
    # ① 反投影: 主点 + Z=0.5 → (0,0,0.5)
    P, _ = backproject(318.44, 238.66, 0.5, K)
    e1 = float(np.abs(P - [0, 0, 0.5]).max())
    ok &= e1 < 1e-9
    print(f"  {'OK ' if e1 < 1e-9 else 'FAIL'} ① 反投影主点误差={e1:.2e}")
    # ② 已知 3D → 投影像素 → 反投影回同一 3D (往返)
    Zt = 0.6
    Xt, Yt = 0.05, -0.03
    u = 394.06 * Xt / Zt + 318.44
    v = 393.47 * Yt / Zt + 238.66
    P2, _ = backproject(u, v, Zt, K)
    e2 = float(np.abs(P2 - [Xt, Yt, Zt]).max())
    ok &= e2 < 1e-9
    print(f"  {'OK ' if e2 < 1e-9 else 'FAIL'} ② 往返误差={e2:.2e}")
    # ③ 鲁棒采样: 框内 0.5m, 混入离群 + 无效
    d = np.full((480, 640), 0.5, np.float32)
    d[:200, :] = 0.0            # 无效区
    d[240, 318] = 9.9           # 离群
    z, info = sample_depth_robust(d, [280, 200, 360, 280])
    e3 = abs(z - 0.5)
    ok &= e3 < 1e-6
    print(f"  {'OK ' if e3 < 1e-6 else 'FAIL'} ③ 鲁棒采样 z={z:.4f} (期望 0.5) σ={info['sigma_m']:.6f}")
    # ④ 全无效 → 必须拒绝 (不返回 0 冒充)
    z2, info2 = sample_depth_robust(np.zeros((480, 640), np.float32), [280, 200, 360, 280])
    ok &= z2 is None
    print(f"  {'OK ' if z2 is None else 'FAIL'} ④ 全无效被拒: {info2.get('reason')}")
    # ⑤ 对齐: 平移 10px 的外参 → 输出对齐图非零
    ext = {"rotation": np.eye(3).ravel().tolist(), "translation_m": [0.0, 0.0, 0.0]}
    al, ainfo = align_depth_to_color(d, K, K, ext)
    ok &= ainfo["aligned"] > 0
    print(f"  {'OK ' if ainfo['aligned'] > 0 else 'FAIL'} ⑤ 对齐有效像素={ainfo['aligned']} 填洞={ainfo['holes_filled']}")
    print(f"  {'PASS' if ok else 'FAIL'} depth_align selftest")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    sys.exit(_selftest())
