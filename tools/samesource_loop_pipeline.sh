#!/usr/bin/env bash
# 同源闭环流水线: 采引擎轨迹 → 同源训头(CV 报指标 + 落 ckpt) → 闭环复验
set -u
cd /home/ubuntu/zmax_rel || exit 1
PY=./gui-venv311/bin/python
DS=/home/ubuntu/stable-wm-cache/datasets/cog_engine_trace_v2.h5
F="/tmp/cog_samesource.log"
: > "$F"
flt() { grep -vE "^\[transformers\]|Loading weights|UNEXPECTED|^Notes:|^- +[a-z]|^Key " ; }

echo "═══ ① 采集引擎同源轨迹 (30 段 × 220 步, insert/full 交替) ═══" | tee -a "$F"
timeout 250 $PY tools/collect_cog_engine_trace.py --episodes 30 --steps 220 --out "$DS" 2>&1 | flt | tail -5 | tee -a "$F"

echo | tee -a "$F"
echo "═══ ② 同源 5 折交叉验证 (诚实指标) ═══" | tee -a "$F"
timeout 250 $PY tools/train_cog_event_head.py --data "$DS" --cv 5 --epochs 3000 --hidden 256 --tag engine_v2 2>&1 | flt | tail -12 | tee -a "$F"

echo | tee -a "$F"
echo "═══ ③ 同源训练并落 ckpt (供闭环加载) ═══" | tee -a "$F"
timeout 250 $PY tools/train_cog_event_head.py --data "$DS" --epochs 6000 --hidden 256 --tag engine_v2 2>&1 | flt | tail -11 | tee -a "$F"

echo | tee -a "$F"
echo "═══ ④ 闭环复验 (加载同源 ckpt engine_v2) ═══" | tee -a "$F"
ZMAX_COG_EVENT_TAG=engine_v2 timeout 250 $PY tools/verify_cog_event_loop.py --steps 220 --seed 100 2>&1 | flt | tail -20 | tee -a "$F"
echo | tee -a "$F"
echo "完成 (完整日志 $F)" | tee -a "$F"
