#!/usr/bin/env python3
"""探针3: freeze 时序一致性 + 连续大步收敛 + site 几何 (2026-09-04)
"""
import os
os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("MUJOCO_GL", "glfw")
import numpy as np
import metaworld as _mt

mt = _mt.MT1("peg-insert-side-v3")

def mk():
    e = mt.train_classes["peg-insert-side-v3"](render_mode="rgb_array", camera_name="corner2")
    e.set_task(mt.train_tasks[0])
    return e

# A: freeze 在 reset 之后 (aligner 现用法) — reset 两次
e = mk(); e.reset(seed=0); e._freeze_rand_vec = True
o1 = np.asarray(e._get_obs(), dtype=np.float64).ravel()
e.reset(seed=0)  # freeze 已 True, reset 是否还随机化?
o2 = np.asarray(e._get_obs(), dtype=np.float64).ravel()
print(f"[probe3] A(先reset后freeze) peg1={np.round(o1[4:7],4)} goal1={np.round(o1[36:39],4)}", flush=True)
print(f"[probe3] A 二次reset        peg2={np.round(o2[4:7],4)} goal2={np.round(o2[36:39],4)}", flush=True)
print(f"[probe3] A 两次一致? peg={np.allclose(o1[4:7],o2[4:7])} goal={np.allclose(o1[36:39],o2[36:39])}", flush=True)

# B: freeze 在 reset 之前
e = mk(); e._freeze_rand_vec = True; e.reset(seed=0)
o1 = np.asarray(e._get_obs(), dtype=np.float64).ravel()
e.reset(seed=0)
o2 = np.asarray(e._get_obs(), dtype=np.float64).ravel()
print(f"[probe3] B(先freeze后reset) peg1={np.round(o1[4:7],4)} goal1={np.round(o1[36:39],4)}", flush=True)
print(f"[probe3] B 二次reset         peg2={np.round(o2[4:7],4)} goal2={np.round(o2[36:39],4)}", flush=True)
print(f"[probe3] B 两次一致? peg={np.allclose(o1[4:7],o2[4:7])} goal={np.allclose(o1[36:39],o2[36:39])}", flush=True)

# C: 连续大步 act=[1,0,0,0] ×10 — 是否收敛加速 (伺服到位率)
e = mk(); e.reset(seed=0); e._freeze_rand_vec = True
h0 = np.asarray(e._get_obs(), dtype=np.float64).ravel()[0:3].copy()
for k in range(10):
    e.step(np.array([1.0, 0.0, 0.0, 0.0]))
    h = np.asarray(e._get_obs(), dtype=np.float64).ravel()[0:3]
    if k in (0, 1, 2, 4, 9):
        print(f"[probe3] act=1.0 步{k+1} Δ={np.round(h-h0,5)}", flush=True)

# D: site 几何 (mujoco name2id)
try:
    m = e.model
    nm = [m.site(i).name for i in range(m.nsite)] if hasattr(m.site(0), "name") else None
    if nm is None:
        # mujoco 3.x: model.site(i) 无 name? 走 mjcf 探测
        nm = [str(m.site_id2name(i)) for i in range(m.nsite)]
except Exception as ex:
    print(f"[probe3] site name 枚举失败: {ex}", flush=True)
    nm = None
if nm:
    for i, n in enumerate(nm):
        if n and any(k in n.lower() for k in ("peg", "hole", "hand", "end", "goal", "grasp", "insert")):
            print(f"[probe3] site[{i}] {n} xpos={np.round(e.data.site_xpos[i],4)}", flush=True)
print("[probe3] done", flush=True)
