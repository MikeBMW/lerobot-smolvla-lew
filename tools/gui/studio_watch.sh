#!/bin/bash
# 🛡 2026-08-18 老倪: studio 崩溃自动重启守护
# 崩溃 (SIGSEGV 非 0 退出) → gdb 抓栈 → 5s 后自动重启; 正常退出 (0) → 结束
cd /root/lerobot-smolvla-lew/tools/gui || exit 1
export DISPLAY=host.docker.internal:0
# 🐛 2026-08-18: Python 3.11 环境 (PyQt5 5.15.10 + Qt 5.15.2 + sip 12.19 — 官方稳定组合;
#   3.12 + sip 6.16 的 timer NULL receiver 竞态 → 换 3.11 根治)
PY=/root/gui-venv311/bin/python
N=0
while true; do
  N=$((N + 1))
  echo "[$(date '+%F %T')] 第 ${N} 次启动 studio (gdb 监控, py311)" >> /tmp/studio_watch.log
  gdb -batch -x /tmp/gdb_cmds2.txt --args $PY studio.py >> /tmp/gdb_studio.log 2>&1
  RC=$?
  if [ "$RC" -eq 0 ]; then
    echo "[$(date '+%F %T')] 正常退出 (rc=0) — 守护结束" >> /tmp/studio_watch.log
    break
  fi
  echo "[$(date '+%F %T')] 崩溃 (rc=$RC) — 5s 后自动重启" >> /tmp/studio_watch.log
  sleep 5
done
