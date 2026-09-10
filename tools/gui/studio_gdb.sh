#!/bin/bash
# studio 崩溃自动抓栈 (2026-08-19 静静: Segfault 在 C/Qt 层, faulthandler 只有 Python 栈
# → gdb batch 模式: 崩溃瞬间 thread apply all bt full 落日志)
# 用法: bash studio_gdb.sh   (代替直接启动; 崩溃后日志 /tmp/studio_gdb_<时间>.log)
cd /root/lerobot-smolvla-lew/tools/gui
ulimit -c unlimited
LOG=/tmp/studio_gdb_$(date +%H%M%S).log
echo "gdb 包裹启动, 日志: $LOG"
gdb -batch \
  -ex "set pagination off" \
  -ex "handle SIGSEGV stop print" \
  -ex "run" \
  -ex "printf '\n===== CRASH STACK =====\n'" \
  -ex "thread apply all bt full" \
  --args /root/gui-venv311/bin/python studio.py 2>&1 | tee "$LOG"
echo "退出码 $? — 若崩溃, 完整栈在 $LOG"
