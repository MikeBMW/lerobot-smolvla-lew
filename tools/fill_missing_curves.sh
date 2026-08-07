#!/bin/bash
# 补齐七模型真实数据: AWE(在跑) → VLA-Touch → MLP 蒸馏 (2026-08-07 老倪: 真实完整报告)
cd /home/xspace/lerobot-smolvla-lew
echo "[$(date +%H:%M)] ① 等 AWE-zFlow 训练完成..."
while pgrep -f train_awe_zflow >/dev/null; do sleep 10; done
sleep 3
echo "[$(date +%H:%M)] ② 跑 VLA-Touch (2000 步, metaworld_peg_v7)..."
.venv/bin/python tools/train_vla_touch.py --steps 2000 --data-root data/metaworld_peg_v7 2>&1 | tail -5
echo "[$(date +%H:%M)] ③ 跑 MLP 蒸馏 (distill_expert, 300 episodes)..."
.venv/bin/python tools/distill_expert.py 2>&1 | tail -5
echo "[$(date +%H:%M)] ④ 曲线盘点:"
for p in vla_touch awe_zflow expert_mlp; do
  n=$(.venv/bin/python -c "
import json, os
f='reports/train_curve_$p.json'
if os.path.exists(f):
    d=json.load(open(f)); c=d.get('curve',[])
    print(f'$p: {len(c)}点 step_s={d.get(\"step_s\")}')
else:
    print(f'$p: 无文件')
" 2>/dev/null)
  echo "  $n"
done
echo "[$(date +%H:%M)] 补训链完成"
