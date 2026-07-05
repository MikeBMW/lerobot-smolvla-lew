#!/bin/bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PC Topic Receiver — 启动脚本
# 连接 Orin Forwarder，接收并显示 topic 数据
# 无需 ROS2，纯 Python3
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

HOST="${HOST:-192.168.23.10}"
PORT="${PORT:-9999}"

echo "📡 连接 Orin Topic Forwarder..."
echo "   Orin: ${HOST}:${PORT}"
echo "   Ctrl+C 停止"

python3 -u pc_receiver.py \
    --host "$HOST" \
    --port "$PORT" \
    "$@"
