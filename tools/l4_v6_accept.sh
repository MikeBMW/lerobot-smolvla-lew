#!/bin/bash
# L4 v6 验收 (无人值守): 等训练链 → 判闸(on/zero 同帧同权重) → ΔMAE → 官方 Direct 评测(3 seeds)
# 2026-09-22
set -u
cd /home/ubuntu/lerobot-smolvla-lew || exit 1
LOG=$HOME/zmax_data/ss_sim_20260921/l4_v6_accept.log
CACHE=/home/ubuntu/stable-wm-cache
CKPT=$CACHE/checkpoints
H5=$CACHE/datasets/optical_insert_v6_disturb.h5
say(){ echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

say "等训练链结束..."
while pgrep -f "v6_newdata_chain.sh" >/dev/null 2>&1; do sleep 30; done
say "训练链结束"

LAST=$(ls -d $CKPT/intact_goal_optical_insert_v6d*_s3072 2>/dev/null | sort -V | tail -1)
[ -n "$LAST" ] || { say "❌ 没找到 v6d* 权重目录"; exit 1; }
POL="$(basename "$LAST")/weights_epoch_1.pt"
say "最后权重: $POL"

say "判闸: 新数据 $H5 × 新权重 (clips=240 repeats=3)"
for s in on zero; do
  say "  ── skill=$s"
  INTACT_POLICY="$POL" gui-venv311/bin/python tools/intact_replay_check_v4.py \
    --h5 "$H5" --stats reports/optical_insert_v6_action_stats.json \
    --skill "$s" --clips 240 --repeats 3 \
    --out "reports/intact_v4_v6_${s}.json" >> "$LOG" 2>&1
done

say "汇总 ΔMAE (新数据/新权重)"
/home/ubuntu/INTACT-JEPA/.venv/bin/python - <<'PY' 2>&1 | tee -a "$LOG"
import json, os
R = "/home/ubuntu/lerobot-smolvla-lew/reports"
def mean_sel(j, slots=(0, 4, 8, 15)):
    ps = j.get("per_slot", {})
    vals = [ps[str(s)]["mae"] for s in slots if str(s) in ps]
    return sum(vals) / len(vals) if vals else float("nan")
res = {}
for arm in ("on", "zero"):
    p = f"{R}/intact_v4_v6_{arm}.json"
    if not os.path.exists(p):
        print(f"  {arm}: 缺文件 {p}"); continue
    j = json.load(open(p))
    res[arm] = mean_sel(j)
    const = j["per_slot"]["0"]["const"]
    pr = j["per_slot"]["0"].get("pearson_dx")
    print(f"  skill={arm:4s}: 槽[0,4,8,15] MAE={res[arm]:.4f}  常数={const:.4f}  "
          f"{'✅赢常数' if res[arm] < const else '❌输常数'}  pearson_dx(slot0)={pr:.3f}")
if len(res) == 2:
    print(f"  ΔMAE(on-zero) = {res['on'] - res['zero']:+.4f}"
          f"   (基线: 老权重×老数据 on=0.0365 zero=0.1306 Δ=-0.0941)")
PY

say "官方 Direct 评测 (pusht, seeds 0/1/42, num=100) — 数据不在位则仅记录 preflight"
for S in 0 1 42; do
  say "  ── seed $S"
  timeout 1800 bash tools/intact/run_intact_eval.sh direct pusht "$POL" "$S" 100 >> "$LOG" 2>&1 \
    && say "     seed $S 完成" || say "     seed $S 失败/超时 (见日志)"
done
say "DONE — 日志 $LOG"
