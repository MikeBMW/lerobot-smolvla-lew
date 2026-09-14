#!/bin/bash
# 🧠⚡ v6 快速接力 (2026-09-14 老倪: "训练减少到半小时以内" → "10分钟以内" → "只要一个epoch")
#   每轮严格保持约定口径: **1 epoch × 1000 步 ≈ 8.5 分钟**; 从上一轮最后权重续 (不零化记忆通道);
#   每轮一个独立目录名 (v6r7..v6r11) → 判闸哨兵自动认最新目录, 每轮出一次 on/zero 数。
#   目的: 在"单次 ≤10 分钟"的约束下累积趋势 (每轮看到的都是随机子集: loader shuffle=True)。
set -u
CACHE=/home/ubuntu/stable-wm-cache/checkpoints
ROOT=/home/ubuntu/lerobot-smolvla-lew
LOG=$ROOT/reports/v6_fast_chain.log
cd /home/ubuntu/INTACT-JEPA || exit 1
PREV=intact_goal_optical_insert_v6r6_s3072
for k in $(seq 7 11); do
  NAME=intact_goal_optical_insert_v6r${k}_s3072
  INIT=$CACHE/$PREV/weights_epoch_1.pt
  if [ ! -f "$INIT" ]; then echo "[$(date +%H:%M:%S)] ❌ 缺初始权重 $INIT → 停链" | tee -a "$LOG"; break; fi
  echo "[$(date +%H:%M:%S)] ▶ $NAME 从 $PREV 续 (1 epoch × 1000 步)" | tee -a "$LOG"
  PATH=/home/ubuntu/INTACT-JEPA/.venv/bin:$PATH \
  STABLEWM_HOME=/home/ubuntu/stable-wm-cache LOCAL_DATASET_DIR=/home/ubuntu/stable-wm-cache \
  nice -n 5 ./.venv/bin/python train.py --config-name=intact_goal_optical_insert_v6 \
      output_model_name="$NAME" init_weights_path="$INIT" init_zero_skill_branch=false \
      trainer.max_epochs=1 +trainer.limit_train_batches=1000 2>&1 | tee -a "$LOG"
  W=$CACHE/$NAME/weights_epoch_1.pt
  if [ ! -f "$W" ]; then echo "[$(date +%H:%M:%S)] ❌ $NAME 没产出权重 → 停链" | tee -a "$LOG"; break; fi
  echo "[$(date +%H:%M:%S)] ✅ $NAME 完成: $(stat -c %s "$W") B" | tee -a "$LOG"
  PREV=$NAME
done
echo "[$(date +%H:%M:%S)] ⏹ 接力链结束 (最后: $PREV)" | tee -a "$LOG"
