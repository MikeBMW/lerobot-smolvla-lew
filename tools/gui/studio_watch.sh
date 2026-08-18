#!/bin/bash
# 🛡 2026-08-18 老倪: studio 崩溃自动重启守护
# 崩溃 (SIGSEGV 非 0 退出) → gdb 抓栈 → 5s 后自动重启; 正常退出 (0) → 结束
cd /root/lerobot-smolvla-lew/tools/gui || exit 1
export DISPLAY=host.docker.internal:0
N=0
while true; do
  N=$((N + 1))
  echo "[$(date '+%F %T')] 第 ${N} 次启动 studio (gdb 监控)" >> /tmp/studio_watch.log
  gdb -batch -x /tmp/gdb_cmds2.txt --args /root/gui-venv/bin/python studio.py >> /tmp/gdb_studio.log 2>&1
  RC=$?
  if [ "$RC" -eq 0 ]; then
    echo "[$(date '+%F %T')] 正常退出 (rc=0) — 守护结束" >> /tmp/studio_watch.log
    break
  fi
  echo "[$(date '+%F %T')] 崩溃 (rc=$RC) — 5s 后自动重启" >> /tmp/studio_watch.log
  sleep 5
done
