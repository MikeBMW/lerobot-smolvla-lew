#!/bin/bash
# L4 v6 新数据 收尾流水: 等采集→补 part00→合并 h5→生成 action stats
# (2026-09-22; part00 被转换器的默认行为删掉过, 所以这里重采 seeds 0-19 补回)
set -u
cd /home/ubuntu/lerobot-smolvla-lew || exit 1
LOG=$HOME/zmax_data/ss_sim_20260921/l4_v6_post.log
say(){ echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

say "等采集进程结束..."
while pgrep -f "intact_insert_dataset_v5.py --seeds 0-127" >/dev/null 2>&1; do sleep 20; done
say "采集结束"

say "补采 seeds 0-19 (重建 part00)"
gui-venv311/bin/python tools/intact_insert_dataset_v5.py --seeds 0-19 --mode full \
  --l2-skill-ctx 1 --disturb mixed --success-only 1 --out-name optical_insert_v6_disturb >> "$LOG" 2>&1
ls -lh reports/optical_insert_v6_disturb_part*.npz | tee -a "$LOG"

say "合并 → optical_insert_v6_disturb.h5 (--skill-ctx --keep-parts)"
LOCAL_DATASET_DIR=/home/ubuntu/stable-wm-cache /home/ubuntu/INTACT-JEPA/.venv/bin/python tools/intact_parts_to_h5.py \
  --parts 'reports/optical_insert_v6_disturb_part*.npz' \
  --out-name optical_insert_v6_disturb --dest /home/ubuntu/stable-wm-cache/datasets \
  --skill-ctx --keep-parts >> "$LOG" 2>&1
ls -lh /home/ubuntu/stable-wm-cache/datasets/optical_insert_v6_disturb.h5 | tee -a "$LOG"

say "生成 v6 action stats (闭环反归一化同一份)"
/home/ubuntu/INTACT-JEPA/.venv/bin/python tools/action_stats_from_h5.py \
  --h5 /home/ubuntu/stable-wm-cache/datasets/optical_insert_v6_disturb.h5 \
  --out reports/optical_insert_v6_action_stats.json >> "$LOG" 2>&1
ls -l reports/optical_insert_v6_action_stats.json | tee -a "$LOG"

say "DONE (下一步: bash tools/v6_newdata_chain.sh 3 1)"
