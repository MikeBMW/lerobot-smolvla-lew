#!/usr/bin/env python3
"""探针9: 夹住后大力抬升 — 闭合力度 × 抬升力度 组合扫描
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

def trial(grip_close, lift_act, close_steps, lift_steps, label):
    e.reset(seed=0); e._freeze_rand_vec = True
    o = np.asarray(e._get_obs(), dtype=np.float64).ravel()
    peg0 = o[4:7].copy()
    # 悬停 → 垂直下降 (实时对准)
    for k in range(80):
        ee = P("endEffector"); peg = o[4:7]
        dv = np.zeros(4)
        dv[:2] = peg[:2] - ee[:2]
        dv[2] = (peg[2] + 0.002 - ee[2]) * 4
        dv[:3] = np.clip(dv[:3] / 0.03, -1, 1); dv[3] = -1.0
        e.step(dv)
        o = np.asarray(e._get_obs(), dtype=np.float64).ravel()
        if np.linalg.norm(ee[:2] - peg[:2]) < 0.003 and abs(ee[2] - peg[2] - 0.002) < 0.004:
            break
    # 闭合
    for k in range(close_steps):
        e.step(np.array([0.0, 0.0, 0.0, grip_close]))
    o = np.asarray(e._get_obs(), dtype=np.float64).ravel()
    grp_c = o[3]; ncon_c = d.ncon
    # 大力抬升
    peg_b = o[4:7].copy()
    for k in range(lift_steps):
        e.step(np.array([0.0, 0.0, lift_act, grip_close]))
    o = np.asarray(e._get_obs(), dtype=np.float64).ravel()
    dl = o[4:7][2] - peg_b[2]
    ok = "✅" if dl > 0.03 else "❌"
    print(f"[p9] {label}: 闭后grp={grp_c:.2f} ncon={ncon_c} 抬{lift_steps}步(act{lift_act}) "
          f"pegΔz={dl:+.4f} ee_z={P('endEffector')[2]:.3f} {ok}", flush=True)

trial(0.6, 0.8, 25, 40, "grip0.6 抬0.8x40")
trial(1.0, 0.8, 25, 40, "grip1.0 抬0.8x40")
trial(1.0, 1.0, 25, 40, "grip1.0 抬1.0x40")
trial(0.6, 1.0, 40, 60, "grip0.6 抬1.0x60 慢闭")
trial(1.0, 1.0, 10, 40, "grip1.0 抬1.0x40 快闭")
print("[p9] done", flush=True)
