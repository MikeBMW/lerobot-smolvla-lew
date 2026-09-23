#!/bin/bash
# 全量全系统 pipeline 训练链 (老倪 2026-09-23: "全量全系统模型全 pipeline 训练, 推理, 练习")
#   L5 定仿真 · 生数据  →  L4 给意图(INTACT + LoRA)  →  L3 给流程(SmolVLA + LoRA)  →  L2 给动作(检测/小模型)
# 纪律: 不覆盖旧产物(新目录/新数据名) · 不发任何真机指令 · 每阶段落日志+状态
cd /home/ubuntu/lerobot-smolvla-lew || exit 9
TS=$(date +%Y%m%d_%H%M%S)
OUT="reports/fullpipe_$TS"
mkdir -p "$OUT"
STATUS="$OUT/status.txt"
PY=./gui-venv311/bin/python
echo "START $(date '+%F %T') out=$OUT" > "$STATUS"
echo "$OUT" > /tmp/fullpipe_current_dir

run() {
  name="$1"; shift
  echo "[$name] start $(date '+%F %T')" >> "$STATUS"
  "$@" > "$OUT/$name.log" 2>&1
  rc=$?
  echo "[$name] RC=$rc end $(date '+%F %T')" >> "$STATUS"
  return $rc
}

# ① L5 定方向 + 造新数据 (规划器生成任务变体 → 引擎真跑 → h5)
run L5_gen $PY tools/l5_plan_and_gen.py --n 200 --steps 400 \
  --out /home/ubuntu/stable-wm-cache/datasets/l5_gen_v4.h5

# ② 全系统联合训练: L4 INTACT + LoRA · L3 SmolVLA + LoRA · L2 检测域适应
run JOINT $PY tools/joint_train_all.py --steps 200 --lora-l4 --lora-l3 \
  --l3-lora-engine local --yolo-epochs 30

# ②b LoRA 产物"可部署化": merge 包装键 + 建指针目录 + worker 自证 trained=True
#    (2026-09-23 实测: 不 merge 的话官方加载器报 Missing key → trained=False → 零动作,
#     会伪装成"新权重没提升"; 详见技能 intact-jepa-integration §0)
run LORA_MERGE bash tools/post_lora_merge.sh intact_goal_optical_insert_v6lora_200 \
  intact_l4_v6lora_200 8 16

# ③ 推理/练习验收: 把整条 pipeline 挂引擎跑闭环 (L5→MEM→L2→L4→L3 → 执行)
run EVAL $PY tools/pipeline_closure_run.py --seed 104 --vote

echo "DONE $(date '+%F %T')" >> "$STATUS"
