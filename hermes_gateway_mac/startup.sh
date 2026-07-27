#!/bin/bash
# Hermes Gateway 开机启动

LOG="$HOME/hermes_gateway_startup.log"
echo "=== $(date) ===" >> "$LOG"

# 防休眠
caffeinate -d -i -m -s &
echo "✅ caffeinate 已启动" >> "$LOG"

# 激活虚拟环境
cd "$(dirname "$0")"
source venv/bin/activate 2>/dev/null || true

# 启动 Gateway (先不带Orin, 等现场手动连接或SSH配置)
python3 gateway_pure.py --port 8080 >> "$LOG" 2>&1 &

echo "✅ Gateway 已启动 (PID: $!)" >> "$LOG"
echo "启动完成" >> "$LOG"
