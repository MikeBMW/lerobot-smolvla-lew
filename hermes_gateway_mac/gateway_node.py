#!/usr/bin/env python3
"""
Hermes Gateway — ROS2 分身节点 (Mac M1)

功能:
- 订阅Orin ROS2话题 (/joint_states, /gripper_pos, /hmi/events)
- 提供HTTP API供Hermes本体查询和控制
- 支持WebSocket实时推送

用法:
    python3 gateway_node.py
    然后在另一个终端: python3 api_server.py
    或一键: bash launch.sh
"""

import rclpy
import json
import time
import threading
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import Float64, String


class HermesGatewayNode(Node):
    """Hermes分身 — ROS2网关节点"""

    def __init__(self):
        super().__init__('hermes_gateway')

        # ── 状态缓存 ──
        self._lock = threading.Lock()
        self.state = {
            "joint_states": None,
            "gripper_pos": None,
            "hmi_events": [],
            "last_update": 0.0,
        }

        # ── 订阅Orin话题 ──
        self.create_subscription(
            JointState, '/real_joint_states', self._on_joint_states, 10)
        self.create_subscription(
            Float64, '/gripper_pos', self._on_gripper_pos, 10)
        self.create_subscription(
            String, '/hmi/events', self._on_hmi_event, 10)

        # ── 发布指令话题 ──
        self.cmd_pub = self.create_publisher(String, '/hermes_cmd', 10)
        self.cmd_vel_pub = self.create_publisher(JointState, '/hermes_target_pose', 10)

        self.get_logger().info("🟢 Hermes Gateway 就绪")

    # ── 订阅回调 ──

    def _on_joint_states(self, msg: JointState):
        with self._lock:
            self.state["joint_states"] = {
                "names": list(msg.name),
                "positions": list(msg.position),
                "velocities": list(msg.velocity) if msg.velocity else [],
            }
            self.state["last_update"] = time.time()

    def _on_gripper_pos(self, msg: Float64):
        with self._lock:
            self.state["gripper_pos"] = msg.data
            self.state["last_update"] = time.time()

    def _on_hmi_event(self, msg: String):
        with self._lock:
            self.state["hmi_events"].append({
                "timestamp": time.time(),
                "data": msg.data,
            })
            # 只保留最近100条
            if len(self.state["hmi_events"]) > 100:
                self.state["hmi_events"] = self.state["hmi_events"][-50:]

    # ── 状态查询 ──

    def get_state(self) -> dict:
        """获取完整状态快照"""
        with self._lock:
            s = dict(self.state)
            s["hmi_count"] = len(s["hmi_events"])
            s["hmi_events"] = s["hmi_events"][-10:]  # 只返回最近10条
            return s

    def get_joint_positions(self) -> dict | None:
        with self._lock:
            if self.state["joint_states"]:
                return dict(zip(
                    self.state["joint_states"]["names"],
                    self.state["joint_states"]["positions"]
                ))
            return None

    def get_gripper(self) -> float | None:
        with self._lock:
            return self.state["gripper_pos"]

    # ── 指令发送 ──

    def publish_cmd(self, command: str):
        """发布HMI指令"""
        msg = String()
        msg.data = command
        self.cmd_pub.publish(msg)
        self.get_logger().info(f"📤 指令: {command}")

    def publish_target_pose(self, joint_names: list, positions: list):
        """发布目标关节位姿"""
        msg = JointState()
        msg.name = joint_names
        msg.position = positions
        self.cmd_vel_pub.publish(msg)
        self.get_logger().info(f"📤 目标位姿: {dict(zip(joint_names, positions))}")


def main():
    rclpy.init()
    node = HermesGatewayNode()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
