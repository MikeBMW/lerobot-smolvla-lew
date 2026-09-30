#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""depth_colorize.py — 深度浮点数组 → 伪彩 JPEG + 真值带 (口径唯一真源)

为什么要单独一个文件: 同一份彩色化口径**两边都要用** ——
  · 容器侧 `ros_depth_stream.py`(可能没装 cv2, 有就用它上色)
  · 宿主侧 `cam_live_stream.py` 的 depth 源(有 cv2, 容器没上色时由它补)
分头各写一份必然出现"两边颜色/量程/文字不一致"的漂移, 所以抽到这里, 两边都 import 它。
**本文件不 import rclpy**(宿主没有 ROS) —— 这是它能被两边共用的前提。
"""
from __future__ import annotations

import time

import numpy as np

try:                       # 容器(ros:humble-ros-base)通常没有 cv2 → 由宿主上色, 见模块头注释
    import cv2
except Exception:                                                             # noqa: BLE001
    cv2 = None

HAS_CV2 = cv2 is not None

RANGE_M = (0.15, 1.20)    # 彩色化量程 (工位台面 ~0.25~0.7m, 留余量)
BAND_H = 46               # 顶部真值带高度 (px)
VALID_LO, VALID_HI = 0.05, 6.0


def band_lines(meta: dict) -> list:
    """真值带文字 (无 cv2 也能拼, 便于测试)"""
    t = meta.get("t") or time.time()
    return [
        "D405 深度 %sx%s · 帧龄 %ss · 源 %sHz · 帧序 %s" % (
            meta.get("w", "?"), meta.get("h", "?"), meta.get("src_stamp_age_s", "?"),
            meta.get("fps", "?"), meta.get("frames", "?")),
        "有效 %s%% · 最近 %sm · 中位 %sm · 中心 %sm · 量程 %.2f~%.2fm · 拍照 %s" % (
            meta.get("valid_pct", "?"), meta.get("near_m"), meta.get("median_m"),
            meta.get("center_m"), RANGE_M[0], RANGE_M[1],
            time.strftime("%H:%M:%S", time.localtime(t))),
    ]


def colorize(d_m: np.ndarray, meta: dict, quality: int = 72) -> bytes:
    """float32 米数组 → 伪彩 JPEG (顶部真值带)。无效像素置黑, 不拿黑当 0 米糊弄。

    没有 cv2 时返回 b""(调用方据此回退: 容器只落原始数组, 由宿主上色)。
    """
    if cv2 is None:
        return b""
    valid = (d_m > VALID_LO) & (d_m < VALID_HI)
    dv = np.clip((d_m - RANGE_M[0]) / (RANGE_M[1] - RANGE_M[0]), 0.0, 1.0)
    img = cv2.applyColorMap((dv * 255).astype(np.uint8), cv2.COLORMAP_TURBO)
    img[~valid] = (0, 0, 0)
    h, w = img.shape[:2]
    band = np.full((BAND_H, w, 3), (24, 20, 16), np.uint8)
    for i, s in enumerate(band_lines(meta)):
        cv2.putText(band, s, (10, 18 + i * 20), cv2.FONT_HERSHEY_SIMPLEX, 0.52,
                    (160, 230, 120), 1, cv2.LINE_AA)
    ok, jpg = cv2.imencode(".jpg", np.vstack([band, img]),
                           [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    return jpg.tobytes() if ok else b""
