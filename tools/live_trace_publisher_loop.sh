#!/usr/bin/env bash
# 轨迹发布器常驻: 它本体是"跑一次就退"(实测 exit 0), 所以用这个薄壳每 2s 重发布一次,
# 让 trace 层(黄=真机 TCP 实测轨迹) 随臂移动实时生长。正常时静默, 仅在出错时打一行。
set -u
cd /home/ubuntu/zmax || exit 1
END=$(( $(date +%s) + ${1:-14400} ))
ERR=0
while [ "$(date +%s)" -lt "$END" ]; do
  out=$(timeout 20 ./gui-venv311/bin/python tools/live_trace_publisher.py 2>&1) || {
    ERR=$((ERR+1)); [ "$ERR" -le 2 ] && echo "[$(date +%H:%M:%S)] ⚠️ 发布失败($ERR): $(echo "$out" | tail -1 | cut -c1-110)"; }
  sleep 2
done
echo "[$(date +%H:%M:%S)] 轨迹发布壳退出(窗口到)"
