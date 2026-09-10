#!/usr/bin/env python3
"""探针4: mujoco site API 兼容 + 夹爪闭合收敛 + peg 随动 (R0 实现依赖)
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

# site 名访问 API 探测
sid = {}
try:
    for i in range(m.nsite):
        try:
            nm = m.site(i).name
        except Exception:
            nm = str(i)
        if nm and any(k in str(nm).lower() for k in ("goal", "hole", "peg", "end", "grasp")):
            sid[str(nm)] = i
            print(f"[probe4] site({i}) name={nm} xpos={np.round(d.site_xpos[i],4)}", flush=True)
except Exception as ex:
    print(f"[probe4] site(i).name API 失败: {ex}", flush=True)
    # 兜底: 尝试 name2id
    for cand in ["goal", "hole", "pegGrasp", "pegHead", "pegEnd", "endEffector"]:
        try:
            i = m.name2id("site", cand)
            print(f"[probe4] name2id({cand}) = {i} xpos={np.round(d.site_xpos[i],4)}", flush=True)
        except Exception as ex2:
            print(f"[probe4] name2id({cand}) 失败: {ex2}", flush=True)

# 夹爪闭合收敛 + 光模块 随动 (悬停到 光模块 上方 → 闭合)
ee = m.site("endEffector").id if hasattr(m.site("endEffector"), "id") else None
pg = m.site("pegGrasp").id if hasattr(m.site("pegGrasp"), "id") else None
print(f"[probe4] endEffector id={ee} pegGrasp id={pg}", flush=True)

# 先移到 光模块 正上方 (act 逼近, 60 步)
o = np.asarray(e._get_obs(), dtype=np.float64).ravel()
tgt = o[4:7].copy() + np.array([0.0, 0.0, 0.12])
for k in range(80):
    cur_hand = d.site_xpos[ee] if ee is not None else o[0:3]
    dv = tgt - cur_hand
    a = np.clip(dv / 0.05, -1, 1)
    e.step(np.concatenate([a[:3], [-1.0]]))
o = np.asarray(e._get_obs(), dtype=np.float64).ravel()
hand = d.site_xpos[ee] if ee is not None else o[0:3]
print(f"[probe4] 逼近后 hand={np.round(hand,4)} 目标={np.round(tgt,4)} 差={np.round(tgt-hand,4)}", flush=True)

# 连续闭合 act[3]=0.6, 看 gripper 收敛 + 光模块 是否随动
peg0 = o[4:7].copy()
for k in range(30):
    e.step(np.array([0.0, 0.0, 0.0, 0.6]))
    o = np.asarray(e._get_obs(), dtype=np.float64).ravel()
    if k in (0, 2, 5, 10, 20, 29):
        print(f"[probe4] 闭{k+1} gripper={o[3]:.4f} pegΔ={np.round(o[4:7]-peg0,4)}", flush=True)
print("[probe4] done", flush=True)
