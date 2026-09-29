#!/bin/bash
# 无人值守接力: 等 v2 采集结束 → 合并 part npz → 官方 h5 → 重训 (动作头权重提升 + 30 epoch)
set -u
LOG=/tmp/chain_v2.log
exec >>"$LOG" 2>&1
echo "=== chain 启动 $(date '+%F %T') ==="
while pgrep -f 'intact_domain_dataset.py' >/dev/null; do sleep 20; done
echo "=== 采集结束 $(date '+%F %T') ==="

cd /home/ubuntu/lerobot-smolvla-lew || exit 1
export HDF5_PLUGIN_PATH=/home/ubuntu/.h5plugins
export STABLEWM_HOME=/home/ubuntu/stable-wm-cache
export LOCAL_DATASET_DIR=/home/ubuntu/stable-wm-cache
export HF_ENDPOINT=https://hf-mirror.com

N=$(ls reports/zmax_insert_v2_part*.npz 2>/dev/null | wc -l)
echo "part 数: $N"
if [ "$N" -lt 3 ]; then
  echo "❌ part 太少 ($N) → 不合并不训练 (拒绝拿残缺数据训模型)"
  exit 2
fi

/home/ubuntu/INTACT-JEPA/.venv/bin/python tools/intact_parts_to_h5.py \
  --parts 'reports/zmax_insert_v2_part*.npz' --out-name zmax_insert_v2 --validate || exit 3
echo "=== h5 合并完成 → 开始重训 $(date '+%F %T') ==="

cd /home/ubuntu/INTACT-JEPA || exit 1
# ⏱ 时间预算 (实测口径: 旧微调 1017 步/epoch · 0.77 s/步 @ batch16/4workers, 数据 18,635 帧)
#   v2 = 151,364 帧 (8.1×) → batch 24 时 ≈6,300 步/epoch; 32 核 → workers 12 提吞吐。
#   原计划 30 epoch 按实测速度要 ≈50 小时 (不可接受) → 砍到 6 epoch (≈3.5-4.5h),
#   且**每个 epoch 的 ckpt 都会落盘** → 我可以在训练跑着的同时用离线回放闸逐个评, 过闸就提前用。
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
STABLEWM_HOME=/home/ubuntu/stable-wm-cache LOCAL_DATASET_DIR=/home/ubuntu/stable-wm-cache \
.venv/bin/python train.py --config-name intact_goal_zmax \
  output_model_name=intact_goal_zmax_v2_s3072 \
  data.dataset.name=zmax_insert_v2.h5 \
  trainer.max_epochs=6 \
  loss.intent.local_weight=1.0 \
  loss.intent.goal_weight=1.0 \
  loader.batch_size=24 \
  loader.num_workers=12
echo "=== 重训结束 rc=$? $(date '+%F %T') ==="
