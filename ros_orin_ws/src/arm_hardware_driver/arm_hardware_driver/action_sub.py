#!/usr/bin/env python3
"""
Jetson Orin action subscriber / motor executor node.

Subscribes to /arm/target_action from PC bridge,
parses the Float32MultiArray into joint targets,
and drives the physical servo motors.

Hardware: Dynamixel/CAN bus servos via Jetson UART.
On non-Jetson (dev/test): logs received actions.
"""

import numpy as np

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32MultiArray


class ActionSubscriber(Node):
    """Subscribe to action commands and execute on hardware."""

    def __init__(self):
        super().__init__("action_subscriber")

        self.declare_parameter("num_joints", 6)
        self.declare_parameter("use_dummy", True)

        self.num_joints = self.get_parameter("num_joints").value
        self.use_dummy = self.get_parameter("use_dummy").value

        self.create_subscription(
            Float32MultiArray,
            "/arm/target_action",
            self._action_callback,
            5,
        )

        self._action_count = 0
        self.get_logger().info(
            f"Action subscriber started: {self.num_joints} joints "
            f"({'dummy/log-only' if self.use_dummy else 'hardware'})"
        )

    def _execute_hardware(self, targets: np.ndarray):
        """Drive physical servo motors (placeholder)."""
        # TODO: Implement Dynamixel/CAN bus motor control
        # e.g., write position goals via dynamixel_sdk
        pass

    def _action_callback(self, msg: Float32MultiArray):
        targets = np.array(msg.data, dtype=np.float32)

        if self.use_dummy:
            self._action_count += 1
            if self._action_count % 50 == 0:
                self.get_logger().info(
                    f"Received action #{self._action_count}: "
                    f"shape=({len(targets)},) "
                    f"range=[{targets.min():.3f}, {targets.max():.3f}]"
                )
        else:
            self._execute_hardware(targets)


def main(args=None):
    rclpy.init(args=args)
    node = ActionSubscriber()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
