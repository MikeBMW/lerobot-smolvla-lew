#!/usr/bin/env python3
"""老倪说"插销没插进插槽、横向有偏差" → 先搞清他屏幕上那副画面到底是哪个状态。

做法: 生成两个**已知状态**的候选帧(metaworld corner2 同机位渲染)
  ① 初始/idle 状态 (光模块平躺台面) ② L2 跑完的终局 (光模块应已插进槽)
然后用多尺度模板匹配在抓下来的窗口画面里找: 哪个候选出现在窗口上, 匹配处的"绿色光模块"
质心与候选帧的绿色质心差多少 → 判定他看到的是哪一态。

用法: DISPLAY=:0 gui-venv311/bin/python tools/diag_who_is_on_screen.py [窗口PNG=/tmp/win_now.png]
"""
import os
import sys

os.environ.setdefault("DISPLAY", ":0")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "gui"))

import numpy as np                                       # noqa: E402
import cv2                                               # noqa: E402
import state_space_sim_real as ssr                       # noqa: E402

WIN = sys.argv[1] if len(sys.argv) > 1 else "/tmp/win_now.png"


def green_stats(bgr):
    """绿色像素 (光模块: mujoco rgba 0.3/1.0/0.3) 的计数与质心 (归一化)"""
    b, g, r = bgr[:, :, 0].astype(int), bgr[:, :, 1].astype(int), bgr[:, :, 2].astype(int)
    m = (g - np.maximum(r, b)) > 40
    n = int(m.sum())
    if n == 0:
        return 0, None
    ys, xs = np.nonzero(m)
    h, w = bgr.shape[:2]
    return n, (float(xs.mean()) / w, float(ys.mean()) / h)


sim = ssr.RealStateSpaceSim(log=lambda *a: None, seed=104, vision=False, mode="insert")
sim._reset(104)
cand_initial = np.asarray(sim.env.render()).copy()                       # RGB
cv2.imwrite("/tmp/cand_initial.png", cand_initial[:, :, ::-1])
tr = sim.run(cap="L2")
cand_final = np.asarray(sim.env.render()).copy()
cv2.imwrite("/tmp/cand_final.png", cand_final[:, :, ::-1])
d = sim.env.data
ph = np.asarray(d.site_xpos[sim._site_ph], float)
hole = np.asarray(sim.geom["hole"], float)
print(f"候选帧已生成: 初始 {cand_initial.shape} / 终局 {cand_final.shape}")
print(f"终局真值: 光模块头 {np.round(ph, 4)} · 孔口 {np.round(hole, 4)}"
      f" · done={bool(tr['done'][-1])} · 阶段={tr['stage'][-1]}")

win = cv2.imread(WIN)
if win is None:
    print(f"读不到窗口图 {WIN}")
    sys.exit(1)
print(f"窗口画面: {win.shape[1]}x{win.shape[0]}")

print("\n════ 多尺度模板匹配: 窗口里出现的是哪个候选 ════")
best_overall = None
for nm, cand in (("初始/idle", cand_initial), ("L2 终局", cand_final)):
    best = (-9, None, None, None)
    for s in np.arange(0.4, 2.6, 0.05):
        t = cv2.resize(cand[:, :, ::-1], None, fx=float(s), fy=float(s), interpolation=cv2.INTER_AREA)
        if t.shape[0] >= win.shape[0] or t.shape[1] >= win.shape[1]:
            continue
        res = cv2.matchTemplate(win, t, cv2.TM_CCOEFF_NORMED)
        _mn, mx, _ml, ml = cv2.minMaxLoc(res)
        if mx > best[0]:
            best = (mx, float(s), ml, t.shape)
    corr, s, loc, tshape = best
    print(f"  {nm:10s} 最佳相关 {corr:.3f} @缩放 {s:.2f} 位置 {loc} 尺寸 {tshape}")
    if best_overall is None or corr > best_overall[0]:
        best_overall = (corr, nm, s, loc, tshape)

corr, nm, s, loc, tshape = best_overall
print(f"\n→ 窗口上最像的是【{nm}】 (相关 {corr:.3f})")
x0, y0 = loc
h, w = tshape[:2]
patch = win[y0:y0 + h, x0:x0 + w]
tpl = (cand_initial if nm.startswith("初始") else cand_final)[:, :, ::-1]
tpl = cv2.resize(tpl, (w, h), interpolation=cv2.INTER_AREA)
n_w, c_w = green_stats(patch)
n_t, c_t = green_stats(tpl)
print(f"  窗口区域 绿色像素 {n_w} 质心 {None if c_w is None else np.round(c_w, 3)}")
print(f"  候选帧   绿色像素 {n_t} 质心 {None if c_t is None else np.round(c_t, 3)}")
if c_w and c_t:
    dd = (abs(c_w[0] - c_t[0]) * w, abs(c_w[1] - c_t[1]) * h)
    print(f"  → 光模块像素质心差 {dd[0]:.0f} × {dd[1]:.0f} px  (小=就是这一态)")
sys.exit(0)
