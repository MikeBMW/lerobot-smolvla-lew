#!/usr/bin/env python3
"""探针8: geom 几何 — 夹爪两指/peg 的真实体素尺寸与位置, 闭合后的接触对
"""
import os
os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("MUJOCO_GL", "glfw")
import numpy as np
import metaworld as _mt

mt = _mt.MT1("peg-insert-side-v3")
e = mt.train_classes["peg-insert-side-v3"](render_mode="rgb_array", camera_name="corner2")
e.set_task(mt.train_tasks[0])
e.reset(seed=0)
e._freeze_rand_vec = True
m, d = e.model, e.data

# 列出所有 geom (name/type/size/pos)
print("=== geoms ===", flush=True)
for i in range(m.ngeom):
    try:
        nm = m.geom(i).name
    except Exception:
        nm = f"g{i}"
    if nm and any(k in str(nm).lower() for k in ("peg", "gripper", "finger", "hand", "claw", "pad", "table", "shelf")):
        g = m.geom(i)
        print(f"geom[{i}] {nm}: type={g.type} size={np.round(g.size,4)} pos={np.round(g.pos,4)}", flush=True)

# 全部 geom 名 (看有没有别的关键体)
print("=== 全部 geom 名 ===", flush=True)
names = []
for i in range(m.ngeom):
    try:
        names.append(str(m.geom(i).name))
    except Exception:
        names.append(f"g{i}")
print(names, flush=True)

# 移到销旁闭合, 看接触对
o = np.asarray(e._get_obs(), dtype=np.float64).ravel()
peg = o[4:7].copy()
ee_id = m.site("endEffector").id
for k in range(80):
    ee = d.site_xpos[ee_id]
    dv = np.zeros(4)
    dv[:2] = peg[:2] - ee[:2]
    dv[2] = (peg[2] + 0.002 - ee[2]) * 4
    dv[:3] = np.clip(dv[:3] / 0.03, -1, 1); dv[3] = -1.0
    e.step(dv)
    if np.linalg.norm(ee[:2] - peg[:2]) < 0.003 and abs(ee[2] - peg[2] - 0.002) < 0.005:
        break
for k in range(25):
    e.step(np.array([0.0, 0.0, 0.0, 0.6]))
o = np.asarray(e._get_obs(), dtype=np.float64).ravel()
print(f"闭合后 grp={o[3]:.3f} ncon={d.ncon}", flush=True)
# 接触对 (geom1, geom2)
for c in d.contact[:d.ncon]:
    try:
        g1 = m.geom(c.geom1).name if hasattr(m.geom(c.geom1), "name") else f"g{c.geom1}"
        g2 = m.geom(c.geom2).name if hasattr(m.geom(c.geom2), "name") else f"g{c.geom2}"
    except Exception:
        g1, g2 = c.geom1, c.geom2
    print(f"contact: {g1} <-> {g2} dist={c.dist:.4f}", flush=True)
print("[p8] done", flush=True)
