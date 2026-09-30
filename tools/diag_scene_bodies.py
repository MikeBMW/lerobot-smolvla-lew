#!/usr/bin/env python3
"""把场景里所有 body/geom 列清楚: 哪个是"带孔块"(可见网格+碰撞), 那两个 3cm 立柱到底属于谁

目的: 弄清"插槽"(可视带孔块) 与 光模块/孔口站点 在世界坐标里是否真在同一位置。
跑法: DISPLAY=:0 gui-venv311/bin/python tools/diag_scene_bodies.py [--seed 104]
"""
import argparse
import os
import sys

os.environ.setdefault("DISPLAY", ":0")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "gui"))

import numpy as np                                       # noqa: E402
import state_space_sim_real as ssr                       # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--seed", type=int, default=104)
a = ap.parse_args()

sim = ssr.RealStateSpaceSim(log=lambda *x: None, seed=a.seed, vision=False, mode="insert")
sim._reset(a.seed)
m, d = sim.env.model, sim.env.data

TYPE = {0: "plane", 1: "hfield", 2: "sphere", 3: "capsule", 4: "ellipsoid",
        5: "cylinder", 6: "box", 7: "mesh"}

print(f"nbody={m.nbody} ngeom={m.ngeom}")
print("\n=== 所有 body (名字/世界位置/几何体数) ===")
for bid in range(m.nbody):
    ng = int(m.body_geomnum[bid])
    nm = m.body(bid).name
    p = np.asarray(d.xpos[bid], float)
    if ng == 0 and not nm:
        continue
    print(f"body#{bid:3d} {nm!r:22s} 世界 {np.round(p, 4)} geoms={ng}"
          f" parent={int(m.body_parentid[bid])}")

print("\n=== 所有 3cm 立柱 box (size[0]≈0.03) 归属 ===")
for g in range(m.ngeom):
    sz = np.asarray(m.geom_size[g], float)
    if int(m.geom_type[g]) == 6 and abs(sz[0] - 0.03) < 1e-6:
        bod = int(m.geom_bodyid[g])
        print(f"  geom#{g} 世界 {np.round(d.geom_xpos[g], 4)} 半尺寸 {np.round(sz, 4)}"
              f" → body#{bod} {m.body(bod).name!r} (父 {int(m.body_parentid[bod])})"
              f" rgba {np.round(m.geom_rgba[g], 2)} contype={int(m.geom_contype[g])}")

print("\n=== 所有 mesh geom (可见块体) ===")
for g in range(m.ngeom):
    if int(m.geom_type[g]) == 7:
        bod = int(m.geom_bodyid[g])
        print(f"  geom#{g} 世界 {np.round(d.geom_xpos[g], 4)} 半尺寸 {np.round(m.geom_size[g], 4)}"
              f" → body#{bod} {m.body(bod).name!r} rgba {np.round(m.geom_rgba[g], 2)}")

print("\n=== 站点 (孔口/终点/光模块头/夹爪) ===")
for nm in ("hole", "goal", "pegHead", "pegEnd", "pegGrasp"):
    try:
        sid = m.site(nm).id
        print(f"  site {nm:9s} 世界 {np.round(d.site_xpos[sid], 4)}"
              f" rgba {np.round(m.site_rgba[sid], 2)}")
    except Exception as e:
        print(f"  site {nm}: 无 ({type(e).__name__})")
print("\n引擎 geom 记录:")
for k, v in (sim.geom or {}).items():
    if isinstance(v, np.ndarray):
        print(f"  {k:10s} {np.round(v, 4)}")
sys.exit(0)
