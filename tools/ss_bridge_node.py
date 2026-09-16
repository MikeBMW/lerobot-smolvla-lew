#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Z-MAX 跨机闭环 Step 1 · 4060 侧 ROS 桥节点 (跑在 Docker ros:humble 容器里, --network host)

职责 (只做搬运, 不碰硬件):
  订阅 /zmax_ss/state  ← Orin 采集节点发布的真机状态 (std_msgs/String, JSON)
  POST http://127.0.0.1:8790/infer  → 本机 venv 推理服务 (torch/CUDA 在 venv, 模型不被搬进容器)
  发布 /zmax_ss/action → Orin 侧只记录不下发 (Step 1 铁律: 旁路)

为什么用容器: 本机是 Ubuntu 24.04(no ROS), Orin 是 Humble(22.04)。用 ros:humble-ros-base 镜像
+ --network host 让 DDS 组播直接上局域网, 与 Orin 同发行版同 domain(0), 零兼容风险。

契约: 见 tools/ss_edge_node.py 头注释 (state/action 两个 JSON 报文的字段)。
"""
import argparse
import json
import os
import time
import urllib.request

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from std_msgs.msg import String

Q = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE, history=HistoryPolicy.KEEP_LAST)


class BridgeNode(Node):
    def __init__(self, state_topic, action_topic, infer_url):
        super().__init__("ss_bridge")
        self.infer_url = infer_url
        self.n_in = self.n_out = self.n_err = 0
        self.lat = []
        self.create_subscription(String, state_topic, self.on_state, Q)
        self.pub = self.create_publisher(String, action_topic, Q)
        self.get_logger().info(f"🌉 桥节点就绪: {state_topic} → {infer_url} → {action_topic}")

    def on_state(self, msg):
        try:
            st = json.loads(msg.data)
        except Exception:
            self.n_err += 1
            return
        self.n_in += 1
        t0 = time.time()
        try:
            req = urllib.request.Request(self.infer_url + "/infer",
                                         data=json.dumps({"state": st}).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=5) as r:
                res = json.loads(r.read())
        except Exception as e:
            self.n_err += 1
            if self.n_err <= 3 or self.n_err % 50 == 0:
                self.get_logger().warn(f"⚠️ 推理服务调用失败({self.n_err}): {type(e).__name__}: {str(e)[:60]}")
            return
        e2e_ms = round((time.time() - t0) * 1000, 2)
        out = {
            "t": time.time(), "seq": st.get("seq"), "src": "host4060", "mode": "shadow_only",
            "action": res.get("action"), "yaw": res.get("yaw"),
            "model_ms": res.get("model_ms"), "e2e_ms": e2e_ms,
            "input_map": res.get("input_map"),
            "note": "结果仅记录, 不下发 (Step 1 旁路)",
        }
        m = String()
        m.data = json.dumps(out, ensure_ascii=False)
        self.pub.publish(m)
        self.n_out += 1
        self.lat.append(e2e_ms)
        if self.n_out % 20 == 0:
            self.get_logger().info(
                f"↩️ 回传 {self.n_out} 帧 (in={self.n_in} err={self.n_err}) · 模型 {res.get('model_ms')}ms · "
                f"端到端 中位 {sorted(self.lat[-40:])[len(self.lat[-40:]) // 2]:.1f}ms")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-topic", default="/zmax_ss/state")
    ap.add_argument("--action-topic", default="/zmax_ss/action")
    ap.add_argument("--infer-url", default="http://127.0.0.1:8790")
    a = ap.parse_args()
    os.environ.setdefault("ROS_DOMAIN_ID", "0")
    rclpy.init()
    n = BridgeNode(a.state_topic, a.action_topic, a.infer_url)
    try:
        rclpy.spin(n)
    except KeyboardInterrupt:
        pass
    finally:
        n.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
