#!/bin/bash
# 🏁 收尾器 (2026-09-14 老倪: "加快, 打完立刻手工")
#   ① 等 v6r10 权重落地 → 停掉接力链 (不再起 v6r11, 把 CPU 让给闭环对照与判闸) → 加快
#   ② 等 3 seed 闭环对照跑完
#   ③ **手工**判所有未判轮次 (不等 cron)
#   ④ 出两张表: 训练步数→判闸趋势 / 3 seed 闭环对照
set -u
ROOT=/home/ubuntu/lerobot-smolvla-lew
OUT=$ROOT/reports/evidence_l4_fixed
CACHE=/home/ubuntu/stable-wm-cache/checkpoints
LOG=$ROOT/reports/finish_20260914.log
say() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

say "⏳ 等 v6r10 权重落地…"
for _ in $(seq 1 150); do
  [ -f "$CACHE/intact_goal_optical_insert_v6r10_s3072/weights_epoch_1.pt" ] && break
  sleep 10
done
if [ -f "$CACHE/intact_goal_optical_insert_v6r10_s3072/weights_epoch_1.pt" ]; then
  say "v6r10 权重已落地 → 停接力链 (跳过 v6r11, CPU 让给对照+判闸)"
  for p in $(pgrep -f "[v]6_fast_chain.sh"); do kill "$p" 2>/dev/null && say "  TERM 接力链 wrapper pid=$p"; done
  sleep 3
  for p in $(pgrep -f "output_model_name=intact_goal_optical_insert_v6r1[01]_s3072"); do
    kill "$p" 2>/dev/null && say "  TERM 训练 pid=$p"
  done
else
  say "⚠️ v6r10 权重等超时 (25 分钟) — 继续往下走"
fi

say "⏳ 等 3 seed 闭环对照…"
for _ in $(seq 1 180); do
  [ -f "$OUT/seed2.json" ] && break
  sleep 10
done
[ -f "$OUT/seed2.json" ] && say "✅ 三 seed 全部完成" || say "⚠️ seed2 超时未完成"

say "🧠 手工判闸 (扫所有未判轮次)"
ZMAX_V6_JUDGE_BUDGET=6 python3 /home/ubuntu/.hermes/scripts/v6_judge_watch.py 2>&1 | tee -a "$LOG"

say "📊 汇总"
python3 - <<'PY' 2>&1 | tee -a "$LOG"
import glob, json, os
STEPS = {"intact_goal_optical_insert_v6r2_s3072": "v6r2(17610 步, 死锁前)",
         "intact_goal_optical_insert_v6r5_s3072": "+400",
         "intact_goal_optical_insert_v6r6_s3072": "+1000",
         "intact_goal_optical_insert_v6r7_s3072": "+2000",
         "intact_goal_optical_insert_v6r8_s3072": "+3000",
         "intact_goal_optical_insert_v6r9_s3072": "+4000",
         "intact_goal_optical_insert_v6r10_s3072": "+5000",
         "intact_goal_optical_insert_v6r11_s3072": "+6000"}
print("=== A. 判闸趋势 (同权重同帧 on/zero 消融, 修好图像桥后) ===")
print(f"{'家族':<10}{'额外步数':<12}{'MAE(on)':<10}{'MAE(zero)':<11}{'ΔMAE':<10}{'std比':<8}{'不塌缩':<7}{'过闸'}")
rows = []
for f in glob.glob("/home/ubuntu/l4_ab/judged/intact_goal_optical_insert_v6*_epoch*.json"):
    if "__prefix" in f or "deadlock" in f:
        continue
    d = json.load(open(f))
    fam = d["family"]
    rows.append((STEPS.get(fam, fam[-14:]), d))
for tag, d in rows:
    ok = "✅" if (d["win_const"] and d["skill_gain"] and d["no_collapse"]) else "❌"
    print(f"{d['family'][-7:]:<10}{tag:<12}{d['mae_on']:<10.4f}{d['mae_zero']:<11.4f}"
          f"{d['gain_abs']:<+10.5f}{d['std_ratio_on']:<8.2f}{str(d['no_collapse']):<7}{ok}")
print("\n=== B. 3 seed 闭环对照 (口径修好后; 解析链不依赖模型=对照锚) ===")
print(f"{'seed':<6}{'解析链 done':<12}{'解析链插入mm':<14}{'直驱 done':<11}{'直驱插入mm':<12}{'直驱真推理':<11}{'skill非零'}")
s = json.load(open("/home/ubuntu/lerobot-smolvla-lew/reports/evidence_l4_fixed/multi_seed_summary.json"))
for r in s["rows"]:
    a, b = r.get("analytic", {}), r.get("direct", {})
    print(f"{str(r.get('seed')):<6}{str(a.get('done')):<12}{str(a.get('insert_mm')):<14}"
          f"{str(b.get('done')):<11}{str(b.get('insert_mm')):<12}{str(b.get('model_calls')):<11}"
          f"{b.get('skill_ctx_nonzero')}")
ins_d = [r["direct"]["insert_mm"] for r in s["rows"] if isinstance(r.get("direct", {}).get("insert_mm"), (int, float))]
ins_a = [r["analytic"]["insert_mm"] for r in s["rows"] if isinstance(r.get("analytic", {}).get("insert_mm"), (int, float))]
if ins_d:
    print(f"\n直驱插入: {min(ins_d):.1f}~{max(ins_d):.1f}mm (n={len(ins_d)})  vs  解析链: {min(ins_a):.1f}~{max(ins_a):.1f}mm (n={len(ins_a)})")
print(f"权重: {s.get('ckpt')}")
PY
say "✅ 收尾器完成"
