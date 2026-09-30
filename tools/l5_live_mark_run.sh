#!/bin/bash
# L5 实时标注器常驻启动器 —— 崩了自动重起 (单实例, 由 pidfile 守护)
# 用法: tools/l5_live_mark_run.sh [额外参数...]
set -u
REPO=/home/ubuntu/zmax
OUT=/home/ubuntu/zmax_data/l5live
mkdir -p "$OUT"
cd "$REPO" || exit 1
exec >>"$OUT/l5_live_mark.out" 2>&1
echo "=== $(date '+%F %T') supervisor start pid=$$ ==="
while true; do
  ./gui-venv311/bin/python tools/l5_live_mark.py \
      --http http://192.168.23.66:8792/frame.jpg \
      --fallback http://127.0.0.1:8791/snapshot/arm.jpg \
      --hz 5 --conf 0.20 "$@"
  rc=$?
  echo "=== $(date '+%F %T') marker exit rc=$rc, 2s 后重起 ==="
  sleep 2
done
