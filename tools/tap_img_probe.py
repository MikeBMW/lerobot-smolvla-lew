#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tap_img_probe.py — 容器内一次性探针: 复现 tap 的取图/解码/落盘 路径, 打印真实异常

背景: tap 只在启动后 42s 成功落盘过一次 cam_rs.png (meta tm=42.26 之后再没更新),
      但 img 计数持续增长 (raw 回调有消息) → 怀疑 _tick_img 里被静默 except 吞掉的异常。
本探针不依赖 tap 进程, 独立订阅 → 反序列化 → 解码 → 写盘, 把每一步结果打出来。
"""
import os
import sys
import time

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image
from rclpy.serialization import deserialize_message

TOPIC = sys.argv[1] if len(sys.argv) > 1 else "/realsense/color/image_raw"
OUT = os.environ.get("SS_OUT", "/out")


class Probe(Node):
    def __init__(self):
        super().__init__("img_probe")
        self.raw = None
        self.n = 0
        self.create_subscription(Image, TOPIC, self.cb, qos_profile_sensor_data, raw=True)

    def cb(self, m):
        self.raw = m
        self.n += 1


def png_write(arr, path, gray=False):
    import struct
    import zlib
    h, w = arr.shape[:2]
    raw = b"".join(b"\x00" + arr[y].tobytes() for y in range(h))

    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0 if gray else 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 6))
    png += chunk(b"IEND", b"")
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "wb") as f:
        f.write(png)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    return len(png)


def main():
    rclpy.init()
    p = Probe()
    t0 = time.monotonic()
    while time.monotonic() - t0 < 12:
        rclpy.spin_once(p, timeout_sec=0.05)
    print("[probe] raw 回调消息数 = %d" % p.n, flush=True)
    if p.raw is None:
        print("[probe] ❌ 12s 内没收到任何 raw 消息 → 话题无发布者/网络不通", flush=True)
        return 1
    try:
        msg = deserialize_message(bytes(p.raw), Image)
        print("[probe] 反序列化 OK: %s %dx%d enc=%s step=%d data=%d字节"
              % (msg.header.frame_id, msg.width, msg.height, msg.encoding, msg.step, len(msg.data)), flush=True)
    except Exception as e:                                              # noqa: BLE001
        print("[probe] ❌ 反序列化失败: %s: %s" % (type(e).__name__, e), flush=True)
        return 1
    try:
        buf = np.frombuffer(bytes(msg.data), dtype=np.uint8)
        h, w = int(msg.height), int(msg.width)
        a = buf[: h * w * 3].reshape(h, w, 3)
        if msg.encoding.lower() == "bgr8":
            a = a[:, :, ::-1]
        print("[probe] 解码 OK: std=%.2f (真图判据 std>5)" % a.std(), flush=True)
        n = png_write(np.ascontiguousarray(a), os.path.join(OUT, "cam_probe.png"))
        print("[probe] ✅ 落盘 OK: %s (%d 字节)" % (os.path.join(OUT, "cam_probe.png"), n), flush=True)
    except Exception as e:                                              # noqa: BLE001
        print("[probe] ❌ 解码/落盘失败: %s: %s" % (type(e).__name__, e), flush=True)
        return 1
    print("[probe] 结论: 取图→解码→落盘 全链在本容器可行; tap 侧未更新 = tap 自身定时/循环问题", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
