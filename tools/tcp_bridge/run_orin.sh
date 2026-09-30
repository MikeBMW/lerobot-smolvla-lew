#!/bin/bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Orin Topic Forwarder — 启动脚本
# 在 Jetson Orin 上运行，只读订阅 ROS2 topic，TCP 转发给 PC
# 安全：仅 Subscriber，不发布任何指令
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

source /opt/ros/humble/setup.bash
export ROS_DOMAIN_ID=42

echo "🚀 启动 Orin Topic Forwarder (只读)..."
echo "   TCP 端口: ${PORT:-9999}"
echo "   图片抽帧率: 每 ${THROTTLE:-10} 帧发1帧"

python3 -u orin_forwarder.py \
    --port "${PORT:-9999}" \
    --throttle-images "${THROTTLE:-10}"
