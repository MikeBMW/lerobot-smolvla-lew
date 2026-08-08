#!/bin/bash
# Z-MAX 标准容器 — 推理/评测入口 (容器内)
# 用法: zmax-infer --policy act --ckpt outputs/train/act_xxx/checkpoints/last/pretrained_model
#      zmax-infer --video all          → 7 模型仿真 rollout 对比视频
#      zmax-infer --report             → Model Zoo PDF 技术选型报告
set -e
cd /app

MODE=""
POLICY=""
CKPT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --policy) POLICY="$2"; shift 2 ;;
    --ckpt) CKPT="$2"; shift 2 ;;
    --video) MODE="video"; shift ;;
    --report) MODE="report"; shift ;;
    *) shift ;;
  esac
done

if [ "$MODE" = "report" ]; then
  echo "📄 [zmax-infer] 生成 Model Zoo PDF 报告…"
  exec python -u tools/gui/report_model_zoo.py
fi
if [ "$MODE" = "video" ]; then
  echo "🎮 [zmax-infer] 7 模型仿真 rollout 对比视频…"
  exec python -u tools/gui/simulink_rollout.py --all
fi

[ -z "$POLICY" ] && echo "❌ 用法: zmax-infer --policy act [--ckpt path]" && exit 1
echo "🎮 [zmax-infer] 推理: policy=$POLICY ckpt=$CKPT"
exec python -u tools/gui/simulink_rollout.py --policy "$POLICY" --ckpt "$CKPT"
