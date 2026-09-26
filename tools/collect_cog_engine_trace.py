#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""collect_cog_engine_trace.py — 用**引擎自己的轨迹**造事件头训练集 (口径同源, 2026-09-26)

为什么: 闭环取证暴露 rz_H5 闭环 AUC 0.238 (**低于随机**) —— 头是拿 l5_gen_v6 (造数据管线产物) 训的,
  而闭环跑的是引擎 insert/full 轨迹, **不同源**。老倪口径: 训练口径 = 训练同源零回退。
  ⇒ 训练数据必须来自**要运行它的那条流**(引擎 tr 的 obs[0:7])。

产出: {out}.h5  keys: observation(39) / action(4) / ep_idx / variant_id / stage_id / mode
标签在训练时由 obs[0:7] 现算 (与闭环验证**同一函数** event_labels), 保证口径一致。
用法: gui-venv311/bin/python tools/collect_cog_engine_trace.py --episodes 8 --steps 220
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import numpy as np

ROOT = "/home/ubuntu/zmax_rel"
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
sys.path.insert(0, os.path.join(ROOT, "src"))

STAGES8 = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"]


def stage_id(s):
    t = str(s).strip()
    for pre in ("阶段 ", "阶段"):
        if t.startswith(pre):
            t = t[len(pre):].strip()
    return STAGES8.index(t) if t in STAGES8 else -1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=8)
    ap.add_argument("--steps", type=int, default=220)
    ap.add_argument("--out", default="/home/ubuntu/stable-wm-cache/datasets/cog_engine_trace_v1.h5")
    ap.add_argument("--modes", default="insert,full")
    a = ap.parse_args()

    import h5py
    from state_space_sim_real import RealStateSpaceSim                # noqa: PLC0415

    modes = [m.strip() for m in a.modes.split(",") if m.strip()]
    OBS, ACT, EP, ST, MD = [], [], [], [], []
    t0 = time.time()
    for i in range(a.episodes):
        mode = modes[i % len(modes)]
        sim = RealStateSpaceSim(seed=100 + i, vision=False, mode=mode, log=lambda *x: None)
        tr = sim.run(max_steps=a.steps)
        n = len(tr["t"])
        if n == 0:
            print("  段%d (%s): 空轨迹, 跳过" % (i, mode))
            continue
        obs = np.array(tr["obs"], dtype=np.float32)
        act = np.array(tr["u_exec_vec"], dtype=np.float32)[:, :4]
        if act.shape[0] != n:
            act = np.resize(act, (n, act.shape[1]))
        OBS.append(obs)
        ACT.append(act)
        EP.append(np.full(n, i, np.int32))
        ST.append(np.array([stage_id(s) for s in tr["stage"]], np.int32))
        MD.append(np.full(n, modes.index(mode), np.int8))
        print("  段%d/%d mode=%-6s 帧=%-4d 阶段序列=%s 夹爪闭合=%s" %
              (i + 1, a.episodes, mode, n,
               "/".join(dict.fromkeys(str(s) for s in tr["stage"])),
               "有" if (obs[1:, 3] < 0.5).any() and (obs[:-1, 3] >= 0.5).any() else "无"))
    if not OBS:
        print("❌ 没采到任何轨迹"); return 1
    obs_all, act_all = np.concatenate(OBS), np.concatenate(ACT)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with h5py.File(a.out, "w") as f:
        f.create_dataset("observation", data=obs_all)
        f.create_dataset("action", data=act_all)
        f.create_dataset("ep_idx", data=np.concatenate(EP))
        f.create_dataset("stage_id", data=np.concatenate(ST))
        f.create_dataset("mode", data=np.concatenate(MD))
        f.create_dataset("variant_id", data=np.concatenate(EP))     # 与 ep_idx 同 (按段划分留出)
        f.attrs["source"] = "engine trace (state_space_sim_real)"
        f.attrs["modes"] = ",".join(modes)
        f.attrs["ts"] = time.strftime("%F %T")
    print("\n✅ 引擎同源数据集: %s" % a.out)
    print("   帧 %d · 段 %d · 夹爪闭合事件帧 %d · 用时 %.1fs" %
          (len(obs_all), len(OBS), int(((obs_all[1:, 3] < 0.5) & (obs_all[:-1, 3] >= 0.5)).sum()), time.time() - t0))
    print("   阶段分布: %s" % dict(zip(*[x.tolist() for x in np.unique(np.concatenate(ST), return_counts=True)])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
