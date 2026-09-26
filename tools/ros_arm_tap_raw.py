#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Z-MAX 手臂相机 · 全速原始帧抓取（在 ROS 容器内运行）
──────────────────────────────────────────────────────────────
为什么需要它:
  ss_remote_tap.py 设计为「raw 订阅, 1Hz 解码」省 CPU → 手臂流被压到 ~0.5-1 fps。
  本脚本按相机原生帧率（实测 1.92Hz）订阅，只做「拷贝字节 + 落共享内存」，
  不做 JPEG 编码（容器内无 cv2）→ 编码交给 4060 本机的 cv2。

产出（tmpfs，不磨损磁盘）:
  /dev/shm/zmax_arm.raw   原始像素
  /dev/shm/zmax_arm.meta  JSON: {seq,w,h,enc,ts,bytes}

用法（容器内）:
  python3 ros_arm_tap_raw.py --topic /realsense/color/image_raw
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import time

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import Image

RAW = "/dev/shm/zmax_arm.raw"
META = "/dev/shm/zmax_arm.meta"
TMP = "/dev/shm/.zmax_arm.raw.tmp"


class RawTap(Node):
    def __init__(self, topic: str):
        super().__init__("zmax_arm_raw_tap")
        self.seq = 0
        self.n = 0
        self.t0 = time.time()
        q = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT,
                       history=HistoryPolicy.KEEP_LAST)
        # 注意: 不能用 raw=True —— 那样回调拿到的是 CDR 序列化字节，
        # 没有 .encoding/.height 等字段（实测报 'bytes' object has no attribute 'encoding'）。
        # 本脚本需要真实像素，让 rclpy 正常反序列化。
        self.create_subscription(Image, topic, self.cb, q)
        self.create_timer(10.0, self.report)
        self.get_logger().info(f"订阅 {topic} → {RAW}")

    def report(self):
        dt = time.time() - self.t0
        if dt > 0:
            self.get_logger().info(f"已收 {self.n} 帧 · {self.n/dt:.2f} fps")

    def cb(self, msg):
        try:
            enc = (msg.encoding or "").lower()
            h, w = int(msg.height), int(msg.width)
            step = int(msg.step)
            data = bytes(msg.data)
            # 只处理 8UC3 / 8UC1 常见编码
            if enc in ("rgb8", "bgr8"):
                w3 = w * 3
                if step != w3:
                    rows = [data[i * step:i * step + w3] for i in range(h)]
                    data = b"".join(rows)
                arr = np.frombuffer(data, np.uint8).reshape(h, w, 3)
                if enc == "rgb8":      # 本机 cv2 用 BGR 口径
                    arr = arr[:, :, ::-1]
                out = np.ascontiguousarray(arr)
                ncomp = 3
            elif enc in ("mono8", "8UC1"):
                if step != w:
                    rows = [data[i * step:i * step + w] for i in range(h)]
                    data = b"".join(rows)
                out = np.frombuffer(data, np.uint8).reshape(h, w)[:, :, None]
                out = np.ascontiguousarray(out)
                ncomp = 1
            else:
                if self.n == 0:
                    self.get_logger().warn(f"不支持的编码 {enc}（只记元数据）")
                return
            payload = out.tobytes()
            # 原子写：先写临时文件再 rename（避免读到写一半的帧）
            with open(TMP, "wb") as f:
                f.write(payload)
            os.replace(TMP, RAW)
            self.seq += 1
            self.n += 1
            meta = {"seq": self.seq, "w": w, "h": h, "nmask": ncomp,
                    "enc": enc, "ts": time.time(), "bytes": len(payload)}
            with open(META + ".tmp", "w") as f:
                json.dump(meta, f)
            os.replace(META + ".tmp", META)
        except Exception as e:  # 绝不因单帧异常退出
            if self.n < 3:
                self.get_logger().error(f"cb 异常: {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", default="/realsense/color/image_raw")
    ap.add_argument("--domain", type=int, default=0)
    args, _ = ap.parse_known_args()
    os.environ.setdefault("ROS_DOMAIN_ID", str(args.domain))
    rclpy.init()
    node = RawTap(args.topic)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        try:
            rclpy.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()
