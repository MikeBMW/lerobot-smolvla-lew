#!/bin/bash
# XSpace Studio 控制台快捷启动 (桌面图标点击调用)
# 硬编码 gui-venv311 的 Python, 不依赖 run_studio.sh 的自动探测
GUI_DIR="/home/ubuntu/lerobot-smolvla-lew/tools/gui"
VENV_PY="/home/ubuntu/lerobot-smolvla-lew/gui-venv311/bin/python"
LOG="/tmp/studio_launch.log"

# 本机 Xorg 显示 (桌面会话一般已设, 兜底 :0)
export DISPLAY="${DISPLAY:-:0}"

# 已有实例在跑 → 激活已有窗口, 不重复启动
if pgrep -f "[g]ui-venv311/bin/python studio.py" >/dev/null 2>&1; then
    WIN=$(DISPLAY="$DISPLAY" xdotool search --onlyvisible --name "XSpace Studio" 2>/dev/null | head -1)
    if [ -n "$WIN" ]; then
        DISPLAY="$DISPLAY" xdotool windowactivate "$WIN" 2>/dev/null
    fi
    exit 0
fi

cd "$GUI_DIR" || exit 1
exec nice -n 10 "$VENV_PY" studio.py >> "$LOG" 2>&1
