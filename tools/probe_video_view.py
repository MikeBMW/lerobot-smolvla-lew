#!/usr/bin/env python3
"""🎥 挖操作视频 (metaworld peg-insert-side-v3, camera=corner2) 的真实相机与几何

输出:
  1. corner2 相机 world 位姿 (pos/quat/fovy) + 视线方向 → 换算成 pyqtgraph 相机 (elevation/azimuth/distance)
  2. 世界 +X/+Y/+Z 在画面里的方向 (含视频 np.rot90(k=2) 180° 旋转后的方向)
  3. 复位后真实几何: 末端/插销/孔位 世界坐标 (给状态空间仿真对齐用)
用法: MUJOCO_GL=egl gui-venv311/bin/python tools/probe_video_view.py
"""
import os
import sys

os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("MUJOCO_EGL_DEVICE", "0")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import numpy as np  # noqa: E402
from train_full_pipeline import make_env, get_obs  # noqa: E402

env = make_env(0)
o = get_obs(env)
m, d = env.model, env.data

cid = m.camera("corner2").id
cam_pos = np.array(m.cam_pos[cid], dtype=float)
cam_quat = np.array(m.cam_quat[cid], dtype=float)
fovy = float(m.cam_fovy[cid])


def quat2mat(q):
    w, x, y, z = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
    ])


R = quat2mat(cam_quat)          # 相机→世界
fwd = -R[:, 2]                  # mujoco 相机看向自身 -Z
up = R[:, 1]
right = R[:, 0]

sites = {}
for nm in ("endEffector", "pegGrasp", "pegHead", "hole", "goal"):
    try:
        sites[nm] = np.array(d.site_xpos[m.site(nm).id], dtype=float)
    except Exception:
        pass

target = sites.get("pegGrasp", np.zeros(3))
vec = target - cam_pos
dist = float(np.linalg.norm(vec))

# pyqtgraph 相机: elevation = 视线与水平面夹角(向下为正), azimuth = 视线在 xy 平面方位角
horiz = float(np.linalg.norm(fwd[:2]))
elev_pg = float(np.degrees(np.arctan2(-fwd[2], horiz)))         # 俯视为正
az_look = float(np.degrees(np.arctan2(fwd[1], fwd[0])))          # 视线方位
az_pg = (az_look + 180.0) % 360.0                                # pyqtgraph 用"相机相对中心"的方位

print("═══ 1) 操作视频相机 (metaworld corner2) ═══")
print(f"cam_pos  = {cam_pos.round(4)}")
print(f"cam_quat = {cam_quat.round(4)}   fovy = {fovy}")
print(f"视线方向 fwd = {fwd.round(4)}   up = {up.round(4)}   right = {right.round(4)}")
print(f"→ 换算 pyqtgraph: elevation = {elev_pg:.1f}°   azimuth = {az_pg:.1f}°   "
      f"distance(到 peg) = {dist:.3f}m")
print(f"  (当前 3D 视图是 elevation=88 azimuth=270 的正俯视 → 差 {88 - elev_pg:.0f}° 俯角)")

print("\n═══ 2) 世界坐标轴在画面里的方向 ═══")
for nm, ax in (("+X", np.array([1, 0, 0.])), ("+Y", np.array([0, 1, 0.])), ("+Z", np.array([0, 0, 1.]))):
    sx = float(np.dot(ax, right))     # 画面右为正
    sy = float(np.dot(ax, up))        # 画面上为正
    d1 = ("右" if sx > 0.05 else "左" if sx < -0.05 else "—")
    d2 = ("上" if sy > 0.05 else "下" if sy < -0.05 else "—")
    # 视频里 aligner 分支做了 np.rot90(k=2) → 画面 180° 旋转 (左右+上下都反)
    d1r = ("左" if sx > 0.05 else "右" if sx < -0.05 else "—")
    d2r = ("下" if sy > 0.05 else "上" if sy < -0.05 else "—")
    print(f"  世界 {nm}: 原始画面 → {d1}{d2} (右{sx:+.2f}/上{sy:+.2f})   "
          f"视频(rot180 后) → {d1r}{d2r}")

print("\n═══ 3) 复位后真实几何 (状态空间仿真该对齐的坐标) ═══")
for nm, p in sites.items():
    print(f"  {nm:<12} = {p.round(4)}")
print(f"  obs[0:3] 末端  = {o[0:3].round(4)}")
print(f"  obs[3]  夹爪  = {o[3]:.4f}")
print(f"  obs[4:7] 插销  = {o[4:7].round(4)}")
print(f"  obs[36:39] 孔位= {o[36:39].round(4)}")
hand, peg, hole = o[0:3], o[4:7], o[36:39]
print(f"  末端→插销 距离 = {np.linalg.norm(hand - peg):.4f}m   "
      f"插销→孔位 距离 = {np.linalg.norm(peg - hole):.4f}m")
env.close()
