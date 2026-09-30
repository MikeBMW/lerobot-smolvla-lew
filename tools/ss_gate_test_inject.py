#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Step 2 · 闸门判决的确定性测试注入器 (跑在 ros:humble 容器里, 只发 /zmax_ss/action)

目的: 往 Orin 闸门喂**构造好的提案**, 验证每条判据真生效 (不靠现场碰运气):
  1 ok        正常方向 + 幅值合理 + 阶段在白名单      → 期望 pass_no_exec (或 disarmed)
  2 dir_rev   方向反向 (取负)                          → 期望 veto_dir (cos≈-1)
  3 mag_big   幅值 ×20                                 → 期望 veto_mag
  4 stale     t 回溯 5 秒                              → 期望 veto_stale
  5 stage_out 阶段=插入 (不在白名单)                    → 期望 veto_stage
  6 shape     动作维度只有 2                            → 期望 veto_shape

用法: source /opt/ros/humble/setup.bash && python3 ss_gate_test_inject.py [--action-topic /zmax_ss/action]
输出: 每 0.5s 发一条 (按上面顺序循环), 便于 Orin 侧 gate_*.jsonl 逐条对照。
"""
import argparse
import json
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from std_msgs.msg import String


class Injector(Node):
    def __init__(self, topic):
        super().__init__("ss_gate_inject")
        q = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE, history=HistoryPolicy.KEEP_LAST)
        self.pub = self.create_publisher(String, topic, q)
        self.cases = ["ok", "dir_rev", "mag_big", "stale", "stage_out", "shape"]
        self.i = 0
        self.create_timer(0.5, self.tick)
        self.get_logger().info(f"🧪 闸门测试注入器 → {topic} (用例: {self.cases})")

    def tick(self):
        case = self.cases[self.i % len(self.cases)]
        self.i += 1
        now = time.time()
        a = [0.20, -0.15, 0.10, 0.5, 0.0, 0.0]     # 基准提案
        p = {"t": now, "seq": 90000 + self.i, "src": "gate_test", "mode": "shadow_only",
             "stage": "对位", "action": a, "yaw": {"dz": 0.0, "ok": 0.5},
             "model_ms": 0.5, "e2e_ms": 1.0, "input_map": "synthetic", "case": case}
        if case == "dir_rev":
            p["action"] = [-x for x in a]
        elif case == "mag_big":
            p["action"] = [x * 20 for x in a]
        elif case == "stale":
            p["t"] = now - 5.0
        elif case == "stage_out":
            p["stage"] = "插入"
        elif case == "shape":
            p["action"] = [0.2, -0.1]
        m = String()
        m.data = json.dumps(p, ensure_ascii=False)
        self.pub.publish(m)
        self.get_logger().info(f"  发 {case}: {p['action'] if case != 'shape' else p['action']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--action-topic", default="/zmax_ss/action")
    a = ap.parse_args()
    rclpy.init()
    n = Injector(a.action_topic)
    try:
        rclpy.spin(n)
    except KeyboardInterrupt:
        pass
    finally:
        n.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
