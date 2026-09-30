#!/usr/bin/env python3
"""📐 挖 metaworld peg-insert-side-v3 真实场景几何 (给 3D 视图 1:1 复刻)

输出: 机器人底座/桌面/光模块/孔位盒 的世界坐标与尺寸
用法: MUJOCO_GL=egl gui-venv311/bin/python tools/probe_scene_geom.py
"""
import os
import sys

os.environ.setdefault("MUJOCO_GL", "egl")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np  # noqa: E402
from train_full_pipeline import make_env  # noqa: E402

env = make_env(0)
m, d = env.model, env.data
print("═══ body (含 base/table/peg/box) ═══")
for i in range(m.nbody):
    nm = m.body(i).name
    if any(k in nm.lower() for k in ("base", "table", "peg", "box", "hole", "pedestal", "link0")):
        print(f"  body {nm:<28} pos={np.array(d.xpos[i]).round(4)}")
print("\n═══ geom 尺寸 (peg/box/table) ═══")
for i in range(m.ngeom):
    nm = m.geom(i).name or f"geom{i}"
    if any(k in nm.lower() for k in ("peg", "box", "table", "hole")):
        print(f"  geom {nm:<24} type={m.geom_type[i]} size={np.array(m.geom_size[i]).round(4)} "
              f"pos={np.array(d.geom_xpos[i]).round(4)}")
print("\n═══ site ═══")
for i in range(m.nsite):
    nm = m.site(i).name
    print(f"  site {nm:<22} pos={np.array(d.site_xpos[i]).round(4)}")
print("\n═══ 关节数/动作维 ═══")
print(f"  nq={m.nq} nv={m.nv} nu={m.nu}  action_space={env.action_space.shape}")
env.close()
