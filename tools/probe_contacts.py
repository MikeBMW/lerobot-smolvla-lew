#!/usr/bin/env python3
"""🔬 metaworld 接触对诊断 — 抬起/转移阶段到底谁在接触谁 (按 body 名字打出来)

用法: MUJOCO_GL=egl gui-venv311/bin/python tools/probe_contacts.py
"""
import os
import sys
from collections import defaultdict

os.environ.setdefault("MUJOCO_GL", "egl")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))

import numpy as np  # noqa: E402
import mujoco  # noqa: E402
from train_full_pipeline import make_env, get_obs  # noqa: E402

env = make_env(0)
m, d = env.model, env.data
env.max_path_length = 3000
print("=== 与夹爪/光模块相关的 body 名 ===")
for i in range(m.nbody):
    nm = m.body(i).name
    if any(k in nm.lower() for k in ("hand", "claw", "peg", "box", "table", "gripper", "finger")):
        print(f"  id={i:<3} {nm}")

peg_id = int(m.body("peg").id)
o = get_obs(env)
peg_z0 = float(d.site_xpos[m.site("pegGrasp").id][2])

# 简易脚本策略: 对位 → 下降 → 闭爪 → 抬起 (只为造出"夹着光模块悬空"的状态)
pair_force = defaultdict(float)
pair_cnt = defaultdict(int)
phase_log = []
for step in range(1400):
    hand = o[0:3]
    peg = np.array(d.site_xpos[m.site("pegGrasp").id])
    lifted = float(peg[2] - peg_z0)
    act = np.zeros(4)
    d_xy = float(np.linalg.norm(hand[:2] - peg[:2]))
    target_z = peg[2] + 0.022
    if d_xy > 0.02:                      # 水平对位
        act[:2] = np.clip((peg[:2] - hand[:2]) * 8, -1, 1)
        act[3] = -1.0
        ph = "对位"
    elif hand[2] - target_z > 0.004:     # 下降
        act[2] = -0.6
        act[3] = -1.0
        ph = "下降"
    elif step % 1 == 0 and lifted < 0.10:  # 闭爪 + 抬起
        act[3] = 1.0
        act[2] = 0.6 if step > 700 else 0.0
        ph = "抓取/抬起"
    else:
        act[3] = 1.0
        act[:2] = np.clip((np.array([-0.17, 0.46]) - hand[:2]) * 6, -1, 1)  # 往孔位转移
        ph = "转移"
    env.step(act)
    o = get_obs(env)
    if step > 700 and step % 50 == 0:    # 只统计"夹着销"之后的接触
        f6 = np.zeros(6)
        for i in range(d.ncon):
            c = d.contact[i]
            b1, b2 = int(m.geom_bodyid[c.geom1]), int(m.geom_bodyid[c.geom2])
            mujoco.mj_contactForce(m, d, i, f6)
            mag = float(np.linalg.norm(f6[:3]))
            n1 = m.body(b1).name or f"body{b1}"
            n2 = m.body(b2).name or f"body{b2}"
            key = tuple(sorted([n1, n2]))
            pair_force[key] += mag
            pair_cnt[key] += 1
        phase_log.append((step, ph, lifted, d.ncon))

print(f"\n=== 抽样阶段 (step, 相位, 提起高度, 接触数) ===")
for s, ph, lf, nc in phase_log[:12]:
    print(f"  step {s:<5} {ph:<8} lifted={lf:+.4f}m  ncon={nc}")

print(f"\n=== 夹着光模块之后的接触对 (按累计力排序) ===")
print(f"{'body 对':<44} {'累计力N':>10} {'出现次数':>8}")
for k, v in sorted(pair_force.items(), key=lambda kv: -kv[1])[:12]:
    tag = "  ← 含 peg" if "peg" in k else ""
    print(f"{str(k):<44} {v:10.2f} {pair_cnt[k]:8d}{tag}")
env.close()
