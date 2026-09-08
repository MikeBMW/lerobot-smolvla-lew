#!/bin/bash
# gdb 监控 studio.py — SIGSEGV 崩溃时自动抓栈 (2026-08-18)
# 用法: bash 本脚本 (后台跑), 让用户在 GUI 里复现崩溃, 然后读 /tmp/gdb_crash.log
# 输出: C 栈 (bt 30) + info threads — 定位 QObject::killTimer / 线程竞争类 Segfault
cd /root/lerobot-smolvla-lew/tools/gui
export DISPLAY=host.docker.internal:0
gdb -batch \
  -ex "set pagination off" \
  -ex "handle SIGSEGV stop print" \
  -ex "run" \
  -ex "printf \"\n===== CRASH BACKTRACE =====\n\"" \
  -ex "bt 30" \
  -ex "info threads" \
  --args /root/gui-venv/bin/python studio.py > /tmp/gdb_crash.log 2>&1
echo "gdb exit: $?" >> /tmp/gdb_crash.log
