#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""target-decoder 闭环验证 — 对照 (真实引擎)

对照:
  base      : SS_TDEC=0                    规则 target (既有基线)
  tdec_next : SS_TDEC=1 SS_TDEC_HEAD=next  学成功轨迹真实运动 (策略版)
  tdec_tgt  : SS_TDEC=1 SS_TDEC_HEAD=target 学规则 target (链路回归版)

红线: 成功率不得回退。指标: 成功率 / 步数 / decoder 命中帧。
用法: cd repo && gui-venv311/bin/python tools/eval_target_decoder.py [seed ...]
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

SEEDS = [int(x) for x in sys.argv[1:]] or [7, 9, 100, 101, 102, 103, 104, 108]
MODES = [("base", {"SS_TDEC": "0"}),
         ("tdec_next", {"SS_TDEC": "1", "SS_TDEC_HEAD": "next"}),
         ("tdec_tgt", {"SS_TDEC": "1", "SS_TDEC_HEAD": "target"})]
FIXED = {"SS_MUSCLE": "0", "SS_INTENT": "0", "SS_OBSERVE": "0", "SS_SHADOW": "0"}

out = {}
for tag, env in MODES:
    os.environ.update(FIXED)
    os.environ.update(env)
    rows = []
    for sd in SEEDS:
        sim = RealStateSpaceSim(seed=sd, vision=False, mode="insert", log=lambda *a: None)
        tr = sim.run(max_steps=1500)
        done = bool(tr["done"][-1]) if tr.get("done") else False
        rows.append({"seed": sd, "steps": len(tr.get("t", [])), "done": done,
                     "tdec_hits": int(getattr(sim, "_tdec_hits", 0))})
        print(f"  [{tag}] seed{sd}: {rows[-1]['steps']}步 done={done} "
              f"dec_hits={rows[-1]['tdec_hits']}", flush=True)
    out[tag] = rows

print("\n=== 汇总 (红线: 成功率不回退) ===")
base_ok = sum(1 for r in out["base"] if r["done"])
for tag in out:
    rs = out[tag]
    ok = sum(1 for r in rs if r["done"])
    print(f"  {tag:10s}: 成功 {ok}/{len(rs)} · 步数均值 {np.mean([r['steps'] for r in rs]):.0f} · "
          f"decoder 命中 {sum(r['tdec_hits'] for r in rs)} 帧"
          + ("   ⚠️ 回退!" if ok < base_ok else ""))
json.dump(out, open('/tmp/target_decoder_eval.json', 'w'), ensure_ascii=False, indent=1)
print("→ /tmp/target_decoder_eval.json")
