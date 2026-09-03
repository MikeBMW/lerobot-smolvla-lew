#!/usr/bin/env python3
"""探针12: 正确锚 (obs hand=claw) 抓取验证 — hand 到 peg 身, 闭合, 抬升
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

e.reset(seed=0); e._freeze_rand_vec = True
o = np.asarray(e._get_obs(), dtype=np.float64).ravel()
peg = o[4:7].copy()
print(f"[p12] hand0={np.round(o[0:3],4)} peg={np.round(peg,4)}", flush=True)

# hand 悬停到 peg 上方 8cm (hand=obs[0:3] 为锚)
for k in range(100):
    o = np.asarray(e._get_obs(), dtype=np.float64).ravel()
    h = o[0:3]
    dv = np.zeros(4)
    dv[:2] = peg[:2] - h[:2]
    dv[2] = (peg[2] + 0.08 - h[2]) * 3
    dv[:3] = np.clip(dv[:3] / 0.03, -1, 1); dv[3] = -1.0
    e.step(dv)
    if np.linalg.norm(h[:2]-peg[:2]) < 0.003 and abs(h[2]-peg[2]-0.08) < 0.006:
        break
o = np.asarray(e._get_obs(), dtype=np.float64).ravel()
print(f"[p12] 悬停 hand={np.round(o[0:3],4)}", flush=True)

# hand 垂直下降到 peg 身 (z 目标 = peg z + 0.002)
for k in range(60):
    o = np.asarray(e._get_obs(), dtype=np.float64).ravel()
    h = o[0:3]
    dz = peg[2] + 0.002 - h[2]
    if abs(dz) < 0.002: break
    a = np.zeros(4); a[2] = np.clip(dz * 4.0, -1, 1); a[3] = -1.0
    e.step(a)
o = np.asarray(e._get_obs(), dtype=np.float64).ravel()
print(f"[p12] 到位 hand={np.round(o[0:3],4)} peg={np.round(o[4:7],4)}", flush=True)

# 闭合 30 步
for k in range(30):
    e.step(np.array([0.0, 0.0, 0.0, 0.8]))
    o = np.asarray(e._get_obs(), dtype=np.float64).ravel()
    if k in (4, 9, 14, 19, 29):
        cs = [f"{m.geom(c.geom1).name or 'g'+str(c.geom1)}|{m.geom(c.geom2).name or 'g'+str(c.geom2)}"
              for c in d.contact[:d.ncon] if 'peg' in (m.geom(c.geom1).name or '') or 'peg' in (m.geom(c.geom2).name or '')]
        print(f"[p12] 闭{k+1} grp={o[3]:.3f} ncon={d.ncon} claw接触={len(cs)}", flush=True)
o = np.asarray(e._get_obs(), dtype=np.float64).ravel()
grp_c = o[3]; peg_c = o[4:7].copy()

# 抬升 40 步
for k in range(40):
    a = np.zeros(4); a[2] = 0.5; a[3] = 0.8
    e.step(a)
    o = np.asarray(e._get_obs(), dtype=np.float64).ravel()
    dl = o[4:7][2] - peg_c[2]
    if k in (4, 9, 19, 39):
        print(f"[p12] 升{k+1} hand_z={o[0]:.4f} pegΔz={dl:+.4f} grp={o[3]:.3f}", flush=True)
    if dl > 0.03:
        print(f"[p12] ✅ 夹住并抬升! pegΔz={dl:+.4f}", flush=True)
        break
o = np.asarray(e._get_obs(), dtype=np.float64).ravel()
print(f"[p12] 最终 pegΔz={o[4:7][2]-peg_c[2]:+.4f} → {'✅ 成功' if o[4:7][2]-peg_c[2]>0.03 else '❌ 失败'}", flush=True)
print("[p12] done", flush=True)
