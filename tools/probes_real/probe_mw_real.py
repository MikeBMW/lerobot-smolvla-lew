#!/usr/bin/env python3
"""探针: metaworld peg-insert-side-v3 契约数字 (2026-09-04 闭环真实化设计用)
打印: 39D obs 段位真值 / goal / action 位移尺度 / 相机参数 / env.step 计时
用法: gui-venv311/bin/python probe_mw_real.py
"""
import os, time
os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("MUJOCO_GL", "glfw")
import numpy as np

t0 = time.time()
import metaworld as _mt
print(f"[probe] metaworld import {time.time()-t0:.1f}s", flush=True)

t0 = time.time()
mt = _mt.MT1("peg-insert-side-v3")
env = mt.train_classes["peg-insert-side-v3"](render_mode="rgb_array", camera_name="corner2")
env.set_task(mt.train_tasks[0])
env.reset(seed=0)
env._freeze_rand_vec = True
print(f"[probe] env 构造+reset {time.time()-t0:.1f}s", flush=True)

o = np.asarray(env._get_obs(), dtype=np.float64).ravel()
print(f"[probe] obs39 全: {np.round(o, 4)}", flush=True)
print(f"[probe] [0:3] hand      = {np.round(o[0:3],4)}", flush=True)
print(f"[probe] [3]   gripper   = {o[3]:.4f}", flush=True)
print(f"[probe] [4:7] peg       = {np.round(o[4:7],4)}", flush=True)
print(f"[probe] [7:11] peg_quat = {np.round(o[7:11],4)}", flush=True)
print(f"[probe] [11:18] pad     = {np.round(o[11:18],4)}", flush=True)
print(f"[probe] [18:21] prev_hand = {np.round(o[18:21],4)}", flush=True)
print(f"[probe] [36:39] goal    = {np.round(o[36:39],4)}", flush=True)

# 几何 site (引擎注释来源 probe_scene_geom)
try:
    for s in ["endEffector", "pegGrasp", "pegHead", "hole", "goal"]:
        sid = env.model.site_name2id(s) if s in [env.model.site_name2id(x) for x in range(env.model.nsite)] else None
    names = [env.model.site_id2name(i) for i in range(env.model.nsite)]
    print(f"[probe] sites({env.model.nsite}): {[n for n in names if n]}", flush=True)
except Exception as e:
    print(f"[probe] site 枚举失败: {e}", flush=True)

# 相机参数 (YOLO 反投影用)
try:
    cam_id = env.model.camera("corner2").id
    print(f"[probe] cam_pos   = {np.round(env.model.cam_pos[cam_id], 4)}", flush=True)
    cm = np.asarray(env.model.cam_mat0[cam_id]).reshape(3, 3).T
    print(f"[probe] cam_mat0.T= \n{np.round(cm, 4)}", flush=True)
    print(f"[probe] cam_fovy  = {env.model.cam_fovy[cam_id]:.4f}", flush=True)
except Exception as e:
    print(f"[probe] 相机失败: {e}", flush=True)

# action 位移尺度实验 (delta 控制增益)
for a in [np.array([0.05, 0.0, 0.0, 0.0]), np.array([0.0, 0.0, 0.05, 0.0])]:
    env.reset(seed=0); env._freeze_rand_vec = True
    h0 = np.asarray(env._get_obs(), dtype=np.float64).ravel()[0:3].copy()
    t0 = time.time()
    env.step(a)
    dt_step = time.time() - t0
    h1 = np.asarray(env._get_obs(), dtype=np.float64).ravel()[0:3]
    print(f"[probe] act={np.round(a,2)} → hand Δ={np.round(h1-h0,5)} | step 耗时 {dt_step*1000:.0f}ms", flush=True)

# 真实渲染计时 (YOLO 帧)
try:
    t0 = time.time()
    img = env.render()
    print(f"[probe] render 1 帧 {time.time()-t0:.2f}s · shape={img.shape}", flush=True)
except Exception as e:
    print(f"[probe] render 失败: {e}", flush=True)

# 完成一次插拔要多少步? 简化: 夹爪闭合后抬升试探
print("[probe] done", flush=True)
