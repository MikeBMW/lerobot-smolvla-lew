#!/usr/bin/env bash
# 论文权重 Direct(零搜索) 评测 —— 单任务执行 (供人工/流水线调用)
# 用法: bash run_paper_direct.sh [TASK] [POLICY] [SEED] [NUM_EVAL]
#   TASK   ∈ pusht|cube|reacher|tworoom
#   POLICY 默认 recovery_delta_full_<task>_s3072 (缓存 checkpoints/ 下的权重目录名)
set -uo pipefail
TASK="${1:-pusht}"; POLICY="${2:-recovery_delta_full_${TASK}_s3072}"
SEED="${3:-42}"; NUM="${4:-100}"
ROOT=/home/ubuntu/INTACT-JEPA
PR="$ROOT/paper_runtime"
export VIRTUAL_ENV="$ROOT/.venv"
export PATH="$VIRTUAL_ENV/bin:$PATH"
export STABLEWM_HOME="${STABLEWM_HOME:-/home/ubuntu/stable-wm-cache}"
export LOCAL_DATASET_DIR="$STABLEWM_HOME"
export MUJOCO_GL="${MUJOCO_GL:-egl}" PYOPENGL_PLATFORM="${PYOPENGL_PLATFORM:-egl}"
export CUBLAS_WORKSPACE_CONFIG="${CUBLAS_WORKSPACE_CONFIG:-:4096:8}"
export PYTHONPATH="$PR:$ROOT"

echo "=== 0) 评测指纹 (钉住的 5 文件必须一致) ==="
( cd "$PR" && sha256sum -c RUNTIME_SHA256SUMS ) || { echo "❌ 指纹不符, 中止"; exit 1; }
echo "=== 1) 数据/权重就位检查 ==="
case "$TASK" in
  pusht)   DS="$STABLEWM_HOME/datasets/pusht_expert_train.h5";;
  cube)    DS="$STABLEWM_HOME/datasets/ogbench/cube_single_expert.h5";;
  reacher) DS="$STABLEWM_HOME/datasets/reacher.h5";;
  tworoom) DS="$STABLEWM_HOME/datasets/tworoom.h5";;
  *) echo "未知任务 $TASK"; exit 2;;
esac
ls -la "$DS" 2>/dev/null || { echo "  ⚠️ 数据集缺失: $DS"; }
ls -la "$STABLEWM_HOME/checkpoints/$POLICY/weights_epoch_5.pt" 2>/dev/null || echo "  ⚠️ 权重缺失"
echo "=== 2) 官方 Direct 评测 (paper_runtime + PriorOnlySolver: 零搜索) ==="
date '+%F %T 开始'
cd "$PR"
# 注: 不传 eval.actor_warmstart (paper 配置里没有该键, 传了会 KeyError);
#     paper eval.py 默认 OmegaConf.select(..., default=True) 已开启 actor。
python eval.py --config-name="$TASK" solver=prior_only policy="$POLICY" \
  seed="$SEED" eval.num_eval="$NUM" 2>&1 | tail -45
rc=${PIPESTATUS[0]}
date "+%F %T 结束 (rc=$rc)"
echo "=== 3) 证据文件 ==="
ls -la "$STABLEWM_HOME"/${TASK}_results.txt* 2>/dev/null
