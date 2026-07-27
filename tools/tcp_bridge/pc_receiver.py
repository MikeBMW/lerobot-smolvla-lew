#!/usr/bin/env python3
"""
PC Topic Receiver — TCP Client for Orin Topic Forwarder
========================================================
Connects to Orin's TCP forwarder, receives topic data stream,
and displays/logs it. Supports JSON log output and real-time display.

Usage:
    python3 pc_receiver.py [--host 192.168.23.10] [--port 9999] [--log data.jsonl]

No ROS2 required on PC side — pure Python 3 stdlib.
"""

import argparse
import json
import socket
import struct
import sys
import time
import base64
from datetime import datetime


class TopicReceiver:
    """Connect to Orin forwarder, receive and display topic data."""

    def __init__(self, host: str = "192.168.23.10", port: int = 9999,
                 log_file: str | None = None, quiet: bool = False):
        self.host = host
        self.port = port
        self.quiet = quiet
        self.sock: socket.socket | None = None
        self._log_fh = open(log_file, "a", encoding="utf-8") if log_file else None
        self._counts: dict[str, int] = {}
        self._start_time = time.time()

    def connect(self):
        print(f"Connecting to Orin at {self.host}:{self.port}...", file=sys.stderr)
        while True:
            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.settimeout(5)
                self.sock.connect((self.host, self.port))
                print(f"Connected to {self.host}:{self.port}", file=sys.stderr)
                return
            except (ConnectionRefusedError, socket.timeout, OSError) as e:
                print(f"  Waiting for Orin... ({e})", file=sys.stderr)
                time.sleep(2)
                self.sock = None

    def receive_loop(self):
        self.connect()
        print(f"{'─'*60}", file=sys.stderr)
        print(f"Receiving data... (Ctrl+C to stop)", file=sys.stderr)
        print(f"{'─'*60}", file=sys.stderr)

        while True:
            try:
                # Read 4-byte length prefix
                raw = self.sock.recv(4)
                if not raw:
                    raise ConnectionError("Connection closed")
                length = struct.unpack("!I", raw)[0]

                # Read payload
                data = b""
                while len(data) < length:
                    chunk = self.sock.recv(length - len(data))
                    if not chunk:
                        raise ConnectionError("Connection broken")
                    data += chunk

                msg = json.loads(data)
                self._handle(msg)

            except (ConnectionError, BrokenPipeError, ConnectionResetError, socket.timeout):
                print(f"\nConnection lost, reconnecting...", file=sys.stderr)
                self.sock = None
                self.connect()
            except KeyboardInterrupt:
                break

    def _handle(self, msg: dict):
        topic = msg.get("topic", "?")
        self._counts[topic] = self._counts.get(topic, 0) + 1

        if self._log_fh:
            self._log_fh.write(json.dumps(msg, ensure_ascii=False) + "\n")

        if self.quiet:
            return

        ttype = msg.get("type", "?")
        seq = msg.get("seq", 0)

        if ttype == "CompressedImage":
            size = msg.get("size", 0)
            print(f"[IMG  #{seq:5d}] {size:>6d} bytes JPEG")
        elif ttype == "Float32MultiArray":
            data = msg.get("data", [])
            vals = ",".join(f"{v:+.4f}" for v in data)
            print(f"[JOINT #{seq:5d}] [{vals}]")
        else:
            print(f"[{topic} #{seq}] {msg}")

    def stats(self):
        elapsed = time.time() - self._start_time
        total = sum(self._counts.values())
        rate = total / elapsed if elapsed > 0 else 0
        print(f"\n{'═'*60}")
        print(f"  Session: {elapsed:.1f}s | {total} msgs | {rate:.0f} msg/s")
        for topic, count in sorted(self._counts.items()):
            print(f"  {topic}: {count}")
        print(f"{'═'*60}")

    def close(self):
        self.stats()
        if self.sock:
            self.sock.close()
        if self._log_fh:
            self._log_fh.close()


def main():
    parser = argparse.ArgumentParser(description="PC TCP Receiver for Orin Topic Forwarder")
    parser.add_argument("--host", default="192.168.23.10", help="Orin IP address")
    parser.add_argument("--port", type=int, default=9999, help="TCP port")
    parser.add_argument("--log", default=None, help="Save received data to JSONL file")
    parser.add_argument("--quiet", action="store_true", help="Suppress display, only log")
    args = parser.parse_args()

    rx = TopicReceiver(host=args.host, port=args.port,
                       log_file=args.log, quiet=args.quiet)
    try:
        rx.receive_loop()
    except KeyboardInterrupt:
        pass
    finally:
        rx.close()


if __name__ == "__main__":
    main()
