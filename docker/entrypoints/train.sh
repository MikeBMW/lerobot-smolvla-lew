#!/bin/bash
# Z-MAX 标准容器 — 训练入口 (容器内)
# 用法: zmax-train --config_path config_xxx.yaml [--steps N] [--batch N] [--lr X]
# 数据 root 自动归一: data/metaworld_peg_grab6 (容器统一数据)
set -e
cd /app

# 解析 --config_path (兼容 --config-path 旧写法)
CFG=""
STEPS=""
BATCH=""
LR=""
while [ $# -gt 0 ]; do
  case "$1" in
    --config_path|--config-path) CFG="$2"; shift 2 ;;
    --steps) STEPS="$2"; shift 2 ;;
    --batch) BATCH="$2"; shift 2 ;;
    --lr) LR="$2"; shift 2 ;;
    *) shift ;;
  esac
done

[ -z "$CFG" ] && echo "❌ 用法: zmax-train --config_path config.yaml" && exit 1
[ -f "$CFG" ] || { echo "❌ 配置不存在: $CFG"; exit 1; }

# 数据 root 统一 (容器内标准数据)
sed -i "s|^  root: .*|  root: data/metaworld_peg_grab6|" "$CFG" 2>/dev/null || true

CMD=(python -u -m lerobot.scripts.lerobot_train --config_path "$CFG")
[ -n "$STEPS" ] && CMD+=(--steps "$STEPS")
[ -n "$BATCH" ] && CMD+=(--batch "$BATCH")
[ -n "$LR" ] && CMD+=(--lr "$LR")
echo "🚀 [zmax-train] 启动: ${CMD[*]}"
exec "${CMD[@]}"
