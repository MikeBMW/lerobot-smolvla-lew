#!/usr/bin/env python3
"""
Orin Real-Robot Topic Forwarder — Domain 23, ALL topics → PC via TCP
======================================================================
Dynamically discovers and subscribes to EVERY topic on ROS_DOMAIN_ID=23.
Generic message serializer handles any ROS2 message type.
READ-ONLY: Subscriber only, never publishes.

Usage (on Orin):
    source /opt/ros/humble/setup.bash
    ROS_DOMAIN_ID=23 python3 orin_forwarder_domain23.py --port 9999
"""

import argparse
import json
import socket
import struct
import time
import sys
import importlib
from typing import Any

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy

# QoS: best-effort to avoid impacting real robot; volatile to not persist
QOS_PROFILE = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT,
                         durability=DurabilityPolicy.VOLATILE)

# Topics to throttle (only send every Nth message)
THROTTLE_PATTERNS = {
    "image": 3,        # was 10 — let more camera frames through
    "point": 5,        # was 20
    "camera_info": 3,  # was 10
    "tf": 2,           # was 5
}
# Topics to skip entirely (high-frequency / non-data)
SKIP_PATTERNS = ["parameter_events", "rosout", "/client_count"]

# Maximum serialized payload size (bytes) — drop oversized messages
MAX_PAYLOAD_BYTES = 2 * 1024 * 1024  # 2 MB


def _throttle_key(topic: str) -> int:
    """Return throttle interval for a topic, 1 = every message."""
    tl = topic.lower()
    for pat, n in THROTTLE_PATTERNS.items():
        if pat in tl:
            return n
    return 1


def message_to_dict(msg) -> dict:
    """Convert any ROS2 message to a JSON-serializable dict (best-effort)."""
    result = {}
    # Try get_fields_and_field_types (standard for most ROS2 msgs)
    if hasattr(msg, "get_fields_and_field_types"):
        try:
            fields = msg.get_fields_and_field_types()
            for field_name in fields:
                val = getattr(msg, field_name, None)
                result[field_name] = _serialize_value(val)
            return result
        except Exception:
            pass

    # Fallback: iterate __slots__
    if hasattr(msg, "__slots__"):
        for slot in msg.__slots__:
            val = getattr(msg, slot, None)
            result[slot] = _serialize_value(val)
        return result

    # Last resort: str()
    return {"_raw": str(msg)}


def _serialize_value(val: Any) -> Any:
    """Recursively serialize a ROS2 message field value."""
    if val is None:
        return None
    if isinstance(val, (bool, int, float, str)):
        return val
    if isinstance(val, (list, tuple)):
        # Truncate long arrays (e.g. image data, point clouds)
        if len(val) > 200:
            return [val[0], val[1], val[2], f"...({len(val)} total)"]
        return [_serialize_value(v) for v in val[:50]]
    if isinstance(val, bytes):
        return f"<bytes:{len(val)}>"
    if hasattr(val, "get_fields_and_field_types"):
        return message_to_dict(val)
    # Nested message with __slots__
    if hasattr(val, "__slots__"):
        d = {}
        for s in val.__slots__:
            d[s] = _serialize_value(getattr(val, s, None))
        return d
    return str(val)[:200]


class DynamicTopicForwarder(Node):
    """Discover all topics on the domain, subscribe, forward via TCP."""

    def __init__(self, port: int = 9999):
        super().__init__("tcp_forwarder_domain23")
        self._port = port
        self._conn: socket.socket | None = None
        self._server: socket.socket | None = None
        self._seq = 0
        self._throttle_counters: dict[str, int] = {}
        self._total_sent = 0
        self._total_dropped = 0

        self._setup_server()
        self._discover_and_subscribe()
        self._print_stats_timer = self.create_timer(30, self._print_stats)

    def _setup_server(self):
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("0.0.0.0", self._port))
        self._server.listen(1)
        self._server.setblocking(False)
        self.get_logger().info(f"TCP server on :{self._port}")

    def _discover_and_subscribe(self):
        """Discover all topics and subscribe dynamically."""
        topic_names_and_types = self.get_topic_names_and_types()
        subscribed = 0
        skipped = 0

        for tname, ttypes in topic_names_and_types:
            # Skip internal topics
            if any(p in tname for p in SKIP_PATTERNS):
                skipped += 1
                continue

            if not ttypes:
                continue

            # Get full message type (e.g. "sensor_msgs/msg/Image")
            full_type = ttypes[0]
            try:
                msg_cls = self._import_message_type(full_type)
            except Exception:
                self.get_logger().warn(f"  SKIP {tname}: cannot import {full_type}")
                skipped += 1
                continue

            self.create_subscription(
                msg_cls, tname,
                self._make_callback(tname, full_type, msg_cls),
                QOS_PROFILE,
            )
            self.get_logger().info(f"  SUB  {tname} [{full_type}]")
            self._throttle_counters[tname] = 0
            subscribed += 1

        self.get_logger().info(
            f"Discovery complete: {subscribed} subscribed, {skipped} skipped"
        )

    @staticmethod
    def _import_message_type(full_type: str):
        """Dynamically import a ROS2 message class from 'pkg/msg/Type' string."""
        parts = full_type.split("/")
        if len(parts) != 3:
            raise ValueError(f"Invalid type: {full_type}")
        pkg, sub, name = parts
        module_path = f"{pkg}.{sub}"
        mod = importlib.import_module(module_path)
        return getattr(mod, name)

    def _make_callback(self, tname: str, full_type: str, msg_cls: type):
        throttle_n = _throttle_key(tname)

        def callback(msg):
            self._seq += 1
            self._throttle_counters[tname] += 1

            if throttle_n > 1 and self._throttle_counters[tname] % throttle_n != 0:
                self._total_dropped += 1
                return

            try:
                payload = {
                    "topic": tname,
                    "type": full_type,
                    "seq": self._seq,
                    "ts": time.time(),
                    "msg": message_to_dict(msg),
                }
            except Exception:
                return

            self._send(payload)

        return callback

    def _send(self, msg: dict):
        if self._conn is None and self._server is not None:
            try:
                self._conn, addr = self._server.accept()
                self.get_logger().info(f"PC connected from {addr}")
            except BlockingIOError:
                return

        try:
            data = json.dumps(msg, ensure_ascii=False).encode()
            if len(data) > MAX_PAYLOAD_BYTES:
                self._total_dropped += 1
                return
            if self._conn is not None:
                self._conn.sendall(struct.pack("!I", len(data)) + data)
                self._total_sent += 1
        except (BrokenPipeError, ConnectionResetError, OSError):
            self.get_logger().warn("PC disconnected, waiting...")
            self._conn = None

    def _print_stats(self):
        self.get_logger().info(
            f"Stats: {self._total_sent} sent, {self._total_dropped} dropped (throttled)"
        )


def main():
    parser = argparse.ArgumentParser(description="Domain 23 Real-Robot Forwarder")
    parser.add_argument("--port", type=int, default=9999, help="TCP listen port")
    args = parser.parse_args()

    rclpy.init()
    node = DynamicTopicForwarder(port=args.port)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
