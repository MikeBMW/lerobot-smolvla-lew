#!/usr/bin/env python3
"""导出状态空间仿真轨迹 → 网页 3D 分层空间 JSON (2026-09-06)
含: 末端轨迹 x / 光模块 peg / 孔位 target / 夹爪 gripper / 阶段 stage
分层向量 (每步): u_ff(前馈) u_fb(反馈) u_fuse(融合) u_limit(安全限幅) u_exec(实际执行)
                latent(状态估计x̂) prior(先验预测) corrected(校正) residual_vec z_k_vec
"""
import sys, os, json
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from state_space_sim import StateSpaceSim

sim = StateSpaceSim()
tr = sim.run()
n = len(tr["x"])
print(f"轨迹: {n} 步, done={tr['done'][-1]}, dist={tr['dist'][-1]:.4f}")

def v3(arr, i):
    """取第 i 步的 3D 向量 (容忍 np 数组/list/标量)"""
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
        "u_ff": v3(tr.get("u_ff_vec", []), i),          # ① 前馈加速器
        "latent": v3(tr.get("latent_vec", []), i),      # ② 状态估计 x̂
        "prior": v3(tr.get("prior_vec", []), i),        # ③ 先验预测
        "corrected": v3(tr.get("corrected_vec", []), i),# ④ 状态校正
        "residual": v3(tr.get("residual_vec", []), i),  # 残差向量
        "u_fb": v3(tr.get("u_fb_vec", []), i),          # 反馈分量
        "u_fuse": v3(tr.get("u_fuse_vec", []), i),      # 融合
        "u_limit": v3(tr.get("u_limit_vec", []), i),    # 安全限幅
        "u_exec": v3(tr.get("u_exec_vec", []), i),      # 执行
        "z_k": v3(tr.get("z_k_vec", []), i),            # 卡尔曼观测
        "contact_p": round(float(tr["contact_p"][i]), 3),
        "residual_scalar": round(float(tr["residual"][i]), 4),
    })

out = {
    "title": "状态空间 3D 分层空间 · 插光模块仿真",
    "n": n_out,
    "step_skip": step,
    "done": bool(tr["done"][-1]),
    "dist_final": round(float(tr["dist"][-1]), 4),
    "stages": sorted(set(f["stage"] for f in frames)),
    "frames": frames,
}

path = "/tmp/ss_traj_full.json"
with open(path, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False)
print(f"✅ 已导出: {path} ({os.path.getsize(path)//1024}KB, {n_out}帧)")
print(f"阶段: {out['stages']}")
print(f"关键帧 x[0]={frames[0]['x']} → x[-1]={frames[-1]['x']}")
