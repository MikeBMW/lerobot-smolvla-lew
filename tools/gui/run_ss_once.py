#!/usr/bin/env python3
"""run_ss_once.py — 真实执行一次状态空间仿真, 输出标准 JSON (守护进程调用)
用法: python run_ss_once.py [seed]
输出: /tmp/ss_run_out.json
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from state_space_sim import StateSpaceSim

seed = int(sys.argv[1]) if len(sys.argv) > 1 else None
if seed:
    import numpy as np
    np.random.seed(seed)

sim = StateSpaceSim()
tr = sim.run()
n = len(tr["x"])
print(f"轨迹: {n} 步, done={tr['done'][-1]}, dist={tr['dist'][-1]:.4f}", flush=True)

def v3(arr, i):
    try:
        v = arr[i]
        if hasattr(v, '__len__') and len(v) >= 3:
            return [round(float(v[0]), 4), round(float(v[1]), 4), round(float(v[2]), 4)]
    except Exception:
        pass
    return None

step = max(1, n // 400)
n_out = (n + step - 1) // step
frames = []
for i in range(0, n, step):
    stage = str(tr["stage"][i]).replace("阶段 ", "").split("·")[0].strip()
    frames.append({
        "t": round(float(tr["t"][i]), 3),
        "x": v3(tr["x"], i),
        "peg": v3(tr["peg"], i),
        "target": v3(tr["target"], i),
        "peg_head": v3(tr.get("peg_head", []), i),
        "gripper": round(float(tr["gripper"][i]), 3) if i < len(tr.get("gripper", [])) else 0,
        "grasped": bool(tr["grasped"][i]) if i < len(tr.get("grasped", [])) else False,
        "stage": stage,
        "dist": round(float(tr["dist"][i]), 4),
        "u_ff": v3(tr.get("u_ff_vec", []), i),
        "latent": v3(tr.get("latent_vec", []), i),
        "prior": v3(tr.get("prior_vec", []), i),
        "corrected": v3(tr.get("corrected_vec", []), i),
        "residual": v3(tr.get("residual_vec", []), i),
        "u_fb": v3(tr.get("u_fb_vec", []), i),
        "u_fuse": v3(tr.get("u_fuse_vec", []), i),
        "u_limit": v3(tr.get("u_limit_vec", []), i),
        "u_exec": v3(tr.get("u_exec_vec", []), i),
        "contact_p": round(float(tr["contact_p"][i]), 3),
        "residual_scalar": round(float(tr["residual"][i]), 4),
    })

out = {
    "title": "状态空间 3D 分层空间 · 插光模块仿真",
    "seed": seed,
    "n": n_out,
    "done": bool(tr["done"][-1]),
    "dist_final": round(float(tr["dist"][-1]), 4),
    "stages": sorted(set(f["stage"] for f in frames)),
    "frames": frames,
}
with open("/tmp/ss_run_out.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False)
print(f"已输出 /tmp/ss_run_out.json ({len(frames)}帧)")
