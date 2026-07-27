#!/usr/bin/env python3
"""
Orin Topic Forwarder — Read-Only ROS2 → TCP Bridge
===================================================
Runs on Jetson Orin. Subscribes to specified ROS2 topics (READ-ONLY)
and streams data to PC over TCP. Never publishes — cannot affect hardware.

Usage:
    python3 orin_forwarder.py [--port 9999] [--topics /arm/joint_state,/camera/rgb/compressed]

Environment:
    source /opt/ros/humble/setup.bash
    export ROS_DOMAIN_ID=42
"""

import argparse
import json
import base64
import socket
import struct
import time
import sys
import traceback
from typing import Any

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32MultiArray
from sensor_msgs.msg import CompressedImage

# ── Topic type registry (extend as needed) ──
TOPIC_TYPES = {
    "std_msgs/msg/Float32MultiArray": Float32MultiArray,
    "sensor_msgs/msg/CompressedImage": CompressedImage,
}

# How to serialize each message type
def serialize_float32multiarray(msg: Float32MultiArray) -> dict:
    return {"data": [round(v, 5) for v in msg.data]}

def serialize_compressedimage(msg: CompressedImage) -> dict:
    return {
        "format": msg.format,
        "data_b64": base64.b64encode(msg.data).decode(),
        "size": len(msg.data),
    }

SERIALIZERS = {
    Float32MultiArray: serialize_float32multiarray,
    CompressedImage: serialize_compressedimage,
}


class TopicForwarder(Node):
    """Subscribe to ROS2 topics and forward to TCP clients."""

    def __init__(self, port: int = 9999, throttle_images: int = 10):
        super().__init__("tcp_topic_forwarder")
        self._port = port
        self._throttle_images = throttle_images
        self._seq = 0
        self._conn: socket.socket | None = None
        self._server: socket.socket | None = None
        self._subs = []

        self._setup_server()
        self._subscribe_all()
        self.get_logger().info(f"Forwarder ready on :{port} — {len(self._subs)} topic(s)")

    def _setup_server(self):
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("0.0.0.0", self._port))
        self._server.listen(1)
        self._server.setblocking(False)
        self.get_logger().info(f"TCP server listening on :{self._port}")

    def _subscribe_all(self):
        """Subscribe to all known ROS2 data topics."""
        topic_list = [
            ("/arm/joint_state", Float32MultiArray),
            ("/camera/rgb/compressed", CompressedImage),
        ]
        for tname, ttype in topic_list:
            sub = self.create_subscription(ttype, tname, self._make_callback(tname, ttype), 10)
            self._subs.append((tname, sub))
            self.get_logger().info(f"  Subscribed: {tname} ({ttype.__name__})")

    def _make_callback(self, tname: str, ttype: type):
        serializer = SERIALIZERS.get(ttype, lambda m: {"raw": str(m)})

        def callback(msg):
            self._seq += 1

            # Throttle images to save bandwidth
            if ttype is CompressedImage and self._seq % self._throttle_images != 0:
                return

            payload = {
                "topic": tname,
                "type": ttype.__name__,
                "seq": self._seq,
                "ts": time.time(),
                **serializer(msg),
            }
            self._send(payload)

        return callback

    def _send(self, msg: dict):
        """Send JSON message to connected PC, accept new connection if needed."""
        # Try accept
        if self._conn is None and self._server is not None:
            try:
                self._conn, addr = self._server.accept()
                self.get_logger().info(f"PC connected from {addr}")
            except BlockingIOError:
                return

        try:
            data = json.dumps(msg, ensure_ascii=False).encode()
            if self._conn is not None:
                self._conn.sendall(struct.pack("!I", len(data)) + data)
        except (BrokenPipeError, ConnectionResetError, OSError):
            self.get_logger().warn("PC disconnected, waiting for reconnect...")
            self._conn = None


def main():
    parser = argparse.ArgumentParser(description="Orin ROS2 → TCP Topic Forwarder")
    parser.add_argument("--port", type=int, default=9999, help="TCP listen port")
    parser.add_argument("--throttle-images", type=int, default=10,
                        help="Only send every Nth image (default: 10)")
    args = parser.parse_args()

    rclpy.init()
    node = TopicForwarder(port=args.port, throttle_images=args.throttle_images)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
