#!/usr/bin/env bash
# 官方 INTACT Direct 评测 (pusht) — 取 SR + 零搜索计时证据
# 用法: bash /home/ubuntu/l4_ab/run_intact_eval.sh [MODE] [TASK] [POLICY] [SEED] [NUM_EVAL]
set -uo pipefail
MODE="${1:-direct}"; TASK="${2:-pusht}"; POLICY="${3:-recovery_delta_full_pusht_s3072}"
SEED="${4:-42}"; NUM="${5:-100}"
cd /home/ubuntu/INTACT-JEPA
export VIRTUAL_ENV=/home/ubuntu/INTACT-JEPA/.venv
export PATH="$VIRTUAL_ENV/bin:$PATH"
export STABLEWM_HOME="${STABLEWM_HOME:-/home/ubuntu/stable-wm-cache}"
export LOCAL_DATASET_DIR="$STABLEWM_HOME"
export MUJOCO_GL="${MUJOCO_GL:-egl}" PYOPENGL_PLATFORM="${PYOPENGL_PLATFORM:-egl}"
echo "=== 前置检查 (依赖/数据/权重) ==="
bash scripts/eval_direct.sh --preflight-only "$TASK" "$POLICY" "$SEED" 2>&1 | tail -8
echo "=== 正式评测: mode=$MODE task=$TASK policy=$POLICY seed=$SEED num_eval=$NUM ==="
date '+%F %T 开始'
bash scripts/eval_official.sh "$MODE" "$TASK" "$POLICY" "$SEED" "$NUM" 2>&1 | tail -60
echo "=== 证据文件 ==="
ls -la "$STABLEWM_HOME/pusht_results.txt"* 2>/dev/null
date '+%F %T 结束'
