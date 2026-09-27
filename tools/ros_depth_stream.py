#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ros_depth_stream.py — D405 深度图实时落盘 [容器 ss-remote-tap 内跑, 常驻]

老倪 2026-09-27: 工位总览要**同时**看 3 路彩图 + **深度图** + 金手指/表面检测 ⇒ 深度得有常驻源。

为什么分两段 (实测过的依赖约束):
  ROS 容器 `ss-remote-tap` 里 **有 numpy 没有 cv2**(`ros:humble-ros-base` 不带), 而往容器里装 cv2
  **容器一重启就没了**(ephemeral) ⇒ 容器只做"只读订阅 + 落原始数组", 彩色化交给宿主侧
  (cam_live_stream 的 depth 源, gui-venv311 有 cv2/numpy)。零新依赖、零脆弱性。

产出 (容器 /out → 宿主 /home/ubuntu/zmax_ss_remote):
  zmax_scene/depth_raw.npy   uint16 原始深度 (原子替换)
  zmax_scene/depth_meta.json {t, frames, fps, w, h, depth_scale, near/median/center_m, valid_pct, src_stamp_age_s}
  容器里恰好有 cv2 时**另外**再写 depth_live.jpg (伪彩+真值带); 没有就跳过, 宿主自己上色。

深度单位 (实测口径): D405 `depth_scale = 0.0001 m/unit` ⇒ 原始值 4013 = **401.3mm**。
      **别把 raw 当 mm** (4013mm=4m 会一眼看错)。

用法 (宿主):
  sudo docker exec -d ss-remote-tap bash -lc 'source /opt/ros/humble/setup.bash && \
      export ROS_DOMAIN_ID=0 && python3 /repo/tools/ros_depth_stream.py --hz 5'
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import Image

try:                                  # 容器里一般没有 → 走"宿主上色"分支
    import cv2
except Exception:                                                             # noqa: BLE001
    cv2 = None

# 彩色化口径**唯一真源**: tools/depth_colorize.py (宿主 cam_live_stream 也 import 同一份,
# 免得两边颜色/量程/文字各写一套 → 迟早漂移)。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from depth_colorize import RANGE_M, colorize          # noqa: E402

DEPTH_SCALE = 0.0001                  # m / unit (D405 出厂 depth_scale)
OUT_DIR = Path("/out/zmax_scene")
OUT_NPY = OUT_DIR / "depth_raw.npy"
OUT_JSON = OUT_DIR / "depth_meta.json"
OUT_JPG = OUT_DIR / "depth_live.jpg"


class DepthStream(Node):
    def __init__(self, hz: float):
        super().__init__("zmax_depth_stream")
        self.hz, self.n, self.last = hz, 0, 0.0
        self.fps, self._t, self._t0 = 0.0, [], None
        qos = QoSProfile(depth=2, history=HistoryPolicy.KEEP_LAST,
                         reliability=ReliabilityPolicy.BEST_EFFORT)
        self.create_subscription(Image, "/realsense/depth/image_rect_raw", self.cb, qos)
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        print("[depth] 订阅 /realsense/depth/image_rect_raw · cv2=%s · 落盘 %s @%.1fHz"
              % ("有" if cv2 else "无(交宿主编色)", OUT_NPY, hz), flush=True)

    def _stamp_age(self, msg: Image) -> float:
        """帧龄 = 现在 − 头时间戳 (按首帧对齐墙钟; Orin ROS 时钟与本机墙钟不同源, 只取相对量)"""
        s = float(msg.header.stamp.sec) + float(msg.header.stamp.nanosec) * 1e-9
        now = time.time()
        if self._t0 is None:
            self._t0 = (now, s)
        w0, s0 = self._t0
        return max(0.0, (now - w0) - (s - s0))

    def cb(self, msg: Image):
        now = time.time()
        self.n += 1
        self._t.append(now)
        self._t = [t for t in self._t if now - t < 2.0]
        self.fps = len(self._t) / 2.0
        if now - self.last < 1.0 / max(0.5, self.hz):
            return
        self.last = now
        try:
            h, w = int(msg.height), int(msg.width)
            buf = np.frombuffer(bytes(msg.data), dtype=np.uint16)
            if buf.size < h * w:
                return
            raw = buf[:h * w].reshape(h, w)
            d = raw.astype(np.float32) * DEPTH_SCALE
            valid = (d > 0.05) & (d < 6.0)
            v = d[valid]
            cen = float(d[h // 2, w // 2])
            meta = {
                "t": now, "frames": self.n, "fps": round(self.fps, 2),
                "w": w, "h": h, "depth_scale": DEPTH_SCALE, "range_m": list(RANGE_M),
                "valid_pct": round(float(valid.mean()) * 100.0, 1),
                "near_m": round(float(v.min()), 3) if v.size else None,
                "median_m": round(float(np.median(v)), 3) if v.size else None,
                "center_m": round(cen, 3) if cen > 0 else None,
                "src_stamp_age_s": round(self._stamp_age(msg), 3),
                "colored_by": "container" if cv2 is not None else "host",
            }
            tmp = str(OUT_NPY) + ".tmp.npy"
            np.save(tmp, raw)                        # 原子替换: 消费侧永远读完整数组
            os.replace(tmp, OUT_NPY)
            OUT_JSON.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
            if cv2 is not None:
                jpg = colorize(d, meta)
                if jpg:
                    tmpj = str(OUT_JPG) + ".tmp"
                    Path(tmpj).write_bytes(jpg)
                    os.replace(tmpj, OUT_JPG)
        except Exception as e:                                                    # noqa: BLE001
            print("[depth] 处理异常: %s" % str(e)[:160], flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hz", type=float, default=5.0, help="落盘频率 (页面看 4~6 足够)")
    a = ap.parse_args()
    rclpy.init()
    node = DepthStream(a.hz)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
