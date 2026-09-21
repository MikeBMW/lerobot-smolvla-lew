#!/bin/bash
# 🧠⚡ v6 新数据接力链 (2026-09-21) —— 用「新抗干扰数据 + skill_ctx」适配训练 L4 INTACT
#
# 口径 (沿用 tools/v6_fast_chain.sh 的约定, 不新造):
#   · 数据: data=zmax_v6 → optical_insert_v6_disturb.h5 (新采集 128 条, 带 24 维 skill_ctx)
#   · 每轮: 1 epoch × 1000 步 (batch 16 → 1.6 万帧/轮)  ≈ 8.5 分钟
#   · 续训: init_weights_path=上一轮 weights_epoch_1.pt, init_zero_skill_branch=false
#           (不零化记忆通道 → 记忆能力逐轮累积, 不是每轮重学)
#   · 每轮独立目录名 v6d1..v6d3 → 与老 v6r* 链隔离, 可对比
# 用法: bash tools/v6_newdata_chain.sh [轮数=3] [起始轮号=1]
set -u
CACHE=/home/ubuntu/stable-wm-cache/checkpoints
ROOT=/home/ubuntu/lerobot-smolvla-lew
LOG=$ROOT/reports/v6_newdata_chain.log
cd /home/ubuntu/INTACT-JEPA || exit 1

ROUNDS=${1:-3}
START=${2:-1}
INIT_OVERRIDE=${3:-}
PREV=intact_goal_optical_insert_v6r11_s3072          # 默认起点 = 当前在役 L4 (intact_l4_current 指向它)
INIT=$CACHE/$PREV/weights_epoch_2.pt
# 自动续训: 若上一轮 (START-1) 的产物在, 直接从它续 (重跑链时不用回头)
if [ -n "$INIT_OVERRIDE" ]; then
  INIT=$INIT_OVERRIDE; PREV="(指定)"
elif [ "$START" -gt 1 ] && [ -f "$CACHE/intact_goal_optical_insert_v6d$((START-1))_s3072/weights_epoch_1.pt" ]; then
  PREV=intact_goal_optical_insert_v6d$((START-1))_s3072
  INIT=$CACHE/$PREV/weights_epoch_1.pt
fi
[ -f "$INIT" ] || { echo "❌ 缺起点权重 $INIT"; exit 1; }
echo "[$(date +%H:%M:%S)] ▶ 起点 $PREV/$INIT" | tee -a "$LOG"

for k in $(seq "$START" $((START + ROUNDS - 1))); do
  NAME=intact_goal_optical_insert_v6d${k}_s3072
  echo "[$(date +%H:%M:%S)] ▶ $NAME (1 epoch × 1000 步, data=zmax_v6, 续自 $PREV)" | tee -a "$LOG"
  PATH=/home/ubuntu/INTACT-JEPA/.venv/bin:$PATH \
  STABLEWM_HOME=/home/ubuntu/stable-wm-cache LOCAL_DATASET_DIR=/home/ubuntu/stable-wm-cache \
  nice -n 5 ./.venv/bin/python train.py --config-name=intact_goal_optical_insert_v6 \
      data=zmax_v6 \
      output_model_name="$NAME" init_weights_path="$INIT" init_zero_skill_branch=false \
      trainer.max_epochs=1 +trainer.limit_train_batches=1000 2>&1 | tee -a "$LOG"
  W=$CACHE/$NAME/weights_epoch_1.pt
  if [ ! -f "$W" ]; then echo "[$(date +%H:%M:%S)] ❌ $NAME 没产出权重 → 停链 (日志 $LOG)" | tee -a "$LOG"; exit 1; fi
  echo "[$(date +%H:%M:%S)] ✅ $NAME 完成: $(stat -c %s "$W") B" | tee -a "$LOG"
  PREV=$NAME; INIT=$W
done
echo "[$(date +%H:%M:%S)] ⏹ 接力链结束 (最后: $PREV) — 下一步: bash tools/intact/run_intact_eval.sh" | tee -a "$LOG"
