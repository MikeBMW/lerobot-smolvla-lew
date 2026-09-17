#!/usr/bin/env python3
"""判定窗口上那副画面 = 哪个状态 (用"绿色光模块"的像素位置做指纹, 不靠整体相关)

候选:
  A 引擎初始 (RealStateSpaceSim reset)      — 光模块躺台面
  B 引擎 L2 跑完 (光模块应插进槽)           — 终局
  C idle 帧 (node_logic 对齐器 env 渲染)    — 引擎没在跑时窗口回退显示的就是它
判据: 窗口里绿色像素(光模块)的 数量 + 归一化质心, 与哪个候选一致。

用法: DISPLAY=:0 gui-venv311/bin/python tools/diag_which_state_on_screen.py [窗口PNG]
"""
import os
import sys

os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "gui"))

import numpy as np                                       # noqa: E402
import cv2                                               # noqa: E402
from PyQt5 import QtWidgets                              # noqa: E402

WIN = sys.argv[1] if len(sys.argv) > 1 else "/tmp/win_now.png"


def green_stats(bgr, tag=""):
    b, g, r = bgr[:, :, 0].astype(int), bgr[:, :, 1].astype(int), bgr[:, :, 2].astype(int)
    m = (g - np.maximum(r, b)) > 40
    n = int(m.sum())
    if n == 0:
        print(f"    {tag}: 没有绿色像素")
        return n, None
    ys, xs = np.nonzero(m)
    h, w = bgr.shape[:2]
    print(f"    {tag}: 绿像素 {n} · 质心 ({xs.mean() / w:.3f}, {ys.mean() / h:.3f})"
          f" · 包围盒 x[{xs.min() / w:.3f}~{xs.max() / w:.3f}] y[{ys.min() / h:.3f}~{ys.max() / h:.3f}]")
    return n, (xs.mean() / w, ys.mean() / h)


# ── A/B: 引擎两态 ──
import state_space_sim_real as ssr                        # noqa: E402
sim = ssr.RealStateSpaceSim(log=lambda *a: None, seed=104, vision=False, mode="insert")
sim._reset(104)
A = np.asarray(sim.env.render())[:, :, ::-1].copy()       # BGR
tr = sim.run(cap="L2")
B = np.asarray(sim.env.render())[:, :, ::-1].copy()
print(f"引擎候选: A 初始 / B 终局 (done={bool(tr['done'][-1])}, 阶段={tr['stage'][-1]})")

# ── C: idle 帧 (窗口的真实回退源) ──
app = QtWidgets.QApplication(sys.argv[:1])
import node_logic as nl                                   # noqa: E402
al = nl._yolo_ensure_aligner(lambda *a: None)
C = np.asarray(al.env.render())[:, :, ::-1].copy()
print("idle 候选 C 已生成 (node_logic 对齐器 env)")

win = cv2.imread(WIN)
print(f"\n窗口画面 {win.shape[1]}x{win.shape[0]}")
print("窗口整体绿像素:"); green_stats(win, "窗口")

print("\n各候选帧的绿像素指纹:")
for nm, c in (("A 引擎初始", A), ("B 引擎终局", B), ("C idle 帧", C)):
    green_stats(c, nm)

print("\n多尺度相关 (辅助):")
for nm, c in (("A 引擎初始", A), ("B 引擎终局", B), ("C idle 帧", C)):
    best = (-9, None)
    for s in np.arange(0.4, 2.6, 0.05):
        t = cv2.resize(c, None, fx=float(s), fy=float(s), interpolation=cv2.INTER_AREA)
        if t.shape[0] >= win.shape[0] or t.shape[1] >= win.shape[1]:
            continue
        res = cv2.matchTemplate(win, t, cv2.TM_CCOEFF_NORMED)
        _mn, mx, _ml, _loc = cv2.minMaxLoc(res)
        if mx > best[0]:
            best = (mx, float(s))
    print(f"    {nm:10s} 最佳相关 {best[0]:.3f} @缩放 {best[1]:.2f}")

cv2.imwrite("/tmp/cand_A_engine_initial.png", A)
cv2.imwrite("/tmp/cand_B_engine_final.png", B)
cv2.imwrite("/tmp/cand_C_idle.png", C)
print("\n候选帧已存 /tmp/cand_{A_engine_initial,B_engine_final,C_idle}.png (可直接看)")
sys.exit(0)
