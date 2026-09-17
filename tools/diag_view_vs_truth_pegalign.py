#!/usr/bin/env python3
"""3D 分层视图(DreamView3D) 画出来的"光模块 vs 插槽" 与 物理真值 差多少 (老倪: 横向有偏差)

背景: 3D 视图的场景几何有一套**写死常量** (ss_dreamview.py:146-166 当年探针测的一组布局):
  _HOLE_MOUTH=[-0.1685,0.4623,0.1309]  _HOLE=[-0.2345,0.4623,0.1309]  _BOX_CENTER=[-0.2645,0.4623,0.095]
  _PEG_CENTER_OFF=[-0.030,0,-0.010]    _PEG_SIZE=(0.20,0.03,0.03)
引擎侧: 孔口/终点/盒中心通过 tr["_meta"] 覆盖 (hole_mouth/goal/box_center) ✓,
但 **光模块的绘制位置/尺寸** 用的是 tr["peg"] + _peg_center_off (meta 里没有 peg 几何)。
本脚本把两边摆在一起量差。

跑法: DISPLAY=:0 gui-venv311/bin/python tools/diag_view_vs_truth_pegalign.py [--vision 0/1] [--seed 104]
"""
import argparse
import os
import sys

os.environ.setdefault("DISPLAY", ":0")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "gui"))

import numpy as np                                       # noqa: E402
import state_space_sim_real as ssr                       # noqa: E402
import ss_dreamview as sdv                               # noqa: E402   (只取常量, 不起窗口)

ap = argparse.ArgumentParser()
ap.add_argument("--vision", type=int, default=0)
ap.add_argument("--seed", type=int, default=104)
ap.add_argument("--cap", default="L2")
a = ap.parse_args()

sim = ssr.RealStateSpaceSim(log=lambda *x: None, seed=a.seed, vision=bool(a.vision), mode="insert")
tr = sim.run(cap=a.cap)
env, m, d = sim.env, sim.env.model, sim.env.data

# ── 物理真值 ──
pb = m.body("peg").id
gi = m.body_geomadr[pb]
true_center = np.asarray(d.geom_xpos[gi], float).copy()
half = np.asarray(m.geom_size[gi], float)                 # 3×3×24cm 的杆 (半尺寸)
xmat = np.asarray(d.geom_xmat[gi], float).reshape(3, 3)
la = int(np.argmax(half))
axis = xmat[:, la] / (np.linalg.norm(xmat[:, la]) or 1)
true_len = float(half[la]) * 2
true_site = np.asarray(d.site_xpos[sim._site_ph], float).copy()
true_mouth = np.asarray(sim.geom["hole"], float).copy()
true_goal = np.asarray(sim.geom["goal"], float).copy()

# ── 3D 视图侧 (按 ss_dreamview 的真实代码路径) ──
meta = tr.get("_meta") or {}
mouth_v = np.asarray(meta.get("hole_mouth", sdv._HOLE_MOUTH), float)
hole_v = np.asarray(meta.get("goal", sdv._HOLE), float)
box_v = np.asarray(meta.get("box_center", sdv._BOX_CENTER), float)
if meta.get("demo"):
    center_off = np.zeros(3)
else:                                                     # ← ss_dreamview.py:1077-1079 默认分支
    head_off = np.asarray(meta.get("peg_head_off", np.array([-0.13, 0, -0.01])), float)
    center_off = head_off * 0.5 + np.array([0.035, 0.0, 0.0])
peg_traj = np.asarray(tr["peg"][-1], float)               # tr["peg"] = obs[4:7]
drawn_center = peg_traj + center_off
peg_half_v = np.asarray(sdv._PEG_SIZE, float)

print("\n──────── ① 插槽 (孔口/终点/盒中心): 视图 vs 真值 ────────")
for nm, v, t in (("孔口 mouth", mouth_v, true_mouth), ("终点 goal", hole_v, true_goal)):
    dd = np.asarray(v, float) - np.asarray(t, float)
    print(f"  {nm}: 视图 {np.round(np.asarray(v, float), 4)}  真值 {np.round(np.asarray(t, float), 4)}"
          f"  Δ={np.round(dd * 1000, 1)} mm  |Δ|={np.linalg.norm(dd) * 1000:.1f} mm")
print(f"  盒中心:  视图 {np.round(box_v, 4)}  真值 {np.round(np.asarray(sim.geom.get('box_center'), float), 4)}")

print("\n──────── ② 光模块 (绘制位置/尺寸): 视图 vs 真值 ────────")
print(f"  meta 里有 peg_head_off 吗: {'peg_head_off' in meta}  (没有→走写死默认 [-0.13,0,-0.01])")
print(f"  视图 _peg_center_off = {np.round(center_off, 4)}  (ss_dreamview 常量 {np.round(sdv._PEG_CENTER_OFF, 4)})")
print(f"  tr['peg'][-1] (obs peg_pos) = {np.round(peg_traj, 4)}")
print(f"  真值 光模块几何中心        = {np.round(true_center, 4)}")
print(f"  真值 光模块头 site         = {np.round(true_site, 4)}")
print(f"  → 视图画的中心 = {np.round(drawn_center, 4)}")
dd = drawn_center - true_center
print(f"  → 画的 vs 真值 Δxyz = {np.round(dd * 1000, 1)} mm |Δ|={np.linalg.norm(dd) * 1000:.1f} mm"
      f"   (水平: Δx={dd[0] * 1000:+.1f} Δy={dd[1] * 1000:+.1f} mm, 竖直 Δz={dd[2] * 1000:+.1f} mm)")
print(f"  → 尺寸: 视图画 {np.round(peg_half_v, 3)} (2×半尺寸 = {peg_half_v[0] * 2 * 100:.0f}cm 长)"
      f" / 真值 {np.round(half, 3)} (2× = {true_len * 100:.0f}cm 长)")

print("\n──────── ③ 结论量: 画出来的光模块 相对 插槽 在哪 ────────")
ax = (true_goal - true_mouth)
ax = ax / (np.linalg.norm(ax) or 1)
for nm, c in (("真值光模块", true_center), ("视图画的光模块", drawn_center)):
    dl = c - true_mouth
    dep = float(np.dot(dl, ax))
    lat = float(np.linalg.norm(dl - dep * ax))
    print(f"  {nm:14s} 相对孔口: 沿孔轴 {dep * 1000:+8.1f} mm · 横向(垂直孔轴) {lat * 1000:7.1f} mm")
print("  (视图侧横向偏差 = 用户看到的光模块与插槽的相对错位)")
sys.exit(0)
