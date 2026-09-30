#!/usr/bin/env bash
# 🎯 把 L4 INTACT 调试配置指向哪个权重 —— 一条命令切换 (老倪: "把调试配置先改好")
#
# 为什么这么设计 (踩过的坑):
#   · 4 个 VSCode 调试配置原来写死 `intact_goal_optical_insert_v4_s3072/weights_epoch_2.pt`
#     → 续训换名 (v5→v6→v6r2) 或删旧轮后, 配置就指向"上一代模型", 调试出来的数字不是当前的。
#   · 官方加载器 stable_worldmodel `load_pretrained(name)` 的解析规则 (实测读源码):
#       ① name 以 .pt 结尾 → 该文件 (同目录必须有 config.json)
#       ② name 是**文件夹** → 目录里**恰好一个 .pt** + config.json   ← 用它做稳定指针
#       ③ 否则当 HF repo id
#     所有相对路径都相对 <cache>/checkpoints/ 解析。
#   · 所以指针 = `checkpoints/intact_l4_current/` (config.json + weights.pt 软链),
#     调试配置只需写 `intact_l4_current`, 换轮次/换 epoch 都只动这一个软链。
#
# 用法:
#   bash tools/l4_use_ckpt.sh                 # 自动: 最新 v6* 轮次目录 + 该目录最新 epoch
#   bash tools/l4_use_ckpt.sh v6r2 1          # 指定轮次关键字 + epoch
#   bash tools/l4_use_ckpt.sh --pin intact_goal_optical_insert_v5_s3072/weights_epoch_4.pt
#   bash tools/l4_use_ckpt.sh --status        # 只看当前指向
set -u
CACHE=${STABLEWM_HOME:-/home/ubuntu/stable-wm-cache}
CK=$CACHE/checkpoints
PTR=$CK/intact_l4_current
LINK=$PTR/weights.pt

status() {
  if [ -L "$LINK" ]; then
    tgt=$(readlink -f "$LINK")
    echo "🎯 当前指针: $PTR/weights.pt"
    echo "   → $tgt"
    echo "   → 尺寸 $(stat -c %s "$tgt" 2>/dev/null) B · 时间 $(stat -c %y "$tgt" 2>/dev/null | cut -d. -f1)"
    echo "   调试配置用: INTACT_POLICY=intact_l4_current (+ INTACT_RUNTIME=root)"
  else
    echo "⚠️ 还没有指针目录/软链: $LINK"
    exit 1
  fi
}

[ "${1:-}" = "--status" ] && { status; exit 0; }

if [ "${1:-}" = "--pin" ]; then
  [ -n "${2:-}" ] || { echo "用法: --pin <轮次目录>/weights_epoch_N.pt"; exit 2; }
  SRC=$CK/$2
else
  KW=${1:-}; EP=${2:-}
  if [ -n "$KW" ]; then
    RUN=$(ls -d "$CK"/intact_goal_*"$KW"*_s3072 2>/dev/null | head -1)
  else
    RUN=$(ls -td "$CK"/intact_goal_optical_insert_v6*_s3072 2>/dev/null | head -1)
  fi
  [ -n "${RUN:-}" ] || { echo "❌ 找不到匹配的轮次目录 (关键字 '$KW')"; exit 3; }
  if [ -n "$EP" ]; then
    SRC=$RUN/weights_epoch_$EP.pt
  else
    SRC=$(ls -t "$RUN"/weights_epoch_*.pt 2>/dev/null | head -1)
  fi
fi
[ -f "$SRC" ] || { echo "❌ 权重不存在: $SRC"; exit 4; }

mkdir -p "$PTR"
cp -f "$(dirname "$SRC")/config.json" "$PTR/config.json" 2>/dev/null || echo "⚠️ 源目录没有 config.json → 官方文件夹加载会失败"
# 指针目录里必须**恰好一个** .pt (官方 _resolve_folder 多一个就报 Ambiguous) → 先清干净
find "$PTR" -maxdepth 1 -name "*.pt" -delete 2>/dev/null
ln -sfn "$(readlink -f "$SRC")" "$LINK"
echo "✅ 指针已更新"
status
echo
echo "四个 VSCode 调试配置 (INTACT_POLICY=intact_l4_current) 现在调试的就是这一份, 不用再改配置。"
