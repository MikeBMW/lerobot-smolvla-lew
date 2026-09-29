#!/bin/bash
# 原项目自带评测: **必须在 paper_runtime/ 下跑** (论文权重 checkpoint 的 config 引用
#   module.InverseTransitionActor, 只有 paper_runtime 有 → 在仓库根跑会报
#   "Error locating target 'module.InverseTransitionActor'")。
# 输出: 官方渲染视频 env_*.mp4 (落在 stable-wm-cache/) + <task>_direct_s<seed>_n<N>.txt
set -u
RT=/home/ubuntu/INTACT-JEPA/paper_runtime
cd "$RT" || exit 1
export INTACT_SKIP_PREFLIGHT=1
export STABLEWM_HOME=/home/ubuntu/stable-wm-cache
export LOCAL_DATASET_DIR=/home/ubuntu/stable-wm-cache
export HF_ENDPOINT=https://hf-mirror.com
export MUJOCO_GL=egl
export PYOPENGL_PLATFORM=egl
export HDF5_PLUGIN_PATH=/home/ubuntu/.h5plugins
export PYTHONPATH="$RT"
OUT=/home/ubuntu/lerobot-smolvla-lew/reports/intact_official
mkdir -p "$OUT"
for T in "$@"; do
  echo "=== $T: 原项目官方评测 (论文权重 recovery_delta_full_${T}_s3072 · direct 零搜索) $(date '+%H:%M:%S') ==="
  rm -f /home/ubuntu/stable-wm-cache/env_*.mp4
  ../.venv/bin/python eval.py --config-name="$T" solver="${SOLVER:-prior_only}" \
      policy="recovery_delta_full_${T}_s3072" seed=42 eval.num_eval="${N_EVAL:-6}" \
      output.filename="${T}_direct_seed42_n${N_EVAL:-6}.txt" 2>&1 | tail -16
  mkdir -p "$OUT/$T"
  cp -f /home/ubuntu/stable-wm-cache/env_*.mp4 "$OUT/$T"/ 2>/dev/null
  echo "   → 视频 $(ls "$OUT/$T" | wc -l) 个已存 $OUT/$T"
done
echo "=== 完成 $(date '+%F %T') ==="
