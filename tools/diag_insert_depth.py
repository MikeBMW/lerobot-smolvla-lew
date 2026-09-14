# -*- coding: utf-8 -*-
"""🔬 diag_insert_depth.py — 解析链"进过插入段却判不完成"的深度取证 (2026-09-15)

背景: 独立进程 A/B 里解析链 3 seed 只有 seed0 done=True。seed1 进过"插入/插入·接触"302 帧
仍未完成。注意 tr["dist"] 在夹持后是 **dh(高度差)**, 不是插入深度 —— 判完成的量是
`_insert_depth()` (光模块头到插入终点距离) < insert_depth(0.002m) 且需连续 2 帧 (_confirm)。
本脚本逐帧记录真实 depth + 阶段 + 接触力, 看在插入段到底到过多少。
用法: MUJOCO_GL=egl gui-venv311/bin/python tools/diag_insert_depth.py --seeds 0,1,2 --steps 600
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

import numpy as np

os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("DISPLAY", ":0")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUI = os.path.join(ROOT, "tools", "gui")
for _p in (ROOT, os.path.join(ROOT, "src"), os.path.join(ROOT, "tools"), GUI):
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.chdir(GUI)
# 🧊 冷记忆隔离 (2026-09-15): 热记忆会让结果随历史漂移; 诊断默认冷口径
os.environ.setdefault("SS_MUSCLE_PATH", "/tmp/diag_mem_%d.json" % os.getpid())
for k, v in (("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache"),
             ("LOCAL_DATASET_DIR", "/home/ubuntu/stable-wm-cache"),
             ("INTACT_RUNTIME", "root"), ("INTACT_POLICY", "intact_l4_current"),
             ("OMP_NUM_THREADS", "6")):
    os.environ.setdefault(k, v)
os.environ.pop("SS_L4_INTACT", None)
os.environ.pop("SS_L4_INTENT_LINE", None)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="0,1,2")
    ap.add_argument("--steps", type=int, default=600)
    a = ap.parse_args()
    for sd in [int(x) for x in a.seeds.split(",") if x.strip()]:
        from state_space_sim_real import RealStateSpaceSim
        sim = RealStateSpaceSim(seed=sd, vision=False, mode="insert", log=lambda *x: None)
        depth_log: list = []
        _orig = sim._insert_depth

        def wrapped(_o=_orig, _l=depth_log):
            v = _o()
            _l.append(None if v is None else float(v))
            return v
        sim._insert_depth = wrapped
        tr = sim.run(max_steps=a.steps)
        stg = [str(s).replace("阶段 ", "") for s in (tr.get("stage") or [])]
        dl = depth_log
        print(f"\n=== seed{sd} === 步数={len(stg)} done={tr.get('done',[False])[-1]} "
              f"阶段={dict(Counter(stg))}")
        ins_idx = [i for i, s in enumerate(stg) if s.startswith("插入")]
        if not dl:
            print("  插入深度函数从未被调用")
        else:
            arr = np.asarray([np.nan if x is None else x for x in dl], float)
            print(f"  depth 采样 {len(arr)} 帧 · 最小 {np.nanmin(arr)*1000:.2f}mm (第 {int(np.nanargmin(arr))} 帧) "
                  f"· 末值 {arr[-1]*1000:.2f}mm · 阈值 2.00mm(引擎 insert_depth=0.002)")
            n_below = int(np.sum(arr < 0.002))
            print(f"  depth < 2mm 的帧数: {n_below} (需连续≥2 帧才 _confirm → {'可触发' if n_below>=2 else '不可能触发'})")
            if ins_idx:
                sub = arr[ins_idx[0]:ins_idx[-1]+1]
                print(f"  插入段({len(sub)} 帧) depth: 起 {sub[0]*1000:.2f}mm 最小 {np.nanmin(sub)*1000:.2f}mm "
                      f"末 {sub[-1]*1000:.2f}mm")
            # 采样打印
            for i in range(0, len(arr), max(1, len(arr)//12)):
                print(f"    帧{i:4d} 阶段={stg[i] if i < len(stg) else '?':10s} depth={arr[i]*1000:8.2f}mm")
        f = np.asarray(tr.get("force") or [], float)
        if f.size:
            print(f"  接触力: 峰值 {np.max(f):.2f} · 插入段峰值 "
                  f"{(np.max(f[ins_idx[0]:ins_idx[-1]+1]) if ins_idx else float('nan')):.2f} · 末值 {f[-1]:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
