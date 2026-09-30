#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
live_motion_recorder.py — 现场拖动机器人时的**实时录制**(真关节角 + 真 TCP), 用来:
  ① 事后引用用户说的"停顿点"(按时间戳复现那一帧的位姿)
  ② 攒 (关节角, TCP) 配对 → 后面拟合 MoveIt URDF 的 6 个关节零位偏移(同源闸修法)
  ③ 画**实时轨迹**(真机 TCP 折线)到臂上相机叠加层

跑在 **domain0 容器**(真机话题所在): ss-remote-tap / zmax-arm-raw
    sudo docker exec -d ss-remote-tap bash -lc 'source /opt/ros/humble/setup.bash && \
        python3 /repo/tools/live_motion_recorder.py --seconds 3600 --hz 50 \
        --jsonl /tmp/live_motion.jsonl --trace /tmp/live_trace.json'

坑(实测): 真机话题是 **BEST_EFFORT** ⇒ 用默认 RELIABLE 订阅一个字节都收不到(只报 incompatible QoS)。
容器里仓库挂载可能是**只读** ⇒ 一律写 /tmp, 完事 `docker cp` 出来。
"""
import argparse
import json
import math
import os
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy, DurabilityPolicy


def qos(rel):
    return QoSProfile(depth=50, history=HistoryPolicy.KEEP_LAST,
                      durability=DurabilityPolicy.VOLATILE, reliability=rel)


class Rec(Node):
    def __init__(self, jt, tt, hz, jsonl, trace, min_dt_trace, head):
        super().__init__("zmax_live_motion_recorder")
        self.hz, self.min_dt_trace = hz, min_dt_trace
        self.jsonl, self.trace_path = jsonl, trace
        self.f = open(jsonl, "a", encoding="utf-8")
        self.js = None
        self.tcp = None
        self.tcp_qos = None
        self.n = 0
        self.trace = []            # TCP 折线(降采样, 供叠加层画)
        self.last_trace_t = 0.0
        self.head = __import__("collections").deque(maxlen=120)   # 最近 120 条(供停顿识别)
        self.head_path = head
        self.last_head = 0.0
        self.t0 = time.time()
        self.last_write = 0.0
        for rel, tag in ((ReliabilityPolicy.BEST_EFFORT, "BEST_EFFORT"),
                         (ReliabilityPolicy.RELIABLE, "RELIABLE")):
            from sensor_msgs.msg import JointState
            from geometry_msgs.msg import PoseStamped
            self.create_subscription(JointState, jt, self._on_js, qos(rel))
            self.create_subscription(PoseStamped, tt, lambda m, t=tag: self._on_tcp(m, t), qos(rel))
        # 周期落盘(1Hz) + 体检行(10s)
        self.create_timer(1.0 / max(1.0, float(hz)), self._tick)
        self.create_timer(10.0, self._beat)
        print("录制中: %s + %s @%.0fHz → %s" % (jt, tt, hz, jsonl), flush=True)

    def _on_js(self, m):
        self.js = {n: float(p) for n, p in zip(m.name, m.position)}

    def _on_tcp(self, m, tag):
        self.tcp_qos = tag
        p, q = m.pose.position, m.pose.orientation
        self.tcp = [p.x, p.y, p.z, q.x, q.y, q.z, q.w]

    def _tick(self):
        if self.js is None or self.tcp is None:
            return
        now = time.time()
        if now - self.last_write < 1.0 / max(1.0, float(self.hz)):
            return
        self.last_write = now
        rec = {"t": round(now - self.t0, 4), "wall": time.strftime("%H:%M:%S"),
               "js": {k: round(v, 6) for k, v in self.js.items()},
               "tcp": [round(v, 6) for v in self.tcp]}
        self.f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.n += 1
        self.head.append(rec)
        if self.n % 25 == 0:
            self.f.flush()
        # 每 ~0.5s 落一份"最近 120 条"的小文件: 宿主机侧的停顿识别只读它
        # (整份 jsonl 会涨到几十 MB, 每秒 docker cp 一次不现实 —— 2026-09-29 实测踩到)
        if now - self.last_head >= 0.5:
            self.last_head = now
            try:
                t = self.head_path + ".tmp"
                with open(t, "w", encoding="utf-8") as fh:
                    json.dump({"head": list(self.head), "n": self.n, "at": rec["wall"]}, fh)
                os.replace(t, self.head_path)            # 同上: 原子落盘
            except Exception as e:                                            # noqa: BLE001
                print("head 写失败: %s" % e, flush=True)
        if now - self.last_trace_t >= self.min_dt_trace:
            self.last_trace_t = now
            self.trace.append([round(v, 5) for v in self.tcp[:3]])
            if len(self.trace) > 40000:
                self.trace = self.trace[::2]     # 过长就抽稀一半
            try:
                t = self.trace_path + ".tmp"
                with open(t, "w", encoding="utf-8") as fh:
                    json.dump({"kind": "path3d", "pts": self.trace, "n": len(self.trace),
                               "hz": self.hz, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}, fh)
                os.replace(t, self.trace_path)          # 原子: 读侧永远拿到完整 JSON
            except Exception as e:                                        # noqa: BLE001
                print("trace 写失败: %s" % e, flush=True)

    def _beat(self):
        self.f.flush()
        if self.tcp:
            print("[%s] %d 条 · TCP=(%.4f, %.4f, %.4f) · 轨迹点 %d" % (
                time.strftime("%H:%M:%S"), self.n, self.tcp[0], self.tcp[1], self.tcp[2],
                len(self.trace)), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--joint-topic", default="/robot/joint_states")
    ap.add_argument("--tcp-topic", default="/robot/tcp_pose")
    ap.add_argument("--hz", type=float, default=50.0)
    ap.add_argument("--seconds", type=float, default=3600.0)
    ap.add_argument("--jsonl", default="/tmp/live_motion.jsonl")
    ap.add_argument("--trace", default="/tmp/live_trace.json")
    ap.add_argument("--head", default="/tmp/live_head.json", help="最近 120 条的滚动小文件")
    ap.add_argument("--trace-dt", type=float, default=0.2, help="轨迹折线抽点间隔(秒)")
    a = ap.parse_args()

    rclpy.init()
    n = Rec(a.joint_topic, a.tcp_topic, a.hz, a.jsonl, a.trace, a.trace_dt, a.head)
    t0 = time.time()
    try:
        while time.time() - t0 < a.seconds:
            rclpy.spin_once(n, timeout_sec=0.2)
    except KeyboardInterrupt:
        pass
    n.f.flush()
    n.destroy_node()
    rclpy.shutdown()
    print("✅ 录制结束: %d 条, 轨迹点 %d" % (n.n, len(n.trace)), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
