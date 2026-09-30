#!/usr/bin/env python3
"""终局几何核对: 光模块(绿杆) 与 盒子插槽 的真实相对位置 (老倪: 「没插进槽, 水平相差一段距离」)

不看站点, 看**几何体本身**:
  · 光模块 geom (box 0.015/0.015/0.12 = 3×3×24cm) 的中心/长轴/两端世界坐标
  · 盒子插槽 = 盒子那两块 3cm 立柱 (geom size[0]=0.03) 之间的走廊: 中心线 + 净宽
  · 结论量: 光模块轴心 到 走廊中心的**水平横向偏差** / 光模块探入盒内的深度

跑法: DISPLAY=:0 gui-venv311/bin/python tools/diag_insert_geom_truth.py [--vision 0/1] [--seed 104]
"""
import argparse
import os
import sys

os.environ.setdefault("DISPLAY", ":0")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "gui"))

import numpy as np                                       # noqa: E402
import state_space_sim_real as ssr                       # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--vision", type=int, default=0)
ap.add_argument("--seed", type=int, default=104)
ap.add_argument("--cap", default="L2")
ap.add_argument("--mode", default="insert", help="insert=L2 插装 / full=L3·L4 全链(插拔+AOI+放回)")
a = ap.parse_args()


def geom_axes(d, gi):
    """geom 的世界中心 + 三个轴 (列向量)"""
    xmat = np.asarray(d.geom_xmat[gi], float).reshape(3, 3)
    return np.asarray(d.geom_xpos[gi], float).copy(), xmat


def describe(env, tag):
    m, d = env.model, env.data
    print(f"\n===== {tag} =====")
    # 光模块
    peg_bid = m.body("peg").id
    peg_gis = list(range(m.body_geomadr[peg_bid], m.body_geomadr[peg_bid] + m.body_geomnum[peg_bid]))
    peg_gis = [g for g in peg_gis if int(m.geom_type[g]) in (6, 5, 3, 7)]
    if not peg_gis:
        print("  找不到光模块几何体"); return
    gi = peg_gis[0]
    c, xm = geom_axes(d, gi)
    half = np.asarray(m.geom_size[gi], float)
    long_ax = int(np.argmax(half))                 # 长轴 = 半尺寸最大那维
    axis_w = xm[:, long_ax] / (np.linalg.norm(xm[:, long_ax]) or 1.0)
    L = float(half[long_ax])
    print(f"  光模块 geom#{gi} 类型={int(m.geom_type[gi])} 半尺寸={half} 长轴(局部{ 'xyz'[long_ax] })"
          f" → 世界 {np.round(axis_w, 3)} 半长 {L * 100:.1f}cm")
    print(f"    中心 {np.round(c, 4)} · 两端 {np.round(c - axis_w * L, 4)} ～ {np.round(c + axis_w * L, 4)}")
    # 盒子插槽 (两块 3cm 立柱)
    box_bid = m.body("box").id
    walls = []
    for g in range(m.body_geomadr[box_bid], m.body_geomadr[box_bid] + m.body_geomnum[box_bid]):
        sz = np.asarray(m.geom_size[g], float)
        if int(m.geom_type[g]) == 6 and abs(sz[0] - 0.03) < 1e-6 and abs(sz[2] - 0.03) < 1e-6:
            walls.append(g)
    print(f"  盒子插槽立柱 geom: {walls}")
    if len(walls) == 2:
        w0 = np.asarray(d.geom_xpos[walls[0]], float)
        w1 = np.asarray(d.geom_xpos[walls[1]], float)
        mid = (w0 + w1) / 2.0
        sep = w1 - w0
        sep_n = sep / (np.linalg.norm(sep) or 1.0)
        gap = float(np.linalg.norm(sep)) - 0.03        # 两立柱内面间距 = 走廊净宽
        print(f"    立柱中心 {np.round(w0, 4)} / {np.round(w1, 4)} · 中心线中点 {np.round(mid, 4)}"
              f" · 净宽 {gap * 100:.1f}cm · 分离方向 {np.round(sep_n, 3)}")
        # 光模块轴心到走廊中心线的横向偏差 = (中心-中点) 去掉沿 sep_n 分量后的模
        dlt = c - mid
        lat = float(np.linalg.norm(dlt - np.dot(dlt, sep_n) * sep_n))
        print(f"    → 光模块轴心 到 走廊中心线 的横向偏差 = {lat * 1000:.1f} mm"
              f"   (走廊净宽 {gap * 1000:.0f} mm, 偏差 < 净宽一半 = 在槽内)")
        print(f"    → 沿轴心方向: 光模块中心偏移分量 {np.dot(dlt, sep_n) * 1000:+.1f} mm")


env = ssr._make_env()
sim = ssr.RealStateSpaceSim(log=lambda *a_: None, seed=a.seed, vision=bool(a.vision), mode=a.mode)
sim._reset(a.seed)
describe(sim.env, f"初始 (reset seed={a.seed}) — 没跑之前")
tr = sim.run(cap=a.cap)
describe(sim.env, f"▶运行结束 (vision={a.vision} cap={a.cap} mode={a.mode} seed={a.seed}) done="
                  f"{bool(tr.get('done', [False])[-1])} 步数={len(tr.get('stage') or [])}")
st = tr.get("stage") or []
print("阶段序列:", " → ".join([s for i, s in enumerate(st) if i == 0 or st[i - 1] != s]))
sys.exit(0)
