#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ros_depth_hist_probe.py — 只读: 深度图直方图 + 与彩色图的一致性体检 [容器内跑]

回答: 这条 /realsense/depth/image_rect_raw 到底看的是不是同一片场景?
  · 直方图 (0.05~3.0m 分箱) → 有没有"近处的台面" (0.2~0.6m)
  · 有效像素比例 / 无效值 (0)
  · 彩色框中心像素 → (按 D405 出厂 depth→color 外参映射后的深度像素) 的深度

用法: sudo docker exec ss-remote-tap bash -lc 'source /opt/ros/humble/setup.bash && \
        python3 /repo/tools/ros_depth_hist_probe.py --box 250,8,304,168'
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import Image

TOPICS = ("/realsense/depth/image_rect_raw", "/realsense/aligned_depth_to_color/image_raw")


def _q(depth=5):
    return QoSProfile(depth=depth, reliability=ReliabilityPolicy.BEST_EFFORT,
                      history=HistoryPolicy.KEEP_LAST)


class DepthProbe(Node):
    def __init__(self):
        super().__init__("zmax_depth_hist", enable_rosout=False)
        self.got = {}
        for t in TOPICS:
            self.create_subscription(Image, t, lambda m, t=t: self._on(m, t), _q())

    def _on(self, m: Image, t: str):
        arr = np.frombuffer(bytes(m.data), dtype=(np.uint16 if m.encoding.startswith("16") else np.float32))
        d = arr.reshape(m.height, -1)[:, :m.width].astype(np.float32)
        if m.encoding.startswith("16"):
            d *= 0.001
        self.got[t] = {"d": d, "encoding": m.encoding, "w": m.width, "h": m.height,
                       "frame_id": m.header.frame_id, "step": m.step}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--box", default="")
    ap.add_argument("--timeout", type=float, default=15.0)
    a = ap.parse_args()
    rclpy.init()
    n = DepthProbe()
    t0 = time.time()
    while time.time() - t0 < a.timeout and len(n.got) < len(TOPICS):
        rclpy.spin_once(n, timeout_sec=0.05)
    out = {"topics_with_frames": list(n.got)}
    for t, info in n.got.items():
        d = info["d"]
        v = d[np.isfinite(d) & (d > 0.05) & (d < 5.0)]
        hist, edges = np.histogram(v, bins=[0.05, 0.15, 0.25, 0.4, 0.6, 0.9, 1.3, 2.0, 3.0, 5.0])
        rec = {"encoding": info["encoding"], "wh": [info["w"], info["h"]], "frame_id": info["frame_id"],
               "valid_frac": round(float((d > 0.05).mean()), 4),
               "zero_frac": round(float((d == 0).mean()), 4),
               "median_m": (round(float(np.median(v)), 3) if v.size else None),
               "hist_m": {f"{edges[i]:.2f}-{edges[i+1]:.2f}": int(hist[i]) for i in range(len(hist))}}
        if a.box:
            x1, y1, x2, y2 = [int(float(s)) for s in a.box.split(",")]
            sub = d[y1:y2 + 1, x1:x2 + 1]
            sv = sub[sub > 0.05]
            rec["box_raw_pixels_m"] = {"median": (round(float(np.median(sv)), 3) if sv.size else None),
                                       "n": int(sv.size), "n_total": int(sub.size)}
        out[t] = rec
    print(json.dumps(out, ensure_ascii=False, indent=1))
    rclpy.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
