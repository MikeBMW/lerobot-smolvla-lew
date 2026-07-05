#!/usr/bin/env python3
"""
Jetson Orin joint state publisher node.

Reads arm encoder values and publishes joint positions
to /arm/joint_state as Float32MultiArray.

Hardware: Dynamixel/CAN bus servos via Jetson UART.
On non-Jetson (dev/test): generates sinusoidal dummy values.
"""

import math
import time
import numpy as np

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32MultiArray


class JointStatePublisher(Node):
    """Publish joint encoder readings from hardware servos."""

    def __init__(self):
        super().__init__("joint_state_publisher")

        self.declare_parameter("num_joints", 6)
        self.declare_parameter("publish_hz", 50.0)
        self.declare_parameter("use_dummy", True)
        self.declare_parameter("dummy_amplitude", 0.5)
        self.declare_parameter("dummy_frequency", 0.2)

        self.num_joints = self.get_parameter("num_joints").value
        publish_hz = self.get_parameter("publish_hz").value
        self.use_dummy = self.get_parameter("use_dummy").value
        self.dummy_amplitude = self.get_parameter("dummy_amplitude").value
        self.dummy_frequency = self.get_parameter("dummy_frequency").value

        self.pub = self.create_publisher(
            Float32MultiArray, "/arm/joint_state", 10
        )

        self._start_time = time.time()
        self.timer = self.create_timer(1.0 / publish_hz, self._publish_loop)

        mode = "dummy sinusoidal" if self.use_dummy else "hardware encoders"
        self.get_logger().info(
            f"Joint state publisher started: {self.num_joints} joints ({mode})"
        )

    def _read_hardware(self) -> list[float]:
        """Read joint positions from real hardware (placeholder)."""
        # TODO: Implement Dynamixel/CAN bus reading
        # e.g., via dynamixel_sdk or pymodbus
        return [0.0] * self.num_joints

    def _generate_dummy(self) -> list[float]:
        """Generate sinusoidal joint positions for testing."""
        elapsed = time.time() - self._start_time
        positions = []
        for i in range(self.num_joints):
            phase = 2 * math.pi * i / self.num_joints
            pos = self.dummy_amplitude * math.sin(
                2 * math.pi * self.dummy_frequency * elapsed + phase
            )
            positions.append(pos)
        return positions

    def _publish_loop(self):
        if self.use_dummy:
            positions = self._generate_dummy()
        else:
            positions = self._read_hardware()

        msg = Float32MultiArray()
        msg.data = positions
        self.pub.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = JointStatePublisher()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
