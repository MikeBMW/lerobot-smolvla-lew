#!/usr/bin/env python3
"""把抓下来的窗口画面 与 我这边已知状态的引擎渲染 做像素级比对

判定链: 窗口左窗格 = ? 
  A 引擎初始 (光模块躺台面)  B 引擎 L2 跑完终局 (光模块已进槽, 已核实图里同轴 0.3px)
输出: 每个候选的相关 + 绿像素(光模块体)质心/包围盒, 并给出"窗口绿块 vs 候选绿块"的像素差。
用法: DISPLAY=:0 gui-venv311/bin/python tools/diag_compare_window_render.py <窗口PNG> <候选PNG...>
"""
import sys

import numpy as np
import cv2

win = cv2.imread(sys.argv[1])
if win is None:
    print("读不到窗口图")
    sys.exit(1)
cands = [(p.split("/")[-1], cv2.imread(p)) for p in sys.argv[2:]]
print(f"窗口 {win.shape[1]}x{win.shape[0]}")


def green(bgr):
    b, g, r = bgr[:, :, 0].astype(int), bgr[:, :, 1].astype(int), bgr[:, :, 2].astype(int)
    m = (g - np.maximum(r, b)) > 40
    n = int(m.sum())
    if not n:
        return 0, None, None
    ys, xs = np.nonzero(m)
    return n, (float(xs.mean()), float(ys.mean())), (int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max()))


best = None
for nm, c in cands:
    if c is None:
        continue
    bst = (-9, None, None, None)
    for s in np.arange(0.4, 2.8, 0.02):
        t = cv2.resize(c, None, fx=float(s), fy=float(s), interpolation=cv2.INTER_AREA)
        if t.shape[0] >= win.shape[0] or t.shape[1] >= win.shape[1]:
            continue
        res = cv2.matchTemplate(win, t, cv2.TM_CCOEFF_NORMED)
        _mn, mx, _ml, loc = cv2.minMaxLoc(res)
        if mx > bst[0]:
            bst = (mx, float(s), loc, t.shape)
    corr, s, loc, tsh = bst
    x0, y0 = loc
    h, w = tsh[:2]
    patch = win[y0:y0 + h, x0:x0 + w]
    resz = cv2.resize(c, (w, h), interpolation=cv2.INTER_AREA)
    nw, cw, bbw = green(patch)
    nt, ct, bbt = green(resz)
    print(f"\n候选 {nm}: 相关 {corr:.4f} @缩放 {s:.2f} @位置 {loc}")
    print(f"   窗口窗格 绿像素 {nw} 质心 {None if cw is None else np.round(cw, 1)} bbox {bbw}")
    print(f"   候选帧   绿像素 {nt} 质心 {None if ct is None else np.round(ct, 1)} bbox {bbt}")
    if cw and ct:
        print(f"   → 质心差 {abs(cw[0] - ct[0]):.1f} x {abs(cw[1] - ct[1]):.1f} px"
              f"  (≤3px = 同一状态同机位)")
    cv2.imwrite(f"/tmp/pane_from_window_{nm}.png", patch)
    if best is None or corr > best[0]:
        best = (corr, nm, loc, tsh)
print(f"\n→ 最匹配: {best[1]} (相关 {best[0]:.4f}); 窗格已存 /tmp/pane_from_window_*.png")
sys.exit(0)
