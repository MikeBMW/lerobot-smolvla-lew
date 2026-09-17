#!/usr/bin/env python3
"""终局渲染 + 几何投影 → 字符画 (我看不了图, 但能把"光模块/插槽/盒面"的相对关系读出来)

标记: P=光模块(绿) M=孔口投影 G=终点投影 W=插槽两侧立柱投影 B=盒子+面四角 t=末端夹爪
输出: 480x480 → 96x48 字符, 每格取块均值; 标记优先印在格上。
用法: DISPLAY=:0 gui-venv311/bin/python tools/diag_ascii_geom_overlay.py
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
    if depth <= 1e-6:
        return None
    return (W / 2.0 + f * xc / depth, H / 2.0 - f * yc / depth)


pb = m.body("peg").id
gi = m.body_geomadr[pb]
half = np.asarray(m.geom_size[gi], float)
xmat = np.asarray(d.geom_xmat[gi], float).reshape(3, 3)
la = int(np.argmax(half))
axis = xmat[:, la] / (np.linalg.norm(xmat[:, la]) or 1)
L = float(half[la])
pc = np.asarray(d.geom_xpos[gi], float).copy()
marks = []           # (char, pixel, 说明)
marks.append(("P", proj(pc), "光模块中心"))
marks.append(("1", proj(pc - axis * L), "光模块端(-x)"))
marks.append(("2", proj(pc + axis * L), "光模块端(+x)"))
marks.append(("M", proj(sim.geom["hole"]), "孔口"))
marks.append(("G", proj(sim.geom["goal"]), "终点"))
marks.append(("t", proj(np.asarray(d.site_xpos[sim._site_ph], float)), "光模块头site"))

# 盒子: 两组 3cm 立柱 (插槽内壁) + 盒体外框
box_bid = m.body("box").id
posts, other = [], []
for g in range(m.body_geomadr[box_bid], m.body_geomadr[box_bid] + m.body_geomnum[box_bid]):
    sz = np.asarray(m.geom_size[g], float)
    p = np.asarray(d.geom_xpos[g], float)
    if int(m.geom_type[g]) == 6 and abs(sz[0] - 0.03) < 1e-6:
        posts.append((g, p, sz))
    other.append((g, p, sz, np.asarray(m.geom_rgba[g], float), int(m.geom_contype[g]),
                  int(m.geom_conaffinity[g]), int(m.geom_type[g]), np.asarray(m.geom_xmat[g], float).reshape(3, 3)))
print(f"盒子几何体 {len(other)} 个; 其中 3cm 立柱 {len(posts)} 个 (插槽内壁)")
for g, p, sz, rgba, ct, ca, gt, xm in other:
    nm = {2: "sphere", 3: "capsule", 4: "ellipsoid", 5: "cylinder", 6: "box", 7: "mesh"}.get(gt, str(gt))
    uv = proj(p)
    print(f"  geom#{g} {nm:8s} 半尺寸{np.round(sz, 4)} rgba{np.round(rgba, 2)} "
          f"contype={ct} conaffinity={ca} 世界{np.round(p, 4)} 像素{None if uv is None else np.round(uv, 1)}")
    marks.append(("W" if (np.abs(sz[0] - 0.03) < 1e-6 and gt == 6) else "b", uv, f"geom#{g}"))

# ── 字符画 ──
cols, rows = 110, 55
ch, cw = H / rows, W / cols
b, g, r = rgb[:, :, 2].astype(int), rgb[:, :, 1].astype(int), rgb[:, :, 0].astype(int)
green = (g - np.maximum(r, b)) > 40
grid = [[" " for _ in range(cols)] for _ in range(rows)]
for rr in range(rows):
    for cc in range(cols):
        y0, y1 = int(rr * ch), max(int(rr * ch) + 1, int((rr + 1) * ch))
        x0, x1 = int(cc * cw), max(int(cc * cw) + 1, int((cc + 1) * cw))
        if green[y0:y1, x0:x1].mean() > 0.25:
            grid[rr][cc] = "P"
            continue
        lum = float(rgb[y0:y1, x0:x1].mean())
        grid[rr][cc] = "#" if lum > 110 else ("·" if lum > 55 else " ")
for ch_, uv, _note in marks:
    if uv is None:
        continue
    cc, rr = int(uv[0] / cw), int(uv[1] / ch)
    if 0 <= rr < rows and 0 <= cc < cols:
        grid[rr][cc] = ch_
print(f"\n终局渲染 480x480 → {cols}x{rows}字符 (P=光模块绿体 M=孔口 G=终点 W=插槽立柱 b=盒体其它几何 t=光模块头)")
print("     " + "".join(str(int(c * cw) // 100 % 10) if c % 10 == 0 else " " for c in range(cols)))
for rr in range(rows):
    print(f"{int(rr * ch):4d} " + "".join(grid[rr]))
print("\n关键点像素坐标:")
for ch_, uv, note in marks:
    if uv is not None:
        print(f"  {ch_} {note:14s} ({uv[0]:6.1f}, {uv[1]:6.1f})")
sys.exit(0)
