#!/usr/bin/env python3
"""探针6: R0 式抓取流程几何 — 悬停→水平对准→垂直下降→闭合→抬升
回答: 夹爪指端降到多深能包住销身? 闭合后 光模块 是否随动?
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
ids = {n: m.site(n).id for n in ["endEffector", "leftEndEffector", "rightEndEffector",
                                 "pegGrasp", "pegHead", "hole", "goal"]}
def P(n): return d.site_xpos[ids[n]].copy()

peg0 = P("pegGrasp").copy()
print(f"[p6] pegGrasp={np.round(peg0,4)} hole={np.round(P('hole'),4)} goal={np.round(P('goal'),4)}", flush=True)

# ① 悬停高度水平逼近 (z=peg_z+0.09, 不碰销)
hover_z = peg0[2] + 0.09
for k in range(100):
    ee = P("endEffector")
    tgt = np.array([peg0[0], peg0[1], hover_z])
    dv = tgt - ee
    dv[2] = (hover_z - ee[2]) * 3.0            # z 快速到悬停
    a = np.zeros(4)
    a[:3] = np.clip(dv / 0.04, -1, 1)
    a[3] = -1.0                                 # 张开
    e.step(a)
    if np.linalg.norm(dv[:2]) < 0.005 and abs(dv[2]) < 0.005:
        break
print(f"[p6] 悬停到位 ee={np.round(P('endEffector'),4)} peg 位移={np.round(P('pegGrasp')-peg0,4)}", flush=True)

# ② 垂直下降 (每 5 步打 指端z/销z/接触)
peg_before = P("pegGrasp")[2]
for k in range(60):
    ee = P("endEffector")
    tgt_z = peg0[2] + 0.002                     # 降到抓握点上方 2mm
    a = np.zeros(4); a[3] = -1.0
    dz = tgt_z - ee[2]
    if abs(dz) < 0.002: break
    a[2] = np.clip(dz * 4.0, -1, 1)             # z 向满速降
    e.step(a)
    if k % 5 == 4:
        o = np.asarray(e._get_obs(), dtype=np.float64).ravel()
        print(f"[p6] 降{k+1} ee_z={P('endEffector')[2]:.4f} 指Lz={P('leftEndEffector')[2]:.4f} "
              f"指Rz={P('rightEndEffector')[2]:.4f} peg={np.round(P('pegGrasp'),4)} grp={o[3]:.2f}", flush=True)
o = np.asarray(e._get_obs(), dtype=np.float64).ravel()
print(f"[p6] 下降结束 ee={np.round(P('endEffector'),4)} peg={np.round(P('pegGrasp'),4)} grp={o[3]:.2f}", flush=True)

# ③ 闭合 30 步
for k in range(30):
    e.step(np.array([0.0, 0.0, 0.0, 0.6]))
    o = np.asarray(e._get_obs(), dtype=np.float64).ravel()
    if k in (4, 9, 14, 19, 29):
        print(f"[p6] 闭{k+1} grp={o[3]:.3f} 指L={np.round(P('leftEndEffector'),4)} "
              f"指R={np.round(P('rightEndEffector'),4)} peg={np.round(P('pegGrasp'),4)}", flush=True)

# ④ 抬升 25 步 — 光模块 随动?
pg = P("pegGrasp").copy()
for k in range(25):
    e.step(np.array([0.0, 0.0, 0.05, 0.6]))
    if k in (4, 9, 14, 24):
        o = np.asarray(e._get_obs(), dtype=np.float64).ravel()
        print(f"[p6] 升{k+1} ee_z={P('endEffector')[2]:.4f} peg={np.round(P('pegGrasp'),4)} "
              f"pegΔz={P('pegGrasp')[2]-pg[2]:+.4f} grp={o[3]:.2f}", flush=True)
print(f"[p6] 抬升后 peg 总升={P('pegGrasp')[2]-pg[2]:+.4f} → {'✅ 夹住' if P('pegGrasp')[2]-pg[2]>0.02 else '❌ 没夹住'}", flush=True)
print("[p6] done", flush=True)
