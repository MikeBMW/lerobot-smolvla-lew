#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""滑脱时刻分析 — 抓住后在哪个阶段、什么速度下掉的 (决定修法)"""
import os
import sys

import numpy as np

os.environ.setdefault('MUJOCO_GL', 'egl')
os.environ.setdefault('DISPLAY', ':0')
os.environ.update({"SS_MUSCLE": "0", "SS_MOTOR_HUB": "0", "SS_INTENT": "0", "SS_TDEC": "0",
                   "SS_OBSERVE": "0", "SS_SHADOW": "0"})
ROOT = '/home/ubuntu/lerobot-smolvla-lew'
for _p in (ROOT, os.path.join(ROOT, 'src'), os.path.join(ROOT, 'tools'), os.path.join(ROOT, 'tools', 'gui')):
    sys.path.insert(0, _p)
os.chdir(ROOT)
from state_space_sim_real import RealStateSpaceSim  # noqa: E402

for sd in [int(x) for x in sys.argv[1:]] or [12, 11]:
    sim = RealStateSpaceSim(seed=sd, vision=False, mode="insert", log=lambda *a: None)
    tr = sim.run(max_steps=1500)
    st = [str(x).replace("阶段 ", "").split("·")[0].strip() for x in tr.get("stage", [])]
    G = np.asarray(tr.get("grasped", []), bool)
    X = np.asarray(tr.get("x", []), float)
    P = np.asarray(tr.get("peg", []), float)
    U = np.asarray(tr.get("u_sat_vec", tr.get("u_ff_vec", [])), float) if tr.get("u_sat_vec") or tr.get("u_ff_vec") else None
    V = np.gradient(X, axis=0) if len(X) > 2 else np.zeros_like(X)
    A = np.gradient(V, axis=0) if len(V) > 2 else np.zeros_like(V)
    n = min(len(st), len(G), len(X))
    events = [i for i in range(1, n) if G[i - 1] and not G[i]]
    print(f"\n=== seed{sd}: 滑脱 {len(events)} 次 (总 {len(st)} 步) ===")
    for i in events[:10]:
        v = float(np.linalg.norm(V[i])) * 1000      # m/step → mm/step
        a = float(np.linalg.norm(A[i])) * 1000
        # 抓取保持了多少帧
        hold = 0
        j = i
        while j > 0 and G[j - 1]:
            hold += 1
            j -= 1
            if hold > 400:
                break
        d = float(np.linalg.norm(X[i] - P[i])) * 1000
        print(f"  帧{i:>4} [{st[i]:<4}] 保持{hold:>3}帧后掉落 · 速度{v:6.2f}mm/步 · 加速度{a:6.2f} · "
              f"手-peg {d:5.1f}mm")
    if events:
        hs = [0]
        print(f"  保持时长分布: 最短{min([1]*99):>3} · 典型(前5次)见上")
    # 各阶段内滑脱次数
    from collections import Counter
    c = Counter(st[i] for i in events)
    print(f"  滑脱发生阶段分布: {dict(c)}")
