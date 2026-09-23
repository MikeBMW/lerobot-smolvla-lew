#!/bin/bash
# 链式: 等跨域A/B结束 → 继续长训 backbone → 写完成标记 (供 cron 上报)
set -u
cd /home/ubuntu/lerobot-smolvla-lew
D=/home/ubuntu/stable-wm-cache/datasets
V=/home/ubuntu/INTACT-JEPA/.venv/bin/python
LOG=/tmp/backbone_cont.log
MARK=/tmp/backbone_cont.done

rm -f "$MARK"
echo "[$(date '+%F %T')] 等待跨域 A/B 结束..." > "$LOG"

# 等 A/B 两个臂都退出
while pgrep -f "joint_unified_backbone.py --steps 800" >/dev/null 2>&1; do sleep 30; done
echo "[$(date '+%F %T')] A/B 已结束, 开始继续训练 backbone" >> "$LOG"

timeout 20000 $V -u tools/joint_unified_backbone.py \
  --steps 4000 --batch 256 --workers 8 --stats 200 \
  --lr 5e-4 --wd 0.01 --pixel-cache 1 \
  --holdout "$D/l5_holdout.h5" \
  --files "$D/v6_train_rand.h5,$D/l5_train.h5" \
  --save /home/ubuntu/stable-wm-cache/checkpoints/backbone_cont >> "$LOG" 2>&1
RC=$?
echo "exit=$RC" >> "$LOG"
echo "rc=$RC" > "$MARK"
echo "[$(date '+%F %T')] 完成 rc=$RC" >> "$LOG"
