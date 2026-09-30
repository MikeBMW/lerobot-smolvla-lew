#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ros_camera_info_probe.py — 只读探针: D405 内参 (camera_info) + 深度可用性 [容器内跑, 零发布]

用途 (2026-09-18 晚): 「2D 检测框 → 3D 边界框」最省事的路是**内参 K + 深度**, 而不是纯几何自监督。
本探针只订阅 (不发布任何话题), 回答三件事:
  ① /realsense/color/camera_info 有没有真值内参 (fx,fy,cx,cy + 畸变模型)
  ② /realsense/depth/image_rect_raw 有没有有效深度 (encoding/量程/无效值比例)
  ③ 光模块检测框中心那个像素的深度是多少 (≥1 有效值 → 反投影立刻可用)

用法 (在 ss-remote-tap 容器内):
  sudo docker exec ss-remote-tap bash -lc 'source /opt/ros/humble/setup.bash && \
      python3 /repo/tools/ros_camera_info_probe.py --box 250,8,304,169'
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
from sensor_msgs.msg import CameraInfo, Image
from std_msgs.msg import String


def _q(depth=5):
    return QoSProfile(depth=depth, reliability=ReliabilityPolicy.BEST_EFFORT,
                      history=HistoryPolicy.KEEP_LAST)


class Probe(Node):
    def __init__(self):
        super().__init__("zmax_caminfo_probe", enable_rosout=False)
        self.info = None
        self.depth = None
        self.depth_m = None
        self.create_subscription(CameraInfo, "/realsense/color/camera_info", self._on_info, _q())
        for t in ("/realsense/depth/image_rect_raw", "/realsense/aligned_depth_to_color/image_raw"):
            self.create_subscription(Image, t, self._on_depth, _q(), callback_group=None)
        self.depth_topic_hits = {}

    def _on_info(self, m: CameraInfo):
        self.info = {"w": m.width, "h": m.height, "K": list(m.k), "D": list(m.d),
                     "distortion_model": m.distortion_model,
                     "P": list(m.p), "frame_id": m.header.frame_id,
                     "R": list(m.r)}

    def _on_depth(self, m: Image):
        t = m.header.frame_id
        arr = np.frombuffer(bytes(m.data), dtype=np.uint16 if "16" in m.encoding else np.float32)
        if m.encoding == "32FC1":
            d = arr.reshape(m.height, m.width).astype(np.float32)
        else:
            d = arr.reshape(m.height, m.width).astype(np.float32) * 0.001      # mm → m
        self.depth = {"encoding": m.encoding, "w": m.width, "h": m.height, "step": m.step,
                      "frame_id": t}
        self.depth_m = d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--box", default="", help="x1,y1,x2,y2 (光模块 2D 框) 看框内深度")
    ap.add_argument("--timeout", type=float, default=20.0)
    args = ap.parse_args()
    rclpy.init()
    n = Probe()
    t0 = time.time()
    while time.time() - t0 < args.timeout and (n.info is None or n.depth_m is None):
        rclpy.spin_once(n, timeout_sec=0.05)
    out = {"camera_info": n.info, "depth": n.depth}
    if n.info:
        K = n.info["K"]
        out["fx_fy_cx_cy"] = [round(K[0], 3), round(K[4], 3), round(K[2], 3), round(K[5], 3)]
        out["fov_deg"] = [round(2 * np.degrees(np.arctan(0.5 * n.info["w"] / K[0])), 2),
                          round(2 * np.degrees(np.arctan(0.5 * n.info["h"] / K[4])), 2)]
    if n.depth_m is not None:
        d = n.depth_m
        valid = np.isfinite(d) & (d > 0.05) & (d < 3.0)
        out["depth_valid_frac"] = round(float(valid.mean()), 4)
        out["depth_range_m"] = [round(float(np.percentile(d[valid], 1)), 4),
                                round(float(np.percentile(d[valid], 99)), 4)] if valid.any() else None
        if args.box:
            x1, y1, x2, y2 = [float(v) for v in args.box.split(",")]
            sub = d[int(y1):int(y2) + 1, int(x1):int(x2) + 1]
            sv = sub[np.isfinite(sub) & (sub > 0.05) & (sub < 3.0)]
            cx, cy = int((x1 + x2) / 2), int((y1 + y2) / 2)
            out["box_depth_m"] = {"median": (round(float(np.median(sv)), 4) if sv.size else None),
                                  "p10": (round(float(np.percentile(sv, 10)), 4) if sv.size else None),
                                  "p90": (round(float(np.percentile(sv, 90)), 4) if sv.size else None),
                                  "n_valid": int(sv.size), "n_total": int(sub.size),
                                  "center_px_depth_m": round(float(d[cy, cx]), 4)}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    rclpy.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
