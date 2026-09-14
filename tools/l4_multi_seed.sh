#!/bin/bash
# 🔬 多 seed 闭环对照 (2026-09-14): 口径修好后, 同权重 / 同口径 / 多 seed 跑「解析链 vs 模型直驱」
#   依据: 评估铁律 —— metaworld 每进程布局漂移, 单次评估不可信 (曾出现同权重 7/8 vs 4/8)
#   每 seed 一轮内部同时跑两臂 (--baseline 1), 各录 mp4; 最后汇总成表。
set -u
ROOT=/home/ubuntu/lerobot-smolvla-lew
OUT=$ROOT/reports/evidence_l4_fixed
CK=intact_goal_optical_insert_v6r2_s3072/weights_epoch_3.pt     # 现役最佳 (3 epoch/17610 步)
LOG=$OUT/multi_seed.log
mkdir -p "$OUT"
echo "[$(date +%H:%M:%S)] ▶ 多 seed 闭环对照 · 权重 $CK" | tee -a "$LOG"
for S in 0 1 2; do
  echo "[$(date +%H:%M:%S)] ▶ seed $S" | tee -a "$LOG"
  cd "$ROOT" || exit 1
  HF_HUB_OFFLINE=1 SS_L3_DEV=cpu SS_L4_DIT=1 SS_L4_DIT_BETA=0.5 SS_L4_DIT_EVERY=16 \
  INTACT_DEVICE=cpu INTACT_POLICY="$CK" CUDA_VISIBLE_DEVICES= nice -n 10 \
  timeout 1800 gui-venv311/bin/python tools/intact_direct_rollout.py \
      --max-steps 260 --infer-every 4 --baseline 1 --seed "$S" --device cpu \
      --video-dir "$OUT" --out "$OUT/seed${S}.json" 2>&1 | tail -12 | tee -a "$LOG"
done
echo "[$(date +%H:%M:%S)] ⏹ 三 seed 跑完, 汇总如下" | tee -a "$LOG"
python3 - <<'PY' | tee -a "$OUT/multi_seed.log"
import json, glob, os
print(f"{'seed':<8}{'解析链 done/插入mm':<22}{'直驱 done/插入mm':<22}{'直驱真推理':<10}{'skill非零':<10}")
rows = []
for p in sorted(glob.glob("/home/ubuntu/lerobot-smolvla-lew/reports/evidence_l4_fixed/seed*.json")):
    d = json.load(open(p))
    for r in d.get("rows", []):
        a, b = r.get("analytic", {}), r.get("direct", {})
        print(f"{str(r.get('seed')):<8}"
              f"{str(a.get('done'))+'/'+str(a.get('insert_mm')):<22}"
              f"{str(b.get('done'))+'/'+str(b.get('insert_mm')):<22}"
              f"{str(b.get('model_calls')):<10}{str(b.get('skill_ctx_nonzero')):<10}")
        rows.append(r)
json.dump({"ckpt": "intact_goal_optical_insert_v6r2_s3072/weights_epoch_3.pt", "rows": rows},
          open("/home/ubuntu/lerobot-smolvla-lew/reports/evidence_l4_fixed/multi_seed_summary.json","w"),
          ensure_ascii=False, indent=1)
print(f"共 {len(rows)} 个 seed 行 → reports/evidence_l4_fixed/multi_seed_summary.json")
PY
echo "[$(date +%H:%M:%S)] ✅ 汇总 JSON 已写" | tee -a "$LOG"
