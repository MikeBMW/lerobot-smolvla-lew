#!/usr/bin/env bash
# 🔁 v4 判闸全量复跑: 7 个 v6 权重 × skill on/zero, 训练同源口径 (见 tools/intact_replay_check_v4.py 头注)
# 输出 reports/intact_v4_<fam>_epoch<ep>_skill_<mode>.json ; 日志 reports/v4_judge_sweep.log
set -uo pipefail
cd /home/ubuntu/lerobot-smolvla-lew
export INTACT_RUNTIME=root STABLEWM_HOME=/home/ubuntu/stable-wm-cache LOCAL_DATASET_DIR=/home/ubuntu/stable-wm-cache
export OMP_NUM_THREADS=8 MKL_NUM_THREADS=8 OPENBLAS_NUM_THREADS=8 NUMEXPR_NUM_THREADS=8
PY=./gui-venv311/bin/python
LOG=reports/v4_judge_sweep.log
CLIPS=${CLIPS:-200}
REPS=${REPS:-3}

: > "$LOG"
echo "[$(date '+%F %T')] ▶ v4 判闸复跑开始 · clips=$CLIPS reps=$REPS · 14 次运行" | tee -a "$LOG"

run() {  # fam ep mode
  local fam=$1 ep=$2 mode=$3
  local out="reports/intact_v4_${fam}_epoch${ep}_skill_${mode}.json"
  echo "[$(date '+%F %T')] ▶ ${fam} epoch${ep} skill=${mode}" | tee -a "$LOG"
  INTACT_POLICY="${fam}/weights_epoch_${ep}.pt" timeout 1800 "$PY" tools/intact_replay_check_v4.py \
    --skill "$mode" --clips "$CLIPS" --repeats "$REPS" --device cuda --out "$out" >>"$LOG" 2>&1
  echo "[$(date '+%F %T')] ✅ ${fam} epoch${ep} ${mode} rc=$?" | tee -a "$LOG"
}

for fam in intact_goal_optical_insert_v6r2_s3072 intact_goal_optical_insert_v6r5_s3072 \
           intact_goal_optical_insert_v6r6_s3072 intact_goal_optical_insert_v6r7_s3072 \
           intact_goal_optical_insert_v6r8_s3072 intact_goal_optical_insert_v6r9_s3072 \
           intact_goal_optical_insert_v6r10_s3072; do
  ep=1
  case "$fam" in *v6r2*) ep=3 ;; esac      # 判闸表里的对照锚 = v6r2 ep3
  for mode in on zero; do run "$fam" "$ep" "$mode"; done
done
echo "[$(date '+%F %T')] 🏁 全部完成" | tee -a "$LOG"
