#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v9 (SmolVLA-Lew) 引擎内 L3 闭环评估 — 同源观测/语言/图像

对照:
  base : SS_L3=0                       解析伺服链 (既有基线, 生产默认)
  l3   : SS_L3=1 SS_L3_EVERY=4         v9 出 xyz (夹爪仍由状态机管)

同源保证 (这是之前外部 rollout 脚本失败的原因):
  · state : 引擎构造 39D (visual39) — 与训练采集完全同源
            (⚠️ env._get_obs() 是另一套语义: [4:7]=peg, 引擎 [4:7]=速度)
  · image : 128×128 LANCZOS — 同训练
  · task  : "peg-insert-side-v3" — 同训练数据集 tasks.parquet
用法: cd repo && gui-venv311/bin/python tools/eval_l3_engine.py [seed ...]
"""
import json
import os
import sys

import numpy as np

os.environ.setdefault('MUJOCO_GL', 'egl')
os.environ.setdefault('DISPLAY', ':0')
ROOT = '/home/ubuntu/lerobot-smolvla-lew'
for p in (ROOT, os.path.join(ROOT, 'src'), os.path.join(ROOT, 'tools'), os.path.join(ROOT, 'tools', 'gui')):
    sys.path.insert(0, p)
os.chdir(ROOT)
from state_space_sim_real import RealStateSpaceSim  # noqa: E402

SEEDS = [int(x) for x in sys.argv[1:]] or [7, 9, 101, 102, 103, 104, 108]
MODES = [("base", {"SS_L3": "0"}),
         ("l3", {"SS_L3": "1", "SS_L3_EVERY": "4"})]
FIXED = {"SS_MUSCLE": "0", "SS_INTENT": "0", "SS_TDEC": "0", "SS_OBSERVE": "0", "SS_SHADOW": "0"}
out = {}
for tag, env in MODES:
    os.environ.update(FIXED)
    os.environ.update(env)
    rows = []
    for sd in SEEDS:
        sim = RealStateSpaceSim(seed=sd, vision=False, mode="insert", log=lambda *a: None)
        tr = sim.run(max_steps=1200)
        done = bool(tr["done"][-1]) if tr.get("done") else False
        rows.append({"seed": sd, "steps": len(tr.get("t", [])), "done": done})
        print(f"  [{tag}] seed{sd}: {rows[-1]['steps']}步 done={done}", flush=True)
    out[tag] = rows
print("\n=== 汇总 ===")
base_ok = sum(1 for r in out["base"] if r["done"])
for tag in out:
    rs = out[tag]
    ok = sum(1 for r in rs if r["done"])
    print(f"  {tag:5s}: 成功 {ok}/{len(rs)} · 步数均值 {np.mean([r['steps'] for r in rs]):.0f}"
          + ("   ⚠️ 回退" if ok < base_ok else "   (不回退)"))
json.dump(out, open('/tmp/l3_engine_eval.json', 'w'), ensure_ascii=False, indent=1)
