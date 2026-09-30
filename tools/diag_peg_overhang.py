# -*- coding: utf-8 -*-
"""🔬 diag_peg_overhang.py — peg(240mm 胶囊) 在台面边界上是否悬空 (解释 seed2 抓不稳) 2026-09-15

已证: peg = capsule r=15mm 半长 120mm (240mm 长杆), 抓取目标=body 原点(胶囊中心)。
seed 只改 peg 初始 x: seed0 0.122 / seed1 0.027 / seed2 0.0019 → 若台面在 x≈0 处结束,
seed2 的杆有一半悬在台外 → 夹爪夹中段时杆受力矩 → 抬升即滑 (与实测一致: seed2 滑 13 次)。
本脚本读模型所有 geom 的世界范围 (台面/箱体) 与 peg 杆两端世界坐标, 直接算悬空量。
用法: MUJOCO_GL=egl gui-venv311/bin/python tools/diag_peg_overhang.py --seeds 0,1,2
"""
from __future__ import annotations

import argparse
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="0,1,2")
    a = ap.parse_args()
    from state_space_sim_real import RealStateSpaceSim
    sim = RealStateSpaceSim(seed=0, vision=False, mode="insert", log=lambda *x: None)
    sim._reset(0)
    m, d = sim.env.model, sim.env.data
    print("世界 geom 清单 (非 peg, 看台面/箱体范围):")
    for gid in range(m.ngeom):
        bn = m.body(int(m.geom_bodyid[gid])).name
        if bn == "peg":
            continue
        p = np.asarray(d.geom_xpos[gid], float)
        sz = np.asarray(m.geom_size[gid], float)
        if float(p[2]) < 0.06:      # 低位物件 = 台面/箱/孔
            print(f"  [{gid}] body={bn:12s} type={int(m.geom_type[gid])} "
                  f"xpos={np.round(p,4).tolist()} size={np.round(sz,4).tolist()}")
    pbi = int(m.body("peg").id)
    gj = [gid for gid in range(m.ngeom) if int(m.geom_bodyid[gid]) == pbi]
    print(f"\npeg geom: {gj}")
    for sd in [int(x) for x in a.seeds.split(",")]:
        sim2 = RealStateSpaceSim(seed=sd, vision=False, mode="insert", log=lambda *x: None)
        sim2._reset(sd)
        m2, d2 = sim2.env.model, sim2.env.data
        g = gj[0]
        pos = np.asarray(d2.geom_xpos[g], float)
        xmat = np.asarray(d2.geom_xmat[g], float).reshape(3, 3)
        half = float(m2.geom_size[g][2])
        axis = xmat[:, 2]                      # capsule 轴向 (local z)
        e1, e2 = pos - axis * half, pos + axis * half
        print(f"=== seed{sd} === peg 中心={np.round(pos,4).tolist()} 轴={np.round(axis,3).tolist()}")
        print(f"    杆两端世界坐标: {np.round(e1,4).tolist()} → {np.round(e2,4).tolist()}")
        print(f"    x 范围 [{min(e1[0],e2[0]):.4f}, {max(e1[0],e2[0]):.4f}] "
              f"· z 范围 [{min(e1[2],e2[2]):.4f}, {max(e1[2],e2[2]):.4f}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
