#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真机 RealSense 只读采样器 (2026-09-17 老倪: 「引入真机 realsense 相机, 跑通 sim to real」)

设计铁律 (与 09-16 架构红线一致):
  · **在 4060 侧 Docker (ros:humble-ros-base --network host, ROS_DOMAIN_ID=0) 里跑**,
    Orin 生产设备**零自研程序零自启** — 本节点只订阅, 不创建任何 publisher
    (self_publishers 自证: 只有 /parameter_events)。
  · 采到的真机数据落盘 → 本机用同一份 YOLO 权重/同一份几何代码做离线与在线适配。

落盘 (每帧一组, 同 stamp):
  color_<i>.npy (HxWx3 uint8) · depth_<i>.npy (HxW uint16 mm 或 float32 m)
  camera_info.json (K/D/尺寸/畸变模型) · tf_static.json (base_link→相机外参)
  tcp_pose.json (geometry_msgs/PoseStamped, frame_id=base_link, 50Hz 真值)
  meta.json (帧数/编码/尺寸/时间戳)

用法 (容器内):
  python3 tools/ros_record_realsense.py --out /out --frames 12 [--timeout 30]
"""
import argparse
import json
import os
import sys
import time

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import CameraInfo, Image
from geometry_msgs.msg import PoseStamped
from tf2_msgs.msg import TFMessage

_BE = QoSProfile(depth=10, history=HistoryPolicy.KEEP_LAST, reliability=ReliabilityPolicy.BEST_EFFORT)
_REL = QoSProfile(depth=10, history=HistoryPolicy.KEEP_LAST, reliability=ReliabilityPolicy.RELIABLE)
_STATIC = QoSProfile(depth=1, history=HistoryPolicy.KEEP_LAST,
                     reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL)


def img_to_np(msg: Image) -> np.ndarray:
    """sensor_msgs/Image → numpy (按 encoding 解释; 处理 step 行填充)"""
    it = {"rgb8": np.uint8, "bgr8": np.uint8, "mono8": np.uint8,
          "16UC1": np.uint16, "mono16": np.uint16, "32FC1": np.float32}[msg.encoding]
    ch = 3 if msg.encoding in ("rgb8", "bgr8") else 1
    raw = np.frombuffer(bytes(msg.data), dtype=it)
    stride = msg.step // raw.dtype.itemsize
    raw = raw.reshape(msg.height, stride)[:, : msg.width * ch]
    arr = raw.reshape(msg.height, msg.width, ch)
    return arr[:, :, 0] if ch == 1 else arr


class Recorder(Node):
    def __init__(self, out: str, frames: int, timeout: float):
        super().__init__("zmax_realcam_recorder")
        self.out = out
        self.want = frames
        self.deadline = time.time() + timeout
        self.color = None
        self.depth = None
        self.ci = None
        self.tcp = None
        self.tf_static = None
        self.n = 0
        self.meta = {"color_enc": None, "depth_enc": None, "size": None, "saved": []}
        self.create_subscription(Image, "/realsense/color/image_raw", self._on_color, _BE)
        self.create_subscription(Image, "/realsense/depth/image_rect_raw", self._on_depth, _REL)
        self.create_subscription(CameraInfo, "/realsense/color/camera_info", self._on_ci, _REL)
        self.create_subscription(PoseStamped, "/robot/tcp_pose", self._on_tcp, _BE)
        self.create_subscription(TFMessage, "/tf_static", self._on_tf, _STATIC)
        print(f"[realcam] 只读订阅中 (要 {frames} 帧, 超时 {timeout:.0f}s): "
              f"/realsense/color/image_raw + depth + camera_info + /robot/tcp_pose + /tf_static", flush=True)

    # ── 回调 ────────────────────────────────────────────────────────────────
    def _on_color(self, m):
        if self.color is None or self.n < self.want:
            try:
                self.color = img_to_np(m)
                self.meta["color_enc"] = m.encoding
                self.meta["size"] = [m.width, m.height]
                self.meta["frame_id"] = m.header.frame_id
            except Exception as e:                                        # noqa: BLE001
                print(f"⚠️ color 解码失败: {type(e).__name__}: {e}", flush=True)

    def _on_depth(self, m):
        if self.depth is None or self.n < self.want:
            try:
                self.depth = img_to_np(m)
                self.meta["depth_enc"] = m.encoding
            except Exception as e:                                        # noqa: BLE001
                print(f"⚠️ depth 解码失败: {type(e).__name__}: {e}", flush=True)

    def _on_ci(self, m):
        if self.ci is None:
            self.ci = {"width": m.width, "height": m.height, "K": list(m.k), "D": list(m.d),
                       "distortion_model": m.distortion_model, "frame_id": m.header.frame_id,
                       "R": list(m.r), "P": list(m.p)}

    def _on_tcp(self, m):
        self.tcp = {"frame_id": m.header.frame_id, "stamp": m.header.stamp.sec + m.header.stamp.nanosec * 1e-9,
                    "position": [m.pose.position.x, m.pose.position.y, m.pose.position.z],
                    "orientation": [m.pose.orientation.x, m.pose.orientation.y,
                                    m.pose.orientation.z, m.pose.orientation.w]}

    def _on_tf(self, m):
        self.tf_static = [{"parent": t.header.frame_id, "child": t.child_frame_id,
                           "translation": [t.transform.translation.x, t.transform.translation.y,
                                           t.transform.translation.z],
                           "rotation": [t.transform.rotation.x, t.transform.rotation.y,
                                        t.transform.rotation.z, t.transform.rotation.w]}
                          for t in m.transforms]

    # ── 落盘 ────────────────────────────────────────────────────────────────
    def try_save(self) -> bool:
        if self.color is None or self.depth is None:
            return False
        if self.n >= self.want:
            return True
        os.makedirs(self.out, exist_ok=True)
        i = self.n
        np.save(os.path.join(self.out, f"color_{i:03d}.npy"), self.color)
        np.save(os.path.join(self.out, f"depth_{i:03d}.npy"), self.depth)
        with open(os.path.join(self.out, "camera_info.json"), "w") as f:
            json.dump(self.ci or {}, f, indent=1)
        with open(os.path.join(self.out, "tf_static.json"), "w") as f:
            json.dump(self.tf_static or [], f, indent=1)
        with open(os.path.join(self.out, "tcp_pose.json"), "w") as f:
            json.dump(self.tcp or {}, f, indent=1)
        self.meta["saved"].append(i)
        self.n += 1
        print(f"[realcam] 存 {i} 帧: color{self.color.shape} {self.meta['color_enc']} · "
              f"depth{self.depth.shape} {self.meta['depth_enc']} · ci={'Y' if self.ci else 'N'} · "
              f"tf_static={len(self.tf_static or [])} · tcp={'Y' if self.tcp else 'N'}", flush=True)
        with open(os.path.join(self.out, "meta.json"), "w") as f:
            json.dump(self.meta, f, indent=1, ensure_ascii=False)
        return self.n >= self.want


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/out")
    ap.add_argument("--frames", type=int, default=12)
    ap.add_argument("--timeout", type=float, default=40.0)
    a = ap.parse_args()
    rclpy.init()
    node = Recorder(a.out, a.frames, a.timeout)
    try:
        while rclpy.ok():
            rclpy.spin_once(node, timeout_sec=0.2)
            if node.try_save():
                break
            if time.time() > node.deadline:
                print(f"⏱ 超时: 只收到 color={'Y' if node.color is not None else 'N'} "
                      f"depth={'Y' if node.depth is not None else 'N'} (共 {node.n} 帧落盘)", flush=True)
                break
    finally:
        node.destroy_node()
        rclpy.shutdown()
    print(f"[realcam] 完成: {node.n} 帧 → {a.out}", flush=True)
    return 0 if node.n > 0 else 2


if __name__ == "__main__":
    sys.exit(main())
