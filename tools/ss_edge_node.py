#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Z-MAX 跨机闭环 Step 1 · Orin 侧采集/记录节点 (只读采集 + 只记录, 绝不发布控制)

拓扑: Orin(本节点) --/zmax_ss/state--> 4060(Docker ROS 桥 → venv 推理) --/zmax_ss/action--> Orin(仅记录)

铁律 (Step 1 旁路):
  · 只订阅真机话题, 不发布任何控制话题, 不调用任何服务
  · 收到 4060 的动作提案 **只写 jsonl + 日志**, 不下发 (执行闸门留到 Step 2)

订阅: /robot/joint_states /robot/force_torque /gripper_pos /robot_status /motion/active_states (全部 raw)
发布: /zmax_ss/state (std_msgs/String, JSON, 默认 20Hz)  ← 这是数据上行, 不是控制
记录: /home/tashan/.zmax/ss_link/{state,action}_<日期>.jsonl

state 报文: {"t","seq","src":"orin_edge","joints":[6],"jvel":[6],"gripper","ft":[6],
             "robot_state","prod_stage","pubs":{...},"scope":"readonly"}
  其中 jvel 由 位置差分 得到 (话题自带 velocity 时优先用)
action 报文 (来自 4060): {"t","seq","action":[6],"yaw":{dz,ok},"model_ms","e2e_ms","input_map","mode":"shadow_only"}
"""
import argparse
import json
import os
import threading
import time

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from rclpy.serialization import deserialize_message
from sensor_msgs.msg import JointState
from std_msgs.msg import Float32, String
from geometry_msgs.msg import WrenchStamped

OUT_DIR = os.path.expanduser("~/.zmax/ss_link")
JQ = QoSProfile(depth=5, reliability=ReliabilityPolicy.BEST_EFFORT, history=HistoryPolicy.KEEP_LAST)
AQ = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE, history=HistoryPolicy.KEEP_LAST)


class EdgeNode(Node):
    JOINTS_TOPIC = os.environ.get("SS_EDGE_JOINTS_TOPIC", "/robot/joint_states")

    def __init__(self, state_topic, action_topic, rate_hz):
        super().__init__("ss_edge")
        os.makedirs(OUT_DIR, exist_ok=True)
        day = time.strftime("%Y%m%d")
        self.f_state = open(os.path.join(OUT_DIR, f"state_{day}.jsonl"), "a")
        self.f_action = open(os.path.join(OUT_DIR, f"action_{day}.jsonl"), "a")
        self._lock = threading.Lock()
        self._rj = self._rf = self._rg = self._rst = self._rstage = None
        self.j = self.f = self.g = None
        self.st = self.stage = ""
        self.prev_pos = self.prev_t = None
        self.seq = 0
        self.n_pub = self.n_act = 0
        self.last_act = None

        self.create_subscription(JointState, self.JOINTS_TOPIC, self.cb_j, JQ, raw=True)
        self.create_subscription(WrenchStamped, "/robot/force_torque", self.cb_f, JQ, raw=True)
        self.create_subscription(Float32, "/gripper_pos", self.cb_g, 5, raw=True)
        self.create_subscription(String, "/robot_status", self.cb_st, 5, raw=True)
        self.create_subscription(String, "/motion/active_states", self.cb_stage, 5, raw=True)
        self.pub = self.create_publisher(String, state_topic, AQ)
        self.create_subscription(String, action_topic, self.on_action, AQ)
        self.create_timer(1.0 / max(1.0, rate_hz), self.tick)
        self.create_timer(10.0, self.report)
        self.get_logger().info(
            f"🛰️ Orin 采集节点启动: 订阅 {self.JOINTS_TOPIC} + force + gripper + status + stage | "
            f"发布 {state_topic} @{rate_hz}Hz | 接收 {action_topic} 仅记录 | 记录目录 {OUT_DIR}")

    # ── 回调: 只存原始字节 ──
    def cb_j(self, m):
        self._rj = m

    def cb_f(self, m):
        self._rf = m

    def cb_g(self, m):
        self._rg = m

    def cb_st(self, m):
        self._rst = m

    def cb_stage(self, m):
        self._rstage = m

    def _decode(self):
        try:
            if self._rj is not None:
                self.j = deserialize_message(bytes(self._rj), JointState)
            if self._rf is not None:
                self.f = deserialize_message(bytes(self._rf), WrenchStamped)
            if self._rg is not None:
                self.g = deserialize_message(bytes(self._rg), Float32)
            if self._rst is not None:
                self.st = deserialize_message(bytes(self._rst), String).data
            if self._rstage is not None:
                self.stage = deserialize_message(bytes(self._rstage), String).data
        except Exception:
            pass

    def tick(self):
        self._decode()
        if self.j is None:
            return
        pos = [float(x) for x in self.j.position]
        vel = [float(x) for x in self.j.velocity] if self.j.velocity else []
        t = time.time()
        if not vel and self.prev_pos is not None and self.prev_t:
            dt = max(1e-4, t - self.prev_t)
            vel = [(a - b) / dt for a, b in zip(pos, self.prev_pos)]
        self.prev_pos, self.prev_t = pos, t
        ft = None
        if self.f is not None:
            w = self.f.wrench
            ft = [round(w.force.x, 4), round(w.force.y, 4), round(w.force.z, 4),
                  round(w.torque.x, 4), round(w.torque.y, 4), round(w.torque.z, 4)]
        self.seq += 1
        st = {
            "t": round(t, 4), "seq": self.seq, "src": "orin_edge",
            "joints": [round(x, 5) for x in pos],
            "jvel": [round(x, 5) for x in vel[:6]] if vel else [],
            "gripper": round(float(self.g.data), 3) if self.g is not None else None,
            "ft": ft,
            "robot_state": self.st[:160],
            "prod_stage": self.stage[:60],
            "scope": "readonly",
        }
        m = String()
        m.data = json.dumps(st, ensure_ascii=False)
        self.pub.publish(m)
        self.n_pub += 1
        with self._lock:
            self.f_state.write(json.dumps(st, ensure_ascii=False) + "\n")
        if self.n_pub % 100 == 0:
            self.f_state.flush()

    def on_action(self, msg):
        """收到 4060 的动作提案 —— 只记录, 绝不执行"""
        self.n_act += 1
        self.last_act = msg.data[:400]
        with self._lock:
            self.f_action.write(msg.data.replace("\n", " ") + "\n")
        if self.n_act % 20 == 0:
            self.f_action.flush()
            self.get_logger().info(f"📥 收到 4060 提案 {self.n_act} 条 (只记录, 不下发) · 最新: {self.last_act[:160]}")

    def report(self):
        self.get_logger().info(
            f"🛰️ 上行 {self.n_pub} 帧 · 下行已记录 {self.n_act} 条 · 产线阶段={self.stage[:30] or '-'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-topic", default="/zmax_ss/state")
    ap.add_argument("--action-topic", default="/zmax_ss/action")
    ap.add_argument("--rate", type=float, default=20.0)
    a = ap.parse_args()
    os.environ.setdefault("ROS_DOMAIN_ID", "0")
    os.environ.setdefault("ZMAX_REPO_ROOT", "/home/tashan/zmax_state_space")
    rclpy.init()
    n = EdgeNode(a.state_topic, a.action_topic, a.rate)
    try:
        rclpy.spin(n)
    except KeyboardInterrupt:
        pass
    finally:
        n.get_logger().info(f"停止: 上行 {n.n_pub} · 下行记录 {n.n_act}")
        n.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
