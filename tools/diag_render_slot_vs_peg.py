#!/usr/bin/env python3
"""在**渲染图**里定位「插槽」(盒子插槽两侧立柱=蓝色半透明碰撞内壁) 与「光模块」(绿色),

判据全部是像素: 立柱投影点 / 立柱像素块 / 光模块绿像素质心 · 包围盒 → 看 光模块 是否在槽中线上。
用法: DISPLAY=:0 gui-venv311/bin/python tools/diag_render_slot_vs_peg.py
"""
import os
import sys

os.environ.setdefault("DISPLAY", ":0")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "gui"))

import numpy as np                                       # noqa: E402
import cv2                                               # noqa: E402
import state_space_sim_real as ssr                       # noqa: E402

sim = ssr.RealStateSpaceSim(log=lambda *a: None, seed=104, vision=False, mode="insert")
sim._reset(104)
tr = sim.run(cap="L2")
env, m, d = sim.env, sim.env.model, sim.env.data
rgb = np.asarray(env.render())
H, W = rgb.shape[:2]
cv2.imwrite("/tmp/final_render.png", rgb[:, :, ::-1])

cid = m.camera("corner2").id
cpos = np.asarray(d.cam_xpos[cid], float).copy()
cmat = np.asarray(d.cam_xmat[cid], float).reshape(3, 3).copy()
fovy = float(m.cam_fovy[cid])
f = 0.5 * H / np.tan(np.radians(fovy / 2.0))


def proj(p):
    v = np.asarray(p, float) - cpos
    xc, yc, zc = float(cmat[:, 0] @ v), float(cmat[:, 1] @ v), float(cmat[:, 2] @ v)
    depth = -zc
    if depth < 0:
        depth, xc, yc = -depth, -xc, -yc
    return None if depth <= 1e-6 else (W / 2.0 + f * xc / depth, H / 2.0 - f * yc / depth)


# 插槽两侧立柱 (盒子碰撞内壁 6cm×3cm, size[0]==0.03 的 box) — 全模型搜
posts = []
for g in range(m.ngeom):
    sz = np.asarray(m.geom_size[g], float)
    if int(m.geom_type[g]) == 6 and abs(sz[0] - 0.03) < 1e-6:
        posts.append(np.asarray(d.geom_xpos[g], float))
print(f"插槽立柱(碰撞内壁) {len(posts)} 个:")
for p in posts:
    print(f"  世界 {np.round(p, 4)} → 像素 {np.round(proj(p), 1)}")
if len(posts) == 2:
    mid = (posts[0] + posts[1]) / 2.0
    print(f"  槽中线中点 {np.round(mid, 4)} → 像素 {np.round(proj(mid), 1)}")

pb = m.body("peg").id
gi = m.body_geomadr[pb]
pc = np.asarray(d.geom_xpos[gi], float).copy()
print(f"\n光模块中心(真值) {np.round(pc, 4)} → 像素 {np.round(proj(pc), 1)}")

# 像素分析
b, g, r = rgb[:, :, 2].astype(int), rgb[:, :, 1].astype(int), rgb[:, :, 0].astype(int)
gmask = (g - np.maximum(r, b)) > 40
bmask = (b - np.maximum(r, g)) > 8
n, lab, stats, cent = cv2.connectedComponentsWithStats(gmask.astype(np.uint8), 8)
print(f"\n绿色连通块 {max(0, n - 1)} 个 (光模块体 + 可能的 hole 标记):")
for i in range(1, n):
    x, y, w, h, area = stats[i]
    print(f"  #{i} 面积 {area} px  bbox x[{x}~{x + w}] y[{y}~{y + h}]  质心 {np.round(cent[i], 1)}")
print(f"蓝色(盒子碰撞内壁)像素 {int(bmask.sum())} 个 · 质心 "
      f"{None if bmask.sum() == 0 else np.round([np.nonzero(bmask)[1].mean(), np.nonzero(bmask)[0].mean()], 1)}")
sys.exit(0)
