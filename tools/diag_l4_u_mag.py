# -*- coding: utf-8 -*-
"""🔍 diag_l4_u_mag.py — 诊断"直驱档机器人完全不动" (2026-09-15)

实测 (diag_stage_gate.py): direct 臂 600 帧 d_xy/dh 逐帧完全不变 (130.0/-100.0),
阶段恒为"接近"; 而 analytic 臂 46 帧就进对位、260 帧进插入 → **直驱档等于冻结执行**。
本脚本测每个臂真实下发的 u 幅度 + L4 融合权重, 定位是不是 L4 decoder 输出≈0 把 u_ff 拉平。
用法: MUJOCO_GL=egl gui-venv311/bin/python tools/diag_l4_u_mag.py --seed 0 --steps 120
"""
from __future__ import annotations

import os
import sys

import numpy as np

os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("DISPLAY", ":0")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUI = os.path.join(ROOT, "tools", "gui")
for _p in (ROOT, os.path.join(ROOT, "src"), os.path.join(ROOT, "tools"), GUI):
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.chdir(GUI)
for k, v in (("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache"),
             ("LOCAL_DATASET_DIR", "/home/ubuntu/stable-wm-cache"),
             ("INTACT_RUNTIME", "root"), ("INTACT_POLICY", "intact_l4_current"),
             ("OMP_NUM_THREADS", "6")):
    os.environ.setdefault(k, v)

for arm, l4, line in (("analytic", False, False), ("direct", True, False), ("line_w1", True, True)):
    for k in ("SS_L4_INTACT", "SS_L4_INTENT_LINE", "SS_L4_INTENT_LINE_W", "SS_L4_INTACT_STAGES"):
        os.environ.pop(k, None)
    if l4:
        os.environ["SS_L4_INTACT"] = "1"
    if line:
        os.environ["SS_L4_INTENT_LINE"] = "1"
        os.environ["SS_L4_INTENT_LINE_W"] = "1"
    from state_space_sim_real import RealStateSpaceSim
    from lerobot.manifold.intact_node import IntactNode, IntactRuntime
    sim = RealStateSpaceSim(seed=0, vision=False, mode="insert", log=lambda *x: None)
    sim.attach_intact(IntactNode(horizon=8, runtime=IntactRuntime(task="pusht", device="cpu")))
    tr = sim.run(max_steps=120)
    uff = np.asarray([u for u in tr.get("u_ff_vec") or [] if u is not None], float)
    uex = np.asarray([u for u in tr.get("u_exec_vec") or [] if u is not None], float)
    l4s = sim.l4_intact_summary() if hasattr(sim, "l4_intact_summary") else {}
    ils = sim.l4_intent_line_summary()
    print(f"\n=== {arm} ===")
    if uff.size:
        print(f"  u_ff  : 均值|x,y,z|={np.abs(uff[:, :3]).mean(axis=0).round(5).tolist()} "
              f"|u|均值={np.abs(uff[:, :3]).mean():.5f} 逐帧|u|范围[{np.abs(uff[:, :3]).sum(1).min():.4f},"
              f"{np.abs(uff[:, :3]).sum(1).max():.4f}]")
    if uex.size:
        print(f"  u_exec: |u|均值={np.abs(uex[:, :3]).mean():.5f}")
    print(f"  L4  直驱: calls={l4s.get('calls')} blend={l4s.get('blend')} w_zero={l4s.get('w_zero')} "
          f"refused={l4s.get('refused')} w={l4s.get('w')} src={l4s.get('src')} "
          f"u_ff_src={(l4s.get('u_ff') or {}).get('u_ff_src') if isinstance(l4s.get('u_ff'), dict) else l4s.get('u_ff_src')}")
    print(f"  直连线: ran={ils['ran']} applied={ils['applied']} w_last={ils['w_last']} "
          f"by_stage={ils['by_stage']} intent_gain={ils['intent_gain_mean']}")
