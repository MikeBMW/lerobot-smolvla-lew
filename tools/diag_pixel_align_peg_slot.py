#!/usr/bin/env python3
"""把关键点投影到 corner2 画面像素上: 光模块 与 插槽 在**图里**差多少像素

老倪说"插销没插到插槽里, 横向有偏差" —— 3D 站点真值说对齐(0.2mm), 但人眼看的是**渲染图**。
这里用 mujoco 相机矩阵把 世界点 → 像素:
  光模块两端(轴) / 孔口 mouth / 终点 goal / 盒子口沿
并算: 图里 光模块轴心 到 孔口 的 像素偏差 + 光模块绿色像素质心 vs 投影点 (自检投影对不对)。
用法: DISPLAY=:0 gui-venv311/bin/python tools/diag_pixel_align_peg_slot.py [--png out.png]
"""
import argparse
import os
import sys

os.environ.setdefault("DISPLAY", ":0")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "gui"))

import numpy as np                                       # noqa: E402
import cv2                                               # noqa: E402
import state_space_sim_real as ssr                       # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--png", default="/tmp/final_render.png")
ap.add_argument("--seed", type=int, default=104)
ap.add_argument("--vision", type=int, default=0)
a = ap.parse_args()

sim = ssr.RealStateSpaceSim(log=lambda *x: None, seed=a.seed, vision=bool(a.vision), mode="insert")
sim._reset(a.seed)
tr = sim.run(cap="L2")
env, m, d = sim.env, sim.env.model, sim.env.data
rgb = np.asarray(env.render())
cv2.imwrite(a.png, rgb[:, :, ::-1])
H, W = rgb.shape[:2]

# ── 相机 ── (corner2)
cid = m.camera("corner2").id
cpos = np.asarray(d.cam_xpos[cid], float).copy()
cmat = np.asarray(d.cam_xmat[cid], float).reshape(3, 3).copy()   # 相机→世界
fovy = float(m.cam_fovy[cid])
f = 0.5 * H / np.tan(np.radians(fovy / 2.0))


def proj(p):
    """世界点 → 像素 (u, v)

    ⚠️ MuJoCo 相机朝向: cam_xmat 的列是相机三轴在世界系; 视轴是 **-z** (GL 约定)。
    先用 -z 做深度, 若为负则整体取反 (自检: 投影的光模块中心要落在渲染图绿像素质心附近)。
    """
    v = np.asarray(p, float) - cpos
    xc = float(cmat[:, 0] @ v)
    yc = float(cmat[:, 1] @ v)
    zc = float(cmat[:, 2] @ v)
    depth = -zc
    if depth < 0:
        depth, xc, yc = -depth, -xc, -yc
    if depth <= 1e-6:
        return None
    u = W / 2.0 + f * xc / depth
    vv = H / 2.0 - f * yc / depth
    return np.array([u, vv])


# ── 关键几何 ──
pb = m.body("peg").id
gi = m.body_geomadr[pb]
half = np.asarray(m.geom_size[gi], float)
xmat = np.asarray(d.geom_xmat[gi], float).reshape(3, 3)
la = int(np.argmax(half))
axis = xmat[:, la] / (np.linalg.norm(xmat[:, la]) or 1)
L = float(half[la])
pc = np.asarray(d.geom_xpos[gi], float).copy()
e1, e2 = pc - axis * L, pc + axis * L
mouth = np.asarray(sim.geom["hole"], float).copy()
goal = np.asarray(sim.geom["goal"], float).copy()
ph = np.asarray(d.site_xpos[sim._site_ph], float).copy()

print(f"阶段终态: {tr['stage'][-1]} · done={bool(tr['done'][-1])} · 渲染 {W}x{H}")
print("\n世界坐标:")
print(f"  光模块中心 {np.round(pc, 4)} 轴 {np.round(axis, 3)} 半长 {L * 100:.1f}cm")
print(f"  光模块两端 {np.round(e1, 4)} ~ {np.round(e2, 4)}")
print(f"  孔口 mouth {np.round(mouth, 4)} · 终点 goal {np.round(goal, 4)} · 头 site {np.round(ph, 4)}")
print(f"  孔轴距 |goal-mouth| = {np.linalg.norm(goal - mouth) * 1000:.1f} mm")

print("\n像素坐标 (u, v):")
P = {}
for nm, p in (("光模块端1", e1), ("光模块中心", pc), ("光模块端2", e2),
              ("光模块头", ph), ("孔口", mouth), ("终点", goal)):
    uv = proj(p)
    P[nm] = uv
    print(f"  {nm:8s} {None if uv is None else np.round(uv, 1)}")

if P["孔口"] is not None and P["光模块中心"] is not None:
    dd = P["光模块中心"] - P["孔口"]
    print(f"\n→ 图里 光模块中心 与 孔口 的像素差: Δu={dd[0]:+.1f} Δv={dd[1]:+.1f}"
          f" |Δ|={np.linalg.norm(dd):.1f} px")
# 光模块轴 到 孔口点 的像素最短距离 (横向错位量)
if all(P[k] is not None for k in ("光模块端1", "光模块端2", "孔口")):
    p1, p2, q = P["光模块端1"], P["光模块端2"], P["孔口"]
    dv = p2 - p1
    t = float(np.clip(np.dot(q - p1, dv) / (np.dot(dv, dv) or 1), 0, 1))
    foot = p1 + t * dv
    print(f"→ 图里 孔口 到 光模块轴线 的横向像素距离 = {np.linalg.norm(q - foot):.1f} px"
          f"  (0 = 完全同轴)")

# ── 自检: 渲染图里绿像素(光模块体) 质心 vs 投影的光模块中心 ──
b, g, r = rgb[:, :, 2].astype(int), rgb[:, :, 1].astype(int), rgb[:, :, 0].astype(int)
mask = (g - np.maximum(r, b)) > 40
n = int(mask.sum())
if n:
    ys, xs = np.nonzero(mask)
    print(f"\n自检: 渲染图绿像素 {n} 个, 质心 ({xs.mean():.1f}, {ys.mean():.1f});"
          f" 投影光模块中心 {np.round(P['光模块中心'], 1)} (应接近 → 说明投影/相机正确)")
    print(f"  绿像素 x 范围 {xs.min()}~{xs.max()}, y 范围 {ys.min()}~{ys.max()}")
print(f"\n终局渲染已存 {a.png}")
sys.exit(0)
