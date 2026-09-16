#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真机图像流可用性扫描 (只读) — 找出**当前真有 publisher** 的图像话题。

为什么需要: /realsense/* 话题在 ROS 图里存在, 但 Publisher count = 0 (相机驱动没在跑),
只有 vision_tag 在**订阅**它们 → 订阅收不到任何帧。所以适配真机第一步必须先搞清
"现在到底哪路像素是活的", 不能假设。

用法 (容器内): python3 tools/ros_scan_image_topics.py
"""
import sys
import time

import rclpy
from rclpy.node import Node
from rcl_interfaces.msg import ParameterEvent  # noqa: F401
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

TYPES_OF_INTEREST = {"sensor_msgs/msg/Image", "sensor_msgs/msg/CompressedImage",
                     "sensor_msgs/msg/CameraInfo", "sensor_msgs/msg/PointCloud2"}
_REL = QoSProfile(depth=1, history=HistoryPolicy.KEEP_LAST, reliability=ReliabilityPolicy.RELIABLE)
_STATIC = QoSProfile(depth=1, history=HistoryPolicy.KEEP_LAST,
                     reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL)


class Scanner(Node):
    def __init__(self):
        super().__init__("zmax_image_topic_scanner")
        self.topics = {}

    def on_change(self, info_list):
        for info in info_list:
            self.topics[(info.name, info.type)] = None


def main():
    rclpy.init()
    n = Scanner()
    n.create_subscription(object, "/parameter_events", lambda *_: None, _REL) if False else None
    # 用 graph API 拿全量 (topic, types) —— 兼容不同 rclpy 版本
    from rclpy.topic_endpoint_info import TopicEndpointInfo  # noqa: F401
    try:
        names_types = n.get_topic_names_and_types()
    except Exception as e:                                                # noqa: BLE001
        print(f"get_topic_names_and_types 失败: {e}", flush=True)
        return 1
    print(f"{'话题':52s} {'类型':38s} pub  sub  实时帧")
    print("-" * 108)
    rows = []
    for name, types in sorted(names_types):
        if not any(t in TYPES_OF_INTEREST for t in types):
            continue
        t = types[0]
        try:
            pubs = n.count_publishers(name)
            subs = n.count_subscribers(name)
        except Exception:                                                 # noqa: BLE001
            pubs = subs = -1
        live = ""
        if pubs > 0 and t in ("sensor_msgs/msg/Image", "sensor_msgs/msg/CompressedImage"):
            got = {"n": 0}

            def _cb(_m, _g=got):
                _g["n"] += 1

            sub = n.create_subscription(object, name, _cb, _REL)
            t0 = time.time()
            while time.time() - t0 < 3.0 and got["n"] < 3:
                rclpy.spin_once(n, timeout_sec=0.2)
            n.destroy_subscription(sub)
            live = f"{got['n']} 帧/3s" if got["n"] else "⚠️ 收不到(可能 QoS 不匹配)"
        rows.append((name, t, pubs, subs, live))
        print(f"{name:52s} {t:38s} {pubs:3d} {subs:4d}  {live}")
    print("-" * 108)
    print("说明: pub=0 → 图里有订阅者但**没有发布者** (驱动没跑) ⇒ 拿不到帧。")
    live_rows = [r for r in rows if r[2] > 0]
    print(f"结论: 图像话题 {len(rows)} 个, 其中**有发布者**的 {len(live_rows)} 个: "
          + (", ".join(f"{r[0]}({r[4] or '无帧'})" for r in live_rows) if live_rows else "无"))
    n.destroy_node()
    rclpy.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
