#!/bin/bash
# Hermes Gateway — 一键启动 (Mac M1)
#
# 用法:
#   chmod +x launch.sh
#   ./launch.sh
#
# 启动后:
#   ROS2 Gateway Node (后台)
#   HTTP API Server (前台 :8080)

set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
echo "🟢 Hermes Gateway Launcher"
echo "   目录: $DIR"
echo ""

# 1. 检查ROS2
if ! command -v ros2 &>/dev/null; then
    echo "❌ 未找到 ROS2。请先 source /opt/ros/humble/setup.bash"
    echo "   或 brew install ros-humble-desktop"
    exit 1
fi
echo "✅ ROS2: $(ros2 --version)"

# 2. 安装Python依赖
echo ""
echo "📦 安装Python依赖..."
pip3 install -q -r "$DIR/requirements.txt" 2>/dev/null || pip install -q -r "$DIR/requirements.txt"
echo "✅ 依赖就绪"

# 3. 启动ROS2节点（后台）
echo ""
echo "🚀 启动 ROS2 Gateway Node..."
python3 "$DIR/gateway_node.py" &
GATEWAY_PID=$!
sleep 2

if kill -0 $GATEWAY_PID 2>/dev/null; then
    echo "✅ ROS2 Gateway PID: $GATEWAY_PID"
else
    echo "❌ 启动失败"
    exit 1
fi

# 4. 启动HTTP API（前台）
echo ""
echo "🌐 启动 HTTP API Server..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
python3 -c "
import sys; sys.path.insert(0, '$DIR')
from gateway_node import HermesGatewayNode
from api_server import set_gateway_node
import rclpy
rclpy.init()
node = HermesGatewayNode()
set_gateway_node(node)

import threading
def spin_ros():
    rclpy.spin(node)
t = threading.Thread(target=spin_ros, daemon=True)
t.start()

from api_server import start_api
start_api()
"

# 清理
kill $GATEWAY_PID 2>/dev/null
echo "🛑 Gateway 已停止"
