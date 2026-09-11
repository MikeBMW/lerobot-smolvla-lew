# -*- coding: utf-8 -*-
"""量孔容差 (2026-09-11): block_inner(孔) 与 peg 的实际尺寸 → 定矩形截面的安全上限
用法: MUJOCO_GL=glfw gui-venv311/bin/python tools/measure_hole.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("MUJOCO_GL", "glfw")
import numpy as np  # noqa: E402
import gen_l4_demo_video as G  # noqa: E402

d = G.L4Demo(seed=0, record=False)
m, dat = d.env.model, d.env.data
print("== meshes ==")
for i in range(m.nmesh):
    name = m.names[m.name_meshadr[i]:].split(b"\x00")[0].decode(errors="replace")
    if any(k in name for k in ("block", "peg")):
        adr, num = int(m.mesh_vertadr[i]), int(m.mesh_vertnum[i])
        v = m.mesh_vert[adr:adr + num].reshape(-1, 3)
        print(f"  {name:22s} n={num:5d} 半尺寸(局部)={np.round((v.max(0) - v.min(0)) / 2, 4)} "
              f"中心={np.round((v.max(0) + v.min(0)) / 2, 4)}")
print("== geoms (peg / block 相关) ==")
for i in range(m.ngeom):
    name = m.names[m.name_geamadr[i]:].split(b"\x00")[0].decode(errors="replace") if hasattr(m, "name_geamadr") else ""
    if name and ("peg" in name or "block" in name):
        print(f"  geom {name:26s} type={int(m.geom_type[i])} size={np.round(m.geom_size[i], 4)} "
              f"pos={np.round(m.geom_pos[i], 4)}")
print("== 孔径判据 (site hole 位置与前向 clearance) ==")
sid = m.site("hole").id
print("  hole site 世界位置:", np.round(dat.site_xpos[sid], 4))
print("  peg 半尺寸:", np.round(m.geom_size[m.geom("peg").id], 4),
      " · peg 体位置:", np.round(dat.xpos[m.body("peg").id], 4))
print("  📌 block_inner(孔腔) 半尺寸 见上表 —— 矩形截面必须 <= 该值")
try:
    d.env.close()
except Exception:
    pass
