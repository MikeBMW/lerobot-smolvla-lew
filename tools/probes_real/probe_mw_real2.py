#!/usr/bin/env python3
"""探针2: site 几何 vs obs 段位 + 连续 step 位移累积 (2026-09-04)
"""
import os, time
os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("MUJOCO_GL", "glfw")
import numpy as np

import metaworld as _mt
mt = _mt.MT1("peg-insert-side-v3")
env = mt.train_classes["peg-insert-side-v3"](render_mode="rgb_array", camera_name="corner2")
env.set_task(mt.train_tasks[0])
env.reset(seed=0)
env._freeze_rand_vec = True

# 全部 site name+xpos (mujoco 新版 API: model.site(i) 无 name 字段? 用 site_id2name)
try:
    m = env.model
    for i in range(m.nsite):
        nm = m.site_id2name(i)
        if nm:
            print(f"[probe2] site[{i}] {nm} = {np.round(m.site_pos[i],4)}", flush=True)
except Exception as e:
    print(f"[probe2] site 枚举失败: {e}", flush=True)

o = np.asarray(env._get_obs(), dtype=np.float64).ravel()
print(f"[probe2] obs hand = {np.round(o[0:3],4)} · peg = {np.round(o[4:7],4)} · goal[36:39] = {np.round(o[36:39],4)}", flush=True)

# 连续 step 位移累积: act=[0.05,0,0,0] ×20
env.reset(seed=0); env._freeze_rand_vec = True
h0 = np.asarray(env._get_obs(), dtype=np.float64).ravel()[0:3].copy()
a = np.array([0.05, 0.0, 0.0, 0.0])
for k in range(20):
    env.step(a)
    h = np.asarray(env._get_obs(), dtype=np.float64).ravel()[0:3]
    if k in (0, 1, 4, 9, 19):
        print(f"[probe2] act=0.05x 步{k+1}: Δ={np.round(h-h0,5)}", flush=True)
print(f"[probe2] 20步累积 Δ={np.round(h-h0,5)} → 单步等效 {np.round((h-h0)/20,5)}", flush=True)

# 大动作一步
env.reset(seed=0); env._freeze_rand_vec = True
h0 = np.asarray(env._get_obs(), dtype=np.float64).ravel()[0:3].copy()
env.step(np.array([0.5, 0.0, 0.0, 0.0]))
h = np.asarray(env._get_obs(), dtype=np.float64).ravel()[0:3]
print(f"[probe2] act=[0.5,0,0,0] 一步 Δ={np.round(h-h0,5)}", flush=True)
env.reset(seed=0); env._freeze_rand_vec = True
h0 = np.asarray(env._get_obs(), dtype=np.float64).ravel()[0:3].copy()
env.step(np.array([1.0, 0.0, 0.0, 0.0]))
h = np.asarray(env._get_obs(), dtype=np.float64).ravel()[0:3]
print(f"[probe2] act=[1.0,0,0,0] 一步 Δ={np.round(h-h0,5)}", flush=True)

# gripper 动作
env.reset(seed=0); env._freeze_rand_vec = True
env.step(np.array([0.0, 0.0, 0.0, 0.6]))
o = np.asarray(env._get_obs(), dtype=np.float64).ravel()
print(f"[probe2] grip act 0.6 一步后 gripper obs = {o[3]:.4f}", flush=True)
print("[probe2] done", flush=True)
