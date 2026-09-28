#!/usr/bin/env bash
# 实时检测常驻: 在役 YOLO 每 2s 跑一次当前臂上相机实帧 → 写叠加 det 层(与 vlm/meas 层并列, 互不覆盖)
# 正常时静默; 仅在前两次出错时打一行(老倪口径: 没请求不要刷屏)
set -u
cd /home/ubuntu/zmax_rel || exit 1
END=$(( $(date +%s) + ${1:-14400} ))
CONF="${2:-0.35}"
ERR=0
while [ "$(date +%s)" -lt "$END" ]; do
  out=$(timeout 25 ./gui-venv311/bin/python tools/gen_overlay_from_det.py --cam arm --conf "$CONF" 2>&1) || {
    ERR=$((ERR+1)); [ "$ERR" -le 2 ] && echo "[$(date +%H:%M:%S)] ⚠️ 检测失败($ERR): $(echo "$out" | tail -1 | cut -c1-110)"; }
  sleep 2
done
echo "[$(date +%H:%M:%S)] 实时检测壳退出(窗口到)"
