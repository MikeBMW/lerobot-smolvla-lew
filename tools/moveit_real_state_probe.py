#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
moveit_real_state_probe.py — 只读抓真机当前状态(关节角 + TCP 位姿), 供 MoveIt 侧做同源校验
────────────────────────────────────────────────────────────
老倪 2026-09-29 语境: 「轨迹线应该是状态空间工程里 moveit 节点规划出来的」——
  但 MoveIt 的 URDF 运动学与真机**不同源**(FK 差 261.5mm), 所以先要有"真机当前状态"这一基准:
  · 起状态: 用真关节角(而不是 IK 猜)
  · 决定性校验: FK(真关节) vs 真 /robot/tcp_pose ⇒ 证明 URDF/基座系是否与真机同源

跑在 **domain0 的容器**里(真机话题在 domain0):  ss-remote-tap / zmax-arm-raw
    sudo docker exec ss-remote-tap python3 /repo/tools/moveit_real_state_probe.py \
        --out /repo/reports/moveit/real_state.json

坑(实测): 真机话题是 **BEST_EFFORT**, 用默认 RELIABLE 订阅收不到任何消息 —— 本脚本两种都试并如实报告。
"""
import argparse
import json
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy, DurabilityPolicy

JS_TOPIC = "/robot/joint_states"
TCP_TOPIC = "/robot/tcp_pose"


def qos(rel):
    return QoSProfile(depth=5, history=HistoryPolicy.KEEP_LAST, durability=DurabilityPolicy.VOLATILE,
                      reliability=rel)


class Probe(Node):
    def __init__(self, joint_topic, tcp_topic, seconds):
        super().__init__("zmax_real_state_probe")
        self.seconds = seconds
        self.joints, self.js_stamp, self.js_qos = None, None, None
        self.tcp, self.tcp_stamp, self.tcp_qos = None, None, None
        for rel, tag in ((ReliabilityPolicy.BEST_EFFORT, "BEST_EFFORT"),
                         (ReliabilityPolicy.RELIABLE, "RELIABLE")):
            self.create_subscription(type(self)._js_type(), joint_topic,
                                     lambda m, t=tag: self._on_js(m, t), qos(rel))
            self.create_subscription(type(self)._tcp_type(), tcp_topic,
                                     lambda m, t=tag: self._on_tcp(m, t), qos(rel))
        self.get_logger().info("订阅 %s + %s (BEST_EFFORT 与 RELIABLE 各一条)" % (joint_topic, tcp_topic))

    @staticmethod
    def _js_type():
        from sensor_msgs.msg import JointState
        return JointState

    @staticmethod
    def _tcp_type():
        from geometry_msgs.msg import PoseStamped
        return PoseStamped

    def _on_js(self, m, tag):
        if self.joints is None or tag == "BEST_EFFORT":
            self.joints = {n: float(p) for n, p in zip(m.name, m.position)}
            self.js_stamp = float(m.header.stamp.sec) + float(m.header.stamp.nanosec) * 1e-9
            self.js_qos = tag

    def _on_tcp(self, m, tag):
        if self.tcp is None or tag == "BEST_EFFORT":
            p = m.pose.position
            q = m.pose.orientation
            self.tcp = [p.x, p.y, p.z, q.x, q.y, q.z, q.w]
            self.tcp_stamp = float(m.header.stamp.sec) + float(m.header.stamp.nanosec) * 1e-9
            self.tcp_qos = tag


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--joint-topic", default=JS_TOPIC)
    ap.add_argument("--tcp-topic", default=TCP_TOPIC)
    ap.add_argument("--seconds", type=float, default=12.0, help="最长等待秒数")
    ap.add_argument("--out", default="real_state.json")
    a = ap.parse_args()

    rclpy.init()
    n = Probe(a.joint_topic, a.tcp_topic, a.seconds)
    t0 = time.time()
    while time.time() - t0 < a.seconds:
        rclpy.spin_once(n, timeout_sec=0.5)
        if n.joints is not None and n.tcp is not None:
            break
    js, tcp = n.joints, n.tcp
    n.destroy_node()
    rclpy.shutdown()

    if js is None or tcp is None:
        print("❌ 收不到: joints=%s tcp=%s (检查 domain0 / 话题名 / QoS)" % (js is not None, tcp is not None))
        return 2
    # 关节名去掉前缀, 只留真机口径(joint_1..6) + 原始名都留档
    out = {
        "source": "domain0 真机话题(只读)",
        "joint_topic": a.joint_topic, "tcp_topic": a.tcp_topic,
        "qos_used": {"joint_states": n.js_qos, "tcp_pose": n.tcp_qos},
        "joints": js,
        "tcp_pose_xyzw": tcp,
        "stamps": {"joints": n.js_stamp, "tcp": tcp and n.tcp_stamp},
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("✅ 真机状态: 关节 %d 个 [%s]" % (len(js), ", ".join(sorted(js)[:8])))
    print("   joint namelist: %s" % list(js.keys()))
    print("   TCP = [%s]  (QoS: joint=%s tcp=%s)" % (
        ", ".join("%.5f" % v for v in tcp), n.js_qos, n.tcp_qos))
    print("   已写 %s" % a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
