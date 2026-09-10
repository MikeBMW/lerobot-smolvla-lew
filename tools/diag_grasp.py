#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓取鲁棒性诊断 — 为什么 seed11/12 那类场景抓不住 (阶段循环的根因)

输出每轮"抓取"尝试的: 手-模块最近距离 / 夹爪闭合时机 / 结束时是否抓住 / 失败模式分类。
失败模式:
  · 没到位   : hand-peg 最近距离 > 阈值 (夹爪没伸到模块上)
  · 时机不对 : 到位了但夹爪闭合时不在正确位置 (闭合过早/过晚)
  · 抓了滑脱 : 段末 grasped=True 但后续又变 False
  · 位置偏差 : 到位但 xy 偏移大 (侧向顶住)
用法: cd repo && gui-venv311/bin/python tools/diag_grasp.py [seed ...]
"""
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


def seg_runs(st, name):
    """连续 stage==name 的区间 [start, end]"""
    runs, cur = [], None
    for i, s in enumerate(st):
        if s == name:
            cur = [i, i] if cur is None else [cur[0], i]
        elif cur is not None:
            runs.append(tuple(cur))
            cur = None
    if cur:
        runs.append(tuple(cur))
    return runs


for sd in [int(x) for x in sys.argv[1:]] or [11, 12, 7, 9]:
    sim = RealStateSpaceSim(seed=sd, vision=False, mode="insert", log=lambda *a: None)
    tr = sim.run(max_steps=1500)
    st = [str(x).replace("阶段 ", "").split("·")[0].strip() for x in tr.get("stage", [])]
    X = np.asarray(tr.get("x", []), float)
    P = np.asarray(tr.get("peg", []), float)
    G = np.asarray(tr.get("grasped", []), bool)
    GR = np.asarray(tr.get("gripper", []), float)
    done = bool(tr["done"][-1]) if tr.get("done") else False
    gr = seg_runs(st, "抓取")
    print(f"\n=== seed{sd} | {len(st)}步 done={done} | 抓取尝试 {len(gr)} 轮 · "
          f"最终 grasped={G[-1] if len(G) else '?'}")
    for k, (a, b) in enumerate(gr[:8]):
        n = min(len(X), len(P))
        d = np.linalg.norm(X[a:min(b + 1, n)] - P[a:min(b + 1, n)], axis=1) * 1000
        dmin = float(d.min()) if d.size else -1
        dxy = float(np.linalg.norm((X[a:min(b + 1, n)] - P[a:min(b + 1, n)])[:, :2], axis=1).min() * 1000) \
            if d.size else -1
        g_end = bool(G[b]) if b < len(G) else None
        mode = ("没到位(>30mm)" if dmin > 30 else
                "侧向偏差(>15mm)" if dxy > 15 else
                "到位" if g_end else "时机/夹持失败")
        print(f"   轮{k}: 帧{a}-{b} ({b-a+1}帧) hand-peg最近 {dmin:.1f}mm · xy最近 {dxy:.1f}mm · "
              f"末端grasped={g_end} · 夹爪 {GR[a]:.2f}→{GR[b]:.2f}  → {mode}")
    # 抓住后又掉的次数
    if len(G):
        drops = int(np.sum((G[:-1]) & (~G[1:])))
        print(f"   抓住后掉落次数: {drops}")
