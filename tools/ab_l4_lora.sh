#!/bin/bash
# L4 LoRA 同口径 A/B: 在役 intact_l4_current  vs  新训 intact_goal_optical_insert_v6lora_200
# 口径: 同一 seed / 同一 mode=insert / 同一 vote 并联仲裁 / 同一引擎闭环; 只换 INTACT_POLICY 一处
cd /home/ubuntu/lerobot-smolvla-lew || exit 9
SWM=/home/ubuntu/stable-wm-cache
NEW=$SWM/checkpoints/intact_goal_optical_insert_v6lora_200
[ -f "$NEW/weights.pt" ] || ln -sfn weights_epoch_1.pt "$NEW/weights.pt"     # 加载器要求恰好一个 weights.pt 软链
ls -l "$NEW/weights.pt"
OUT=reports/ab_lora_l4_$(date +%Y%m%d_%H%M%S); mkdir -p "$OUT"
for pol in intact_l4_current intact_goal_optical_insert_v6lora_200; do
  echo "===== INTACT_POLICY=$pol =====" | tee -a "$OUT/ab.log"
  INTACT_POLICY=$pol INTACT_DEVICE=cpu INTACT_RUNTIME=root INTACT_KEEP_INPUT=1 \
  STABLEWM_HOME=$SWM LOCAL_DATASET_DIR=$SWM INTACT_REPO=/home/ubuntu/INTACT-JEPA \
  MUJOCO_GL=egl ./gui-venv311/bin/python tools/pipeline_closure_run.py --seed 104 --vote --steps 450 \
    > "$OUT/$pol.log" 2>&1
  echo "rc=$?" | tee -a "$OUT/ab.log"
  grep -E "引擎闭环|整个数据闭环|L4 |✓|↩" "$OUT/$pol.log" | tail -6 | tee -a "$OUT/ab.log"
  echo | tee -a "$OUT/ab.log"
done
echo "A/B 日志: $OUT" | tee -a "$OUT/ab.log"
