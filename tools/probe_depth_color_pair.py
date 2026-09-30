#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_depth_color_pair.py — 同一时刻取 深度+彩色 一对, 验证深度图布局是否正确

为什么要这个: 老倪要的深度窗口必须**是真深度、且和彩色画面同一场景**。
  单看深度图"像不像深度"不可靠(花的图也能看着有梯度)。判据取**同一时刻的一对**:
    · 深度图与彩色图的**边缘结构**必须正相关(同一场景的同一批物体边界);
      时间错开几秒/不同传感器视差的对比都会被污染的, 所以要在同一个节点里同时收两路。
    · 若布局搞错(例如把行主序当列主序), 重排后是"花"的, 相关性会掉到 0 附近。
  只读订阅, 不发任何指令。

用法 (容器内):
  sudo docker exec ss-remote-tap bash -lc 'source /opt/ros/humble/setup.bash && \
    export ROS_DOMAIN_ID=0 && python3 /repo/tools/probe_depth_color_pair.py'
"""
from __future__ import annotations

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import Image

Q = QoSProfile(depth=1, history=HistoryPolicy.KEEP_LAST,
               reliability=ReliabilityPolicy.BEST_EFFORT)


def _grad_mag(a: np.ndarray) -> np.ndarray:
    """3x3 盒式平滑后的 Sobel 幅度 (不依赖 cv2)"""
    k = np.ones((3, 3), np.float32) / 9.0
    s = np.zeros_like(a)
    for dy in (0, 1, 2):
        for dx in (0, 1, 2):
            s[1:-1, 1:-1] += a[dy:a.shape[0] - 2 + dy, dx:a.shape[1] - 2 + dx] * k[dy, dx]
    gx = s[1:-1, 2:] - s[1:-1, :-2]
    gy = s[2:, 1:-1] - s[:-2, 1:-1]
    return np.hypot(gx, gy)


class Pair(Node):
    def __init__(self):
        super().__init__("zmax_depth_pair_probe")
        self.depth = None
        self.color = None
        self.n = 0
        self.create_subscription(Image, "/realsense/depth/image_rect_raw", self.on_d, Q)
        self.create_subscription(Image, "/realsense/color/image_raw", self.on_c, Q)

    def on_d(self, m: Image):
        a = np.frombuffer(bytes(m.data), np.uint16)
        if a.size >= m.height * m.width:
            self.depth = (a[: m.height * m.width].reshape(m.height, m.width).astype(np.float32)
                          * 0.0001, m.height, m.width, m.step)
    def on_c(self, m: Image):
        b = np.frombuffer(bytes(m.data), np.uint8)
        n = m.height * m.width
        if b.size >= n * 3:
            img = b[: n * 3].reshape(m.height, m.width, 3).astype(np.float32)
            self.color = (img.mean(axis=2), m.height, m.width, m.encoding)


def main() -> int:
    rclpy.init()
    p = Pair()
    got = 0
    for i in range(600):
        rclpy.spin_once(p, timeout_sec=0.05)
        if p.depth and p.color:
            got += 1
            d, dh, dw, dstep = p.depth
            c, ch, cw, cenc = p.color
            if (dh, dw) != (ch, cw):
                print("尺寸不同: 深度 %dx%d vs 彩色 %dx%d (编码 %s)" % (dw, dh, cw, ch, cenc))
            # 统一降到 240x320 再比 (抗噪, 也避开视差)
            di = d[::2, ::2][: d.shape[0] // 2, : d.shape[1] // 2]
            ci = c[::2, ::2][: c.shape[0] // 2, : c.shape[1] // 2]
            hh = min(di.shape[0], ci.shape[0]); ww = min(di.shape[1], ci.shape[1])
            di, ci = di[:hh, :ww], ci[:hh, :ww]
            valid = (di > 0.05) & (di < 6.0)
            gd = _grad_mag(np.nan_to_num(di))
            gc = _grad_mag(ci)
            msk = (valid[1:-1, 1:-1]) & (valid[1:-1, 2:])
            m2 = msk[: gd.shape[0], : gd.shape[1]]
            a = gd.ravel(); b = gc.ravel(); mm = m2.ravel()[: a.size]
            if mm.sum() > 500:
                a, b = a[mm], b[mm]
                if a.std() > 0 and b.std() > 0:
                    print("样品%d 深度 %dx%d step=%d · 彩色 %dx%d(%s) · 有效 %.0f%% · 边缘相关 %+.3f"
                          % (got, dw, dh, dstep, cw, ch, cenc, valid.mean() * 100,
                             float(np.corrcoef(a, b)[0, 1])))
            if got >= 3:
                break
            p.depth = p.color = None
    if not got:
        print("⚠️ 20~30s 内没凑齐一对 (深度 0.24Hz / 彩色更慢?)")
    p.destroy_node()
    rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
