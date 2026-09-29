#!/bin/bash
# 🎯 无人值守逐 epoch 判闸: 每个 ckpt 一落盘 → 立刻用原项目评法(离线回放)评一次
#   CPU 推理 (不抢训练的 5.8GB 显存), 结果追加到 /tmp/intact_gate.log
#   判据: 必须显著赢"常数基线(教师均值)"; v1 失败口径 = 模型 xyz MAE 0.092 > 常数 0.086
set -u
LOG=/tmp/intact_gate.log
CK=/home/ubuntu/stable-wm-cache/checkpoints/intact_goal_zmax_v2_s3072
cd /home/ubuntu/lerobot-smolvla-lew || exit 1
export HDF5_PLUGIN_PATH=/home/ubuntu/.h5plugins
export STABLEWM_HOME=/home/ubuntu/stable-wm-cache
export LOCAL_DATASET_DIR=/home/ubuntu/stable-wm-cache
export HF_ENDPOINT=https://hf-mirror.com
export INTACT_RUNTIME=root
echo "=== 判闸守护启动 $(date '+%F %T') ===" >> "$LOG"
while pgrep -f 'config-name intact_goal_zmax' > /dev/null; do
  for f in "$CK"/weights_epoch_*.pt; do
    [ -e "$f" ] || continue
    tag=$(basename "$f" .pt)
    if grep -q "GATED $tag" "$LOG" 2>/dev/null; then continue; fi
    echo "--- $tag $(date '+%H:%M:%S') ---" >> "$LOG"
    INTACT_POLICY="$CK/$(basename "$f")" \
      timeout 1800 /home/ubuntu/INTACT-JEPA/.venv/bin/python tools/intact_replay_check.py \
      --n 60 --stride 300 --device cpu --out "reports/intact_replay_${tag}.json" \
      >> "$LOG" 2>&1
    echo "GATED $tag" >> "$LOG"
  done
  sleep 30
done
# 训练结束后把剩余 ckpt 补评一遍
for f in "$CK"/weights_epoch_*.pt; do
  [ -e "$f" ] || continue
  tag=$(basename "$f" .pt)
  grep -q "GATED $tag" "$LOG" 2>/dev/null && continue
  echo "--- $tag (补评) $(date '+%H:%M:%S') ---" >> "$LOG"
  INTACT_POLICY="$CK/$(basename "$f")" \
    timeout 1800 /home/ubuntu/INTACT-JEPA/.venv/bin/python tools/intact_replay_check.py \
    --n 60 --stride 300 --device cpu --out "reports/intact_replay_${tag}.json" >> "$LOG" 2>&1
  echo "GATED $tag" >> "$LOG"
done
echo "=== 判闸守护结束 $(date '+%F %T') ===" >> "$LOG"
