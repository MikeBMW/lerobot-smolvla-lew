#!/bin/bash
# L4 策略同口径多 seed A/B (隔离版): 直连线闭环 4 臂, 只换 INTACT_POLICY 一处
#   臂: analytic(解析对照) / direct(直驱基准 SS_L4_INTACT=1) / line_w0 / line_w1
#   指标: done · steps · 末端插入 mm · 全程最小 peg头↔目标 mm  (全部取自引擎真跑)
# 判据 (老倪): 新训权重**有提升**才允许切默认指针 intact_l4_current; 持平/回退一律不切
cd /home/ubuntu/lerobot-smolvla-lew || exit 9
SWM=/home/ubuntu/stable-wm-cache
OUT=reports/ab_l4_policy_ms_$(date +%Y%m%d_%H%M%S); mkdir -p "$OUT"
for pol in intact_l4_current intact_l4_v6lora_200; do
  echo "===== INTACT_POLICY=$pol =====" | tee -a "$OUT/ab.log"
  INTACT_POLICY=$pol INTACT_DEVICE=cpu INTACT_RUNTIME=root INTACT_KEEP_INPUT=1 \
  STABLEWM_HOME=$SWM LOCAL_DATASET_DIR=$SWM INTACT_REPO=/home/ubuntu/INTACT-JEPA MUJOCO_GL=egl \
  ./gui-venv311/bin/python tools/ab_intent_line_closedloop.py --seeds 0,1,2 --steps 450 \
    > "$OUT/$pol.log" 2>&1
  echo "rc=$?" | tee -a "$OUT/ab.log"
  grep -E "臂|analytic|direct|line_w|成功率|min|done|提升|回退" "$OUT/$pol.log" | tail -14 | tee -a "$OUT/ab.log"
  echo | tee -a "$OUT/ab.log"
done
echo "A/B(多seed) 日志: $OUT" | tee -a "$OUT/ab.log"
