#!/bin/bash
# Z-MAX 状态空间工程 · Orin 旁路(影子)守护启动 — 幂等, 供 crontab @reboot 调用
# 老倪 2026-09-16 批准; 只读运行, 绝不发布控制量
LOG=/home/tashan/.zmax/ss_shadow.log
BASE=/home/tashan/zmax_state_space

if pgrep -f "[s]s_shadow.py" >/dev/null 2>&1; then
    echo "$(date '+%F %T') 已在运行 pid=$(pgrep -f '[s]s_shadow.py' | head -1), 跳过" >> "$LOG"
    exit 0
fi
if [ ! -f "$BASE/tools/ss_shadow.py" ]; then
    echo "$(date '+%F %T') 错误: 找不到 $BASE/tools/ss_shadow.py" >> "$LOG"
    exit 1
fi

cd "$BASE" || exit 1
setsid nohup bash /home/tashan/.zmax/start_ss_shadow.sh >> "$LOG" 2>&1 < /dev/null &
echo "$(date '+%F %T') 已启动 ss_shadow.py PID=$!" >> "$LOG"
sleep 6
if pgrep -f "[s]s_shadow.py" >/dev/null 2>&1; then
    echo "$(date '+%F %T') 状态: 运行中" >> "$LOG"
else
    echo "$(date '+%F %T') 警告: 启动后未发现进程, 见日志上文" >> "$LOG"
fi
