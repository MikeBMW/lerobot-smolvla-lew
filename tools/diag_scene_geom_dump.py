#!/usr/bin/env python3
"""看一眼 metaworld 场景的真实几何: 盒子/孔/光模块 各是什么几何体, 孔在哪, 尺寸多少

用途: 判断"光模块最后没插进槽"到底是物理没进去, 还是渲染/几何理解偏差。
跑法: DISPLAY=:0 gui-venv311/bin/python tools/diag_scene_geom_dump.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("MUJOCO_GL", "glfw")
sys.path.insert(0, os.path.join(HERE, "gui"))

import numpy as np                                       # noqa: E402
import state_space_sim_real as ssr                       # noqa: E402

env = ssr._make_env()
env.reset()
m, d = env.model, env.data

print("=== 站点 ===")
for name in ("hole", "goal", "peg", "hand", "gripper"):
    try:
        sid = m.site(name).id
        print(f"  site {name:8s} = {np.round(d.site_xpos[sid], 4)}")
    except Exception as e:
        print(f"  site {name}: 无 ({type(e).__name__})")

print("\n=== body 及其几何体 (世界位置/尺寸) ===")
for bn in ("box", "peg", "hand", "gripper", "box_hole", "hole"):
    try:
        bid = m.body(bn).id
    except Exception:
        continue
    print(f"  body {bn}: 世界位置 {np.round(d.xpos[bid], 4)}  四元数 {np.round(d.xquat[bid], 3)}")
    for gi in range(m.body_geomadr[bid], m.body_geomadr[bid] + m.body_geomnum[bid]):
        gtype = int(m.geom_type[gi])
        tname = {2: "sphere", 3: "capsule", 4: "ellipsoid", 5: "cylinder", 6: "box",
                 7: "mesh", 0: "plane", 1: "hfield"}.get(gtype, str(gtype))
        print(f"      geom#{gi} {tname:9s} size={np.round(m.geom_size[gi], 4)}"
              f" pos(局部)={np.round(m.geom_pos[gi], 4)} rgba={np.round(m.geom_rgba[gi], 2)}"
              f" 世界位置={np.round(d.geom_xpos[gi], 4)}")

print("\n=== 盒子附近的所有 body (找出孔/槽是怎么建的) ===")
for bid in range(m.nbody):
    p = np.round(d.xpos[bid], 4)
    if abs(p[0] + 0.2) < 0.15 and abs(p[1] - 0.42) < 0.15 and abs(p[2] - 0.1) < 0.2:
        nm = m.body(bid).name
        ng = m.body_geomnum[bid]
        print(f"  body#{bid} {nm!r:22s} 世界 {p} geoms={ng}")
        for gi in range(m.body_geomadr[bid], m.body_geomadr[bid] + ng):
            tname = {2: "sphere", 3: "capsule", 4: "ellipsoid", 5: "cylinder", 6: "box",
                     7: "mesh"}.get(int(m.geom_type[gi]), "?" )
            print(f"        {tname:8s} size={np.round(m.geom_size[gi], 4)}"
                  f" pos={np.round(m.geom_pos[gi], 4)} 世界={np.round(d.geom_xpos[gi], 4)}")
sys.exit(0)
