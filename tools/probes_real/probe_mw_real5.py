#!/usr/bin/env python3
"""探针5: 夹爪闭合时 指端 vs 销身 几何 (R0 抓取失败的根因定位)
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
                                 "pegGrasp", "pegHead", "pegEnd", "hole", "goal"]}
def P(n): return d.site_xpos[ids[n]].copy()

o = np.asarray(e._get_obs(), dtype=np.float64).ravel()
print(f"[p5] 初始 endEffector={np.round(P('endEffector'),4)}", flush=True)
print(f"[p5] 初始 left={np.round(P('leftEndEffector'),4)} right={np.round(P('rightEndEffector'),4)}", flush=True)
print(f"[p5] 初始 pegGrasp={np.round(P('pegGrasp'),4)} pegHead={np.round(P('pegHead'),4)} pegEnd={np.round(P('pegEnd'),4)}", flush=True)
print(f"[p5] obs peg={np.round(o[4:7],4)} obs hand={np.round(o[0:3],4)}", flush=True)

# 移到 光模块 正上方 (夹爪 xy=pegGrasp xy, z 保持悬停), 再降到物理下限
tgt = P('pegGrasp') + np.array([0.0, 0.0, 0.005])   # 直接瞄准抓握点上方 5mm
for k in range(120):
    dv = tgt - P('endEffector')
    a = np.clip(dv / 0.03, -1, 1)
    e.step(np.concatenate([a[:3], [1.0]]))            # 全程张开 (act_g=1? 需确认方向)
    if k % 30 == 29:
        print(f"[p5] 逼近{k+1} ee={np.round(P('endEffector'),4)} dv={np.round(dv,4)}", flush=True)
o = np.asarray(e._get_obs(), dtype=np.float64).ravel()
print(f"[p5] 到位 ee={np.round(P('endEffector'),4)} grp={o[3]:.3f}", flush=True)

# 闭合 40 步, 观察指端与销
for k in range(40):
    e.step(np.array([0.0, 0.0, 0.0, 0.6]))
    o = np.asarray(e._get_obs(), dtype=np.float64).ravel()
    if k in (0, 5, 10, 15, 20, 30, 39):
        print(f"[p5] 闭{k+1} grp={o[3]:.3f} left={np.round(P('leftEndEffector'),4)} "
              f"right={np.round(P('rightEndEffector'),4)} ee={np.round(P('endEffector'),4)} "
              f"peg={np.round(P('pegGrasp'),4)}", flush=True)
# 抬升试探: 夹爪升 5cm, 光模块 跟不跟?
peg_before = P('pegGrasp').copy()
for k in range(20):
    e.step(np.array([0.0, 0.0, 0.05, 0.6]))
    if k in (4, 9, 19):
        o = np.asarray(e._get_obs(), dtype=np.float64).ravel()
        print(f"[p5] 升{k+1} ee_z={P('endEffector')[2]:.4f} peg={np.round(P('pegGrasp'),4)} grp={o[3]:.3f}", flush=True)
print(f"[p5] peg 抬升量 = {P('pegGrasp')[2]-peg_before[2]:.4f}", flush=True)
print("[p5] done", flush=True)
