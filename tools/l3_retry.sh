#!/bin/bash
# L3 (SmolVLA+LoRA) 重试: 首次 rc=1 是 CUDA OOM (8GB 卡上还有 joint_unified_backbone 占 1.5G)
# 处置: batch 4 → 2 + expandable_segments + 等 GPU 余量; 结果追加到训练链 status.txt (哨兵会看见)
cd /home/ubuntu/lerobot-smolvla-lew || exit 9
OUT=$(cat /tmp/fullpipe_current_dir)
{
  echo "[L3_retry] start $(date '+%F %T') batch=2 tag=r4"
} >> "$OUT/status.txt"
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
  ./gui-venv311/bin/python tools/joint_train_all.py --only L3 --steps 200 \
    --l3-tag r4 --l3-batch 2 --gpu-wait 1800 >> "$OUT/L3_retry.log" 2>&1
rc=$?
echo "[L3_retry] RC=$rc end $(date '+%F %T')" >> "$OUT/status.txt"
tail -25 "$OUT/L3_retry.log"
exit $rc
