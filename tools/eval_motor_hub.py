#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运动基元快通道验证 — 共享肌肉记忆接管 ⚡前馈槽位 (真实引擎)

三路对照:
  base  : 纯实时决策 (解析伺服链基线)
  mm    : 按 seed 查标杆 (旧快通道; 换场景即失效)
  mhub  : 共享运动基元 (多 seed 平均模板 → 跨场景泛化)

指标: 成功率 / 总步数 / 基元命中帧 / 段数与耗时分布
红线: 成功率不得回退; 关注"步数下降"(更快)与"无标杆场景也能命中"(共享生效)
用法: cd repo && gui-venv311/bin/python tools/eval_motor_hub.py [seed ...]
"""
import json
import os
import sys
from collections import Counter

import numpy as np

os.environ.setdefault('MUJOCO_GL', 'egl')
os.environ.setdefault('DISPLAY', ':0')
ROOT = '/home/ubuntu/lerobot-smolvla-lew'
for _p in (ROOT, os.path.join(ROOT, 'src'), os.path.join(ROOT, 'tools'), os.path.join(ROOT, 'tools', 'gui')):
    sys.path.insert(0, _p)
os.chdir(ROOT)
from state_space_sim_real import RealStateSpaceSim  # noqa: E402

SEEDS = [int(x) for x in sys.argv[1:]] or [7, 9, 11, 12, 104]
MODES = [("base", {"SS_MUSCLE": "0", "SS_MOTOR_HUB": "0"}),
         ("mm", {"SS_MUSCLE": "1", "SS_MOTOR_HUB": "0"}),
         ("mhub", {"SS_MUSCLE": "0", "SS_MOTOR_HUB": "1"})]
FIXED = {"SS_INTENT": "0", "SS_TDEC": "0", "SS_OBSERVE": "0", "SS_SHADOW": "0"}

out = {}
for tag, env in MODES:
    os.environ.update(FIXED)
    os.environ.update(env)
    rows = []
    for sd in SEEDS:
        sim = RealStateSpaceSim(seed=sd, vision=False, mode="insert", log=lambda *a: None)
        tr = sim.run(max_steps=1500)
        done = bool(tr["done"][-1]) if tr.get("done") else False
        st = [str(x).replace("阶段 ", "").split("·")[0].strip() for x in tr.get("stage", [])]
        row = {"seed": sd, "steps": len(tr.get("t", [])), "done": done,
               "mh_hits": int(getattr(sim, "_mh_hits", 0)),
               "mm_hits": int(getattr(sim, "_mm_hits", 0)),
               "seg_frames": dict(Counter(st))}
        rows.append(row)
        print(f"  [{tag}] seed{sd}: {row['steps']}步 done={done} "
              f"基元命中={row['mh_hits']} 标杆命中={row['mm_hits']}", flush=True)
    out[tag] = rows

print("\n=== 汇总 ===")
base_ok = sum(1 for r in out["base"] if r["done"])
for tag in out:
    rs = out[tag]
    ok = sum(1 for r in rs if r["done"])
    hits = sum(r["mh_hits"] + r["mm_hits"] for r in rs)
    print(f"  {tag:5s}: 成功 {ok}/{len(rs)} · 步数均值 {np.mean([r['steps'] for r in rs]):.0f} · "
          f"快通道命中 {hits} 帧" + ("   ⚠️ 回退!" if ok < base_ok else "   (不回退)"))
json.dump(out, open('/tmp/motor_hub_eval.json', 'w'), ensure_ascii=False, indent=1)
print("→ /tmp/motor_hub_eval.json")
