#!/usr/bin/env python3
"""一次性打印深度话题的原始元数据 (排查: 彩色化图与彩色图边缘不相关 → 怀疑 step/编码/字节序)"""
import rclpy
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import Image
import numpy as np


class P(Node):
    def __init__(self):
        super().__init__("zmax_depth_probe")
        q = QoSProfile(depth=1, history=HistoryPolicy.KEEP_LAST,
                       reliability=ReliabilityPolicy.BEST_EFFORT)
        self.create_subscription(Image, "/realsense/depth/image_rect_raw", self.cb, q)
        self.done = False

    def cb(self, m: Image):
        if self.done:
            return
        self.done = True
        n = len(m.data)
        print("height=%d width=%d step=%d encoding=%r is_bigendian=%d len(data)=%d"
              % (m.height, m.width, m.step, m.encoding, m.is_bigendian, n))
        print("按 width*2 期望 %d 字节; 按 step*height 期望 %d 字节 ⇒ %s"
              % (m.width * 2, m.step * m.height,
                 "step==width*2, reshape(h,w) 正确" if m.step == m.width * 2
                 else "⚠️ step != width*2 ⇒ 现有 reshape(h,w) 错位!"))
        a = np.frombuffer(bytes(m.data), np.uint16)
        print("前 12 个原始值:", a[:12].tolist())
        print("原始值分位: min=%d p10=%d 中位=%d p90=%d max=%d"
              % (a.min(), int(np.percentile(a, 10)), int(np.median(a)), int(np.percentile(a, 90)), a.max()))
        # 两种 reshape 谁更"像平面": 逐行中位数的平滑度 (真深度图逐行应平滑变化)
        for tag, arr in (("reshape(h,w)", a[: m.height * m.width].reshape(m.height, m.width)),
                         ("reshape(w,h).T", a[: m.height * m.width].reshape(m.width, m.height).T)):
            d = arr.astype(np.float32) * 0.0001
            v = (d > 0.05) & (d < 6)
            row = np.array([np.median(d[i][v[i]]) if v[i].any() else np.nan for i in range(d.shape[0])])
            row = row[np.isfinite(row)]
            rough = float(np.mean(np.abs(np.diff(row)))) * 1000 if row.size > 3 else -1
            print("  %-16s 逐行中位粗糙度 %.1fmm (越小越平滑)" % (tag, rough))


rclpy.init()
n = P()
for _ in range(400):                      # 话题 0.24Hz ⇒ 最多等 ~20s (0.05s * 400)
    rclpy.spin_once(n, timeout_sec=0.05)
    if n.done:
        break
print("完成" if n.done else "⚠️ 20s 内没收到深度帧")
n.destroy_node()
rclpy.shutdown()
