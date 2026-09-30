#!/usr/bin/env python3
"""探针11: 决定性 — 两指闭合中心漂移补偿 × 抬升节奏, 找能夹起 peg 的组合
全程逐帧: ee/指L/指R site y + 光模块 y + grp
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
S = {n: m.site(n).id for n in ["endEffector", "leftEndEffector", "rightEndEffector"]}
def P(n): return d.site_xpos[S[n]].copy()

def trial(y_off_mm, lift_mode, label):
    e.reset(seed=0); e._freeze_rand_vec = True
    o = np.asarray(e._get_obs(), dtype=np.float64).ravel()
    peg_tgt = o[4:7].copy() + np.array([0.0, y_off_mm, 0.0])   # y 补偿目标
    # 悬停水平逼近 (z=光模块+0.08)
    for k in range(90):
        o = np.asarray(e._get_obs(), dtype=np.float64).ravel()
        ee = P("endEffector")
        dv = np.zeros(4)
        dv[:2] = (peg_tgt[:2] - ee[:2])
        dv[2] = (peg_tgt[2] + 0.08 - ee[2]) * 3
        dv[:3] = np.clip(dv[:3] / 0.03, -1, 1); dv[3] = -1.0
        e.step(dv)
        if np.linalg.norm(ee[:2] - peg_tgt[:2]) < 0.003 and abs(ee[2] - peg_tgt[2] - 0.08) < 0.006:
            break
    # 垂直下降 (到位 = ee z ≈ 光模块 z + 0.003)
    for k in range(70):
        o = np.asarray(e._get_obs(), dtype=np.float64).ravel()
        ee = P("endEffector")
        dz = peg_tgt[2] + 0.003 - ee[2]
        if abs(dz) < 0.002: break
        a = np.zeros(4); a[2] = np.clip(dz * 4.0, -1, 1); a[3] = -1.0
        e.step(a)
    # 闭合 25 步 (跟踪中心)
    ctr_track = []
    for k in range(25):
        e.step(np.array([0.0, 0.0, 0.0, 0.8]))
        o = np.asarray(e._get_obs(), dtype=np.float64).ravel()
        if k in (2, 5, 10, 15, 24):
            ctr_track.append((round(o[3],2), round((P("leftEndEffector")[1]+P("rightEndEffector")[1])/2,4)))
    o = np.asarray(e._get_obs(), dtype=np.float64).ravel()
    grp_c = o[3]; peg_c = o[4:7].copy()
    # 抬升
    for k in range(45):
        a = np.zeros(4)
        a[2] = 0.4 if lift_mode == "mid" else (0.9 if k < 10 else 0.9)
        a[3] = 0.8
        e.step(a)
        o = np.asarray(e._get_obs(), dtype=np.float64).ravel()
        if o[4:7][2] - peg_c[2] > 0.035:
            print(f"[p11] {label}: 闭后grp={grp_c:.2f} 中心轨迹={ctr_track} → ✅ 抬升成功 pegΔz={o[4:7][2]-peg_c[2]:+.3f} (k={k})", flush=True)
            return True
    o = np.asarray(e._get_obs(), dtype=np.float64).ravel()
    print(f"[p11] {label}: 闭后grp={grp_c:.2f} 中心轨迹={ctr_track} pegΔz={o[4:7][2]-peg_c[2]:+.4f} ❌", flush=True)
    return False

trial(0.0, "mid", "y补偿0   抬0.4")
trial(-0.005, "mid", "y补偿-5mm 抬0.4")
trial(-0.010, "mid", "y补偿-10mm抬0.4")
trial(-0.005, "slow", "y补偿-5mm 抬0.9")
print("[p11] done", flush=True)
