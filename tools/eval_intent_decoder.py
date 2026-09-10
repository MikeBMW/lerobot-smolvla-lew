#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""意图直读 decoder 验证 — 对照实验 (真实引擎, 零训练)

对照:
  base   : SS_MUSCLE=0 SS_INTENT=0  纯实时决策 (现有能力基线)
  intent : SS_MUSCLE=0 SS_INTENT=1  意图直读接管前馈槽位 (L2 三件套不动)

指标: 成功率 / 总步数 / 意图命中帧数 (int_hits) / 前馈接管段
关键点: 在**没有标杆的新场景**上也能生效 = 能力跨场景共享 (旧快通道按 seed 查, 新场景必失效)。

用法: cd repo && MUJOCO_GL=egl gui-venv311/bin/python tools/eval_intent_decoder.py [seed ...]
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

SEEDS = [int(x) for x in sys.argv[1:]] or [7, 9, 11, 12]
MODES = [("base", {"SS_MUSCLE": "0", "SS_INTENT": "0"}),
         ("intent", {"SS_MUSCLE": "0", "SS_INTENT": "1"})]
FIXED = {"SS_OBSERVE": "0", "SS_SHADOW": "0"}   # 不写记忆/不跑影子, 保证对照干净

out = {}
for tag, env in MODES:
    os.environ.update(FIXED)
    os.environ.update(env)
    rows = []
    for sd in SEEDS:
        sim = RealStateSpaceSim(seed=sd, vision=False, mode="insert", log=lambda *a: None)
        tr = sim.run(max_steps=1500)
        done = bool(tr["done"][-1]) if tr.get("done") else False
        n = len(tr.get("t", []))
        row = {"seed": sd, "steps": n, "done": done,
               "int_hits": int(getattr(sim, "_int_hits", 0)),
               "mm_hits": int(getattr(sim, "_mm_hits", 0)),
               "lib": (sim._intent_dec.summary() if getattr(sim, "_intent_dec", None) else None)}
        rows.append(row)
        print(f"  [{tag}] seed{sd}: {n}步 done={done} "
              f"int_hits={row['int_hits']} mm_hits={row['mm_hits']}", flush=True)
    out[tag] = rows

print("\n=== 汇总 ===")
for tag in out:
    rs = out[tag]
    ok = sum(1 for r in rs if r["done"])
    print(f"  {tag:7s}: 成功 {ok}/{len(rs)} · 步数均值 "
          f"{np.mean([r['steps'] for r in rs]):.0f} · 意图命中帧 "
          f"{sum(r['int_hits'] for r in rs)}")
json.dump(out, open('/tmp/intent_decoder_eval.json', 'w'), ensure_ascii=False, indent=1)
print("→ /tmp/intent_decoder_eval.json")
