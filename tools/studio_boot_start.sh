#!/usr/bin/env bash
# studio_boot_start.sh — 开机后拉起 XSpace Studio 并盯 60s 存活 (避免"启动了又没了")
set -u
REPO=/home/ubuntu/lerobot-smolvla-lew
cd "$REPO/tools/gui" || exit 1
LOG=/tmp/studio_launch.log
export DISPLAY=:0
if pgrep -f "[g]ui-venv311/bin/python studio.py" >/dev/null 2>&1; then
  echo "already running: $(pgrep -f '[g]ui-venv311/bin/python studio.py' | tr '\n' ' ')"
  exit 0
fi
: > "$LOG"
setsid nice -n 10 "$REPO/gui-venv311/bin/python" studio.py >> "$LOG" 2>&1 < /dev/null &
for i in $(seq 1 12); do
  sleep 5
  if ! pgrep -f "[g]ui-venv311/bin/python studio.py" >/dev/null 2>&1; then
    echo "❌ 第 ${i} 次检查 (${i}x5s): 进程已退出"
    echo "--- 日志尾 40 行 ---"
    tail -40 "$LOG"
    exit 3
  fi
done
PID=$(pgrep -f "[g]ui-venv311/bin/python studio.py" | head -1)
echo "✅ 存活 60s · pid=$PID · rss=$(awk '/VmRSS/{print $2/1024" MB"}' /proc/$PID/status 2>/dev/null)"
echo "--- 日志尾 6 行 ---"; tail -6 "$LOG"
