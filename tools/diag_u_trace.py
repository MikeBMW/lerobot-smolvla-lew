# -*- coding: utf-8 -*-
"""🔍 diag_u_trace.py — 逐帧看 u 全链路 (ff/fb/exec/sat) 与末端真实位移

上一测结果: direct 臂 u_ff 幅度 **比 analytic 还大 2.3×** (0.122 vs 0.052) 且 L4 真融合
(calls=15 blend=120 w=0.3), 但机器人在 600 帧里逐帧不动 → 矛盾. 必须看 u 全链路与真位移。
用法: MUJOCO_GL=egl gui-venv311/bin/python tools/diag_u_trace.py --seed 0 --steps 60
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

N = int(os.environ.get("DIAG_STEPS", "60"))
for arm, l4 in (("analytic", False), ("direct", True)):
    for k in ("SS_L4_INTACT", "SS_L4_INTENT_LINE", "SS_L4_INTENT_LINE_W"):
        os.environ.pop(k, None)
    if l4:
        os.environ["SS_L4_INTACT"] = "1"
    from state_space_sim_real import RealStateSpaceSim
    from lerobot.manifold.intact_node import IntactNode, IntactRuntime
    sim = RealStateSpaceSim(seed=0, vision=False, mode="insert", log=lambda *x: None)
    sim.attach_intact(IntactNode(horizon=8, runtime=IntactRuntime(task="pusht", device="cpu")))
    tr = sim.run(max_steps=N)

    def A(k, d=3):
        v = [u for u in tr.get(k) or [] if u is not None]
        return np.asarray(v, float).reshape(len(v), -1)[:, :d] if v else np.zeros((0, d))

    x = np.asarray(tr.get("x") or [], float).reshape(-1, 3)
    uff, uex, usat = A("u_ff_vec"), A("u_exec_vec"), A("u_sat_vec")
    print(f"\n=== {arm} ===")
    if x.size:
        print(f"  末端位移 Δx = {(x[-1]-x[0]).round(5).tolist()} · |Δx| = {np.linalg.norm(x[-1]-x[0]):.5f} m "
              f"· x 逐帧变化量均值 {np.abs(np.diff(x, axis=0)).mean():.6f}")
    print(f"  u_ff 前5帧 |u|: {np.abs(uff[:5]).round(4).tolist() if uff.size else '—'}")
    print(f"  u_ff 后5帧 |u|: {np.abs(uff[-5:]).round(4).tolist() if uff.size else '—'}")
    print(f"  u_sat 后5帧   : {usat[-5:].round(4).tolist() if usat.size else '—'}")
    print(f"  逐帧 signed 和 (x/y/z) 后5帧: {usat[-5:].sum(axis=0).round(4).tolist() if usat.size else '—'}")
    for k in ("u_limit_vec", "u_fb_vec", "u_fuse_vec"):
        v = A(k)
        if v.size:
            print(f"  {k}: 后5帧 {v[-5:].round(4).tolist()}")
    stg = [str(s).replace("阶段 ", "") for s in (tr.get("stage") or [])]
    print(f"  阶段序列(唯一): {sorted(set(stg))} · 帧数 {len(stg)}")
