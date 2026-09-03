#!/usr/bin/env python3
"""探针10: 抬升瞬间 接触对消失时序 — 夹持是否建立 / 何时滑脱
"""
import os
os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("MUJOCO_GL", "glfw")
import numpy as np
import metaworld as _mt

mt = _mt.MT1("peg-insert-side-v3")
e = mt.train_classes["peg-insert-side-v3"](render_mode="rgb_array", camera_name="corner2")
e.set_task(mt.train_tasks[0])
m, d = e.model, e.data
ee_id = m.site("endEffector").id
def P(n): return d.site_xpos[m.site(n).id].copy()
def contacts():
    out = []
    for c in d.contact[:d.ncon]:
        try:
            g1 = m.geom(c.geom1).name or f"g{c.geom1}"
            g2 = m.geom(c.geom2).name or f"g{c.geom2}"
        except Exception:
            g1, g2 = f"g{c.geom1}", f"g{c.geom2}"
        out.append(f"{g1}|{g2}")
    return out

e.reset(seed=0); e._freeze_rand_vec = True
o = np.asarray(e._get_obs(), dtype=np.float64).ravel()
# 悬停→垂直下降(实时对准)
for k in range(90):
    o = np.asarray(e._get_obs(), dtype=np.float64).ravel()
    ee = P("endEffector"); peg = o[4:7]
    dv = np.zeros(4)
    dv[:2] = peg[:2] - ee[:2]
    dv[2] = (peg[2] + 0.000 - ee[2]) * 5
    dv[:3] = np.clip(dv[:3] / 0.025, -1, 1); dv[3] = -1.0
    e.step(dv)
    if np.linalg.norm(ee[:2] - peg[:2]) < 0.002 and abs(ee[2] - peg[2]) < 0.003:
        break
o = np.asarray(e._get_obs(), dtype=np.float64).ravel()
print(f"[p10] 到位 ee={np.round(P('endEffector'),4)} peg={np.round(o[4:7],4)}", flush=True)
# 闭合(每步看接触何时出现)
for k in range(30):
    e.step(np.array([0.0, 0.0, 0.0, 0.8]))
    o = np.asarray(e._get_obs(), dtype=np.float64).ravel()
    cs = contacts()
    peg_c = [c for c in cs if "peg" in c]
    if k in (0, 2, 5, 8, 12, 20, 29):
        print(f"[p10] 闭{k+1} grp={o[3]:.3f} 接触={len(cs)} peg接触={len(peg_c)}", flush=True)
    if len(peg_c) >= 4:
        print(f"[p10] 闭{k+1} 首次≥4 peg接触 grp={o[3]:.3f}", flush=True)
        break
o = np.asarray(e._get_obs(), dtype=np.float64).ravel()
peg_b = o[4:7].copy()
# 抬升 10 步, 每步看接触与 peg
for k in range(10):
    e.step(np.array([0.0, 0.0, 0.06, 0.8]))
    o = np.asarray(e._get_obs(), dtype=np.float64).ravel()
    cs = contacts()
    peg_c = [c for c in cs if "peg" in c]
    print(f"[p10] 升{k+1} ee_z={P('endEffector')[2]:.4f} grp={o[3]:.3f} "
          f"pegΔz={o[4:7][2]-peg_b[2]:+.4f} 接触={len(cs)} peg接触={len(peg_c)}", flush=True)
    if o[4:7][2] - peg_b[2] > 0.02:
        print("[p10] ✅ peg 跟随抬升!", flush=True)
        break
print("[p10] done", flush=True)
