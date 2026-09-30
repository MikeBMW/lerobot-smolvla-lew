#!/usr/bin/env python3
"""看看「引擎未运行」时输入图像窗口里那副画面到底是什么 (老倪: 「光模块没插进槽, 水平差一段」)

那副画面 = node_logic._YOLO_ALIGNER.env 的渲染 (只 reset、从不 step 的对齐器环境)。
这里用**同一对象/同一渲染**量它的真实布局: 光模块在哪、盒子插槽在哪、差多少。
跑法: DISPLAY=:0 gui-venv311/bin/python tools/diag_idle_frame_scene.py
"""
import os
import sys

os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "gui"))

import numpy as np                                       # noqa: E402
from PyQt5 import QtWidgets                              # noqa: E402

app = QtWidgets.QApplication(sys.argv[:1])
import node_logic as nl                                  # noqa: E402

al = nl._yolo_ensure_aligner(lambda *a: None)
env = al.env
m, d = env.model, env.data
img = np.asarray(env.render())
print(f"渲染帧: shape={img.shape} 均值={img.mean():.1f} (引擎 idle 用的就是这一帧)")

pb = m.body("peg").id
gi = m.body_geomadr[pb]
c = np.asarray(d.geom_xpos[gi], float)
half = np.asarray(m.geom_size[gi], float)
xmat = np.asarray(d.geom_xmat[gi], float).reshape(3, 3)
la = int(np.argmax(half))
ax = xmat[:, la] / (np.linalg.norm(xmat[:, la]) or 1)
L = float(half[la])
print(f"光模块: 中心 {np.round(c, 4)} 长轴 {np.round(ax, 3)} 半长 {L * 100:.1f}cm"
      f" 两端 {np.round(c - ax * L, 4)} ~ {np.round(c + ax * L, 4)}")

h = np.asarray(d.site_xpos[m.site("hole").id], float)
g = np.asarray(d.site_xpos[m.site("goal").id], float)
print(f"盒子插槽: 孔口 {np.round(h, 4)} 终点 {np.round(g, 4)}")

dxy = c[:2] - h[:2]
print(f"→ 光模块中心 到 插槽孔口 的水平距离 = {float(np.linalg.norm(dxy)) * 1000:.0f} mm"
      f" (Δx={dxy[0] * 1000:+.0f}mm, Δy={dxy[1] * 1000:+.0f}mm)")
print(f"→ 竖直(z)差 = {(c[2] - h[2]) * 1000:+.0f} mm  (插槽在 13cm 高处, 光模块躺在台面)")
print("\n结论: 静态初始帧里 光模块躺在台面上、离插槽有水平距离 — 这是 metaworld 初始场景, 不是运行结果")
sys.exit(0)
