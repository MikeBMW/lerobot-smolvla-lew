#!/usr/bin/env python3
"""探针7: 夹持窗口扫描 — ee 降多深 + y 对准多准才能夹住销 (R0 抓取参数)
每轮: 悬停对准(实时peg) → 降到目标z(猛降) → 闭合20步 → 抬升15步 → 判夹持
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
ids = {n: m.site(n).id for n in ["endEffector", "leftEndEffector", "rightEndEffector", "pegGrasp"]}
def P(n): return d.site_xpos[ids[n]].copy()

def trial(z_target_mm, y_off_mm, label):
    e.reset(seed=0); e._freeze_rand_vec = True
    o = np.asarray(e._get_obs(), dtype=np.float64).ravel()
    peg = o[4:7].copy()                      # 实时光模块位置 (obs)
    # 悬停 (z=销+0.09, 水平对准+侧偏)
    tgt_xy = np.array([peg[0], peg[1] + y_off_mm])
    for k in range(80):
        ee = P("endEffector")
        dv = np.zeros(4)
        dv[:2] = tgt_xy - ee[:2]
        dv[2] = (peg[2] + 0.09 - ee[2]) * 3
        dv[:3] = np.clip(dv[:3] / 0.03, -1, 1); dv[3] = -1.0
        e.step(dv)
        if np.linalg.norm(ee[:2] - tgt_xy) < 0.003 and abs(ee[2] - peg[2] - 0.09) < 0.005:
            break
    # 垂直猛降到目标 z
    for k in range(80):
        ee = P("endEffector")
        dz = (peg[2] + z_target_mm) - ee[2]
        if abs(dz) < 0.0015: break
        a = np.zeros(4); a[2] = np.clip(dz * 5.0, -1, 1); a[3] = -1.0
        e.step(a)
    o = np.asarray(e._get_obs(), dtype=np.float64).ravel()
    ee_final = P("endEffector").copy(); peg_final = o[4:7].copy()
    # 闭合 22 步
    for k in range(22):
        e.step(np.array([0.0, 0.0, 0.0, 0.6]))
    o = np.asarray(e._get_obs(), dtype=np.float64).ravel()
    grp_closed = o[3]
    # 抬升 15 步
    for k in range(15):
        e.step(np.array([0.0, 0.0, 0.05, 0.6]))
    o = np.asarray(e._get_obs(), dtype=np.float64).ravel()
    lift = o[4:7][2] - peg_final[2]
    ok = "✅" if lift > 0.02 else "❌"
    print(f"[p7] {label}: 目标z={peg[2]+z_target_mm:.4f} ee终z={ee_final[2]:.4f} "
          f"闭合后grp={grp_closed:.2f} 抬升Δpegz={lift:+.4f} {ok}", flush=True)

for zm, yo, lb in [(0.005, 0.0, "z+5mm y对"), (0.002, 0.0, "z+2mm y对"),
                   (0.000, 0.0, "z+0mm y对"), (-0.003, 0.0, "z-3mm y对"),
                   (0.002, -0.005, "z+2mm y偏-5"), (0.002, 0.005, "z+2mm y偏+5"),
                   (0.002, 0.0, "z+2mm y对(重复)")]:
    trial(zm, yo, lb)
print("[p7] done", flush=True)
