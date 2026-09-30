#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ros_tcp_cache.py — TCP 位姿高速缓存 [容器 ss-remote-tap 内跑, 常驻]
════════════════════════════════════════════════════════════════════
问题: `ssh ros2 topic echo --once /robot/tcp_pose` 单次要 ~3s ⇒ 叠加渲染线程每 2s 去读一次,
      帧龄被拖到 3s，叠加帧率掉到 ~0.3fps。

做法: 容器内常驻订阅 (50Hz 话题, 实际按 --hz 落盘), 原子写一个小 JSON。
      消费侧只读文件 ⇒ 微秒级，叠加帧率不再受位姿读取拖累。

产出: /out/zmax_scene/tcp_pose.json
      {"t":<unix>,"xyz":[x,y,z],"quat":[qx,qy,qz,qw],"age_s":<写入时的新鲜度>}

用法:
  sudo docker exec -d ss-remote-tap bash -lc 'source /opt/ros/humble/setup.bash && \
    export ROS_DOMAIN_ID=0 && python3 /repo/tools/ros_tcp_cache.py --hz 20'
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import rclpy
from geometry_msgs.msg import PoseStamped
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String

OUT = Path("/out/zmax_scene/tcp_pose.json")
# 🩺 2026-09-27: 顺带缓存 /robot_status (三查: 上电/运行态/报警) ——
#   手动控制区要显示"是否 idle / 有没有报警", 而 `ssh ros2 topic echo --once` 单次 3~7s,
#   页面 1.5s 轮询顶不住 ⇒ 同 TCP 位姿一样落文件, 宿主微秒级读。
OUT_ST = Path("/out/zmax_scene/robot_status.json")


class TcpCache(Node):
    def __init__(self):
        super().__init__("zmax_tcp_cache", enable_rosout=False)
        self.last = None
        self.stamp = 0.0
        self.st = None                      # 🩺 最近一条 /robot_status(已解析)
        self.st_stamp = 0.0
        self.create_subscription(
            PoseStamped, "/robot/tcp_pose", self._on,
            QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT,
                       history=HistoryPolicy.KEEP_LAST))
        self.create_subscription(
            String, "/robot_status", self._on_st,
            QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT,
                       history=HistoryPolicy.KEEP_LAST))

    def _on(self, m: PoseStamped):
        p = m.pose
        self.last = {"xyz": [p.position.x, p.position.y, p.position.z],
                     "quat": [p.orientation.x, p.orientation.y, p.orientation.z, p.orientation.w],
                     "frame_id": m.header.frame_id}
        self.stamp = time.time()

    def _on_st(self, m: String):
        """话题载荷是 JSON 字符串(实测样例: {"success":true,"power_state":"on",...})"""
        try:
            d = json.loads(m.data)
            if isinstance(d, dict):
                self.st = d
                self.st_stamp = time.time()
        except Exception:                    # 载荷不是 JSON 就原样记下来, 别丢信息
            self.st = {"raw": m.data[:400]}
            self.st_stamp = time.time()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hz", type=float, default=20.0, help="落盘频率 (话题本身 50Hz)")
    a = ap.parse_args()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    rclpy.init()
    n = TcpCache()
    period = 1.0 / a.hz
    nxt = time.time()
    writes = 0
    print("  TCP 缓存启动: /robot/tcp_pose → %s @%.0fHz" % (OUT, a.hz), flush=True)
    print("  三查缓存启动: /robot_status → %s" % OUT_ST, flush=True)
    while rclpy.ok():
        rclpy.spin_once(n, timeout_sec=0.05)
        if n.last is not None and time.time() >= nxt:
            d = dict(n.last)
            d["t"] = n.stamp
            d["age_s"] = round(time.time() - n.stamp, 3)
            tmp = OUT.with_suffix(".tmp")
            try:
                tmp.write_text(json.dumps(d), encoding="utf-8")
                os.replace(tmp, OUT)          # 原子替换 ⇒ 读侧永远读到完整 JSON
                writes += 1
            except Exception as e:
                print("  ⚠ 写失败: %s" % e, flush=True)
            # 🩺 三查状态 (与位姿同一落盘节奏; 没有新消息就不覆盖, 保留最后一条 + 其帧龄)
            if n.st is not None:
                ds = dict(n.st)
                ds["t"] = n.st_stamp
                ds["age_s"] = round(time.time() - n.st_stamp, 3)
                tmp2 = OUT_ST.with_suffix(".tmp")
                try:
                    tmp2.write_text(json.dumps(ds, ensure_ascii=False), encoding="utf-8")
                    os.replace(tmp2, OUT_ST)
                except Exception as e:
                    print("  ⚠ 状态写失败: %s" % e, flush=True)
            nxt = time.time() + period
            if writes % 200 == 1:
                print("  已写 %d 次 · TCP=(%.4f,%.4f,%.4f)"
                      % (writes, *d["xyz"]), flush=True)
    n.destroy_node()
    rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
