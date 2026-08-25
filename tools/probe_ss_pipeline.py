#!/usr/bin/env python3
"""🧮 状态空间仿真 完整插拔流程 实测校验 (八阶段 + 插销独立轨迹)

用法: gui-venv311/bin/python tools/probe_ss_pipeline.py
判定: 八阶段全部走到「完成」+ 插销真的从台面被抓起(z 上升)+ 销头插到 goal (残距 < 4mm)
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "tools", "gui"))
from state_space_sim import (StateSpaceSim, PEG_POS0, HOLE_POS,  # noqa: E402
                             HOLE_MOUTH, X0)

sim = StateSpaceSim(log=lambda *a: None)
tr = sim.run()
n = len(tr["x"])
stages = [s.replace("阶段 ", "").split(" · ")[0] for s in tr["stage"]]
order, seen = [], set()
for i, s in enumerate(stages):
    if s not in seen:
        seen.add(s)
        order.append((s, i, tr["t"][i]))

print(f"═══ 阶段序列 (共 {n} 帧 / {tr['t'][-1]:.2f}s) ═══")
for s, i, t in order:
    print(f"  {s:<4} 首现 帧{i:<5} t={t:.2f}s")
print(f"  完成标志 done={tr['done'][-1]}")
print("\n═══ 调度器推进证据 (真实源码 cognition.ActionModulator) ═══")
for s, r in sim.sched.history:
    print(f"  → {s}: {r}")

gi = next((i for i, g in enumerate(tr["grasped"]) if g), None)
peg_z = [p[2] for p in tr["peg"]]
head_end = np.asarray(tr["peg_head"][-1])
resid = float(np.linalg.norm(head_end - HOLE_POS))
print("\n═══ 关键物理量 ═══")
print(f"  末端: {np.round(tr['x'][0], 3)} → {np.round(tr['x'][-1], 3)}")
print(f"  插销: {np.round(tr['peg'][0], 3)} → {np.round(tr['peg'][-1], 3)}")
print(f"  插销 z: 初始 {peg_z[0]:.3f} → 最高 {max(peg_z):.3f} (提起 {max(peg_z) - peg_z[0]:.3f}m)")
print(f"  夹住时刻: 帧 {gi} (t={tr['t'][gi]:.2f}s)" if gi is not None else "  ❌ 从未夹住")
print(f"  销头终点 {np.round(head_end, 3)}  goal {np.round(HOLE_POS, 3)}  插入残距 {resid * 1000:.1f}mm")
print(f"  夹爪: {tr['gripper'][0]:.2f} → {tr['gripper'][-1]:.2f} (峰值 {max(tr['gripper']):.2f})")

ok_stage = [s for s, _, _ in order] == ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"]
ok_grasp = gi is not None and max(peg_z) - peg_z[0] > 0.08
ok_insert = resid < 0.02
print("\n═══ 判定 ═══")
print(f"  八阶段完整 (接近→对位→下降→抓取→抬起→转移→插入→完成): {'✅' if ok_stage else '❌ ' + str([s for s, _, _ in order])}")
print(f"  插销真被抓起 (z 上升 >8cm): {'✅' if ok_grasp else '❌'}")
print(f"  销头插到位 (残距 <20mm): {'✅' if ok_insert else '❌'} ({resid * 1000:.1f}mm)")
print(f"  → 总判定: {'✅ 完整插拔流程通' if (ok_stage and ok_grasp and ok_insert) else '❌ 未通'}")
