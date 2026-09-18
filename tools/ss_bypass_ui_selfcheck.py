#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""offscreen 自检: 旁路可视化窗 (波形/字号/重叠) — 不改任何真机状态

① 真的构造窗口并 refresh → 抓异常
② 打印各通道点数 → 证明位姿 XYZ / 插入力 真进了波形
③ 渲染 PNG (人工可看)
④ 用真实字体度量算所有文本矩形 → 断言互不重叠 (老倪报的"名称与描述重叠")
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, "/home/ubuntu/lerobot-smolvla-lew/tools/gui")

from PyQt5 import QtCore, QtGui, QtWidgets      # noqa: E402

import ss_bypass_view as V                       # noqa: E402

OUT = os.path.expanduser("~/zmax_data/20260918_bypass_ui")
os.makedirs(OUT, exist_ok=True)

app = QtWidgets.QApplication(sys.argv)
win = V.SSBypassView()
win.resize(1620, 980)
win.show()
app.processEvents()
win.refresh()
app.processEvents()

print("=" * 60)
print("① 窗口构造 + refresh:", "无异常")
print("   窗口标题:", win.windowTitle())
print("   波形组件: 状态空间", len(V.BANDS_SS), "通道 / 真机", len(V.BANDS_REAL), "通道")
for name, cw in (("状态空间", win.curve), ("真机", win.curve_real)):
    for k, pts in cw.data.items():
        last = pts[-1] if pts else None
        print(f"   [{name}] {k:10s} 点数 {len(pts):4d}  最新 {last[1] if last else '—'}")
print("   插入力面板 |F| =", win.labs["p_pose_fmag"].text(),
      "· Fz =", win.labs["p_pose_fz"].text(),
      "· Fx,Fy,Fz =", win.labs["p_pose_f3"].text())
print("   TCP XYZ =", win.labs["p_pose_xyz"].text())
print("   六维力 =", win.labs["src_ft"].text())

win.grab().save(os.path.join(OUT, "bypass_window.png"))
win.curve_real.grab().save(os.path.join(OUT, "band_real.png"))
win.curve.grab().save(os.path.join(OUT, "band_ss.png"))
print("② 渲染:", os.path.join(OUT, "bypass_window.png"))

print("③ 文本矩形重叠检查 (用组件自己的 layout() → 断言的就是真实绘制矩形):")
bad = 0
for cw in (win.curve, win.curve_real):
    g = cw.layout()
    fm_t, fm_v, fm_a = g["fm_t"], g["fm_v"], g["fm_a"]
    print(f"   [{cw.title[:14]}] {cw.width()}x{cw.height()} 泳道高 {g['band_h']}px · 左栏 {g['gutter']}px"
          f" · 右栏 {g['right_w']}px · 绘图区宽 {g['x1'] - g['x0']}px")
    for i, b in enumerate(cw.bands):
        gi = g["bands"][i]
        series = cw.data.get(b["key"]) or []
        txt = ((b.get("fmt") or (lambda v: f"{v:.4f}"))(series[-1][1]) if series else "—") \
            + ((" " + b["unit"]) if b.get("unit") else "")
        v_rect = QtCore.QRect(gi["value_rect"].x(), gi["value_rect"].y(),
                              fm_v.horizontalAdvance(txt), fm_v.height())
        left = gi["title_rect"].united(v_rect)
        for pname, a, c in (("名↕值", gi["title_rect"], v_rect),
                            ("左栏⌐右上", left, gi["hi_rect"]),
                            ("左栏⌐右下", left, gi["lo_rect"]),
                            ("右上↕右下", gi["hi_rect"], gi["lo_rect"])):
            if a.intersects(c):
                bad += 1
                print(f"      ❌ 重叠 {b['title']} {pname}: {a.getRect()} × {c.getRect()}")
        fit = gi["value_baseline"] + fm_v.descent() - gi["y0"]
        print(f"      {b['title']:10s} 名baseline y0+{gi['title_baseline'] - gi['y0']:3d} ·"
              f" 值baseline y0+{gi['value_baseline'] - gi['y0']:3d} (值底 y0+{fit})"
              f" · 泳道高 {g['band_h']} → 余量 {g['band_h'] - fit}px · 值文本 {txt}")
print("   重叠对数:", bad, "→", "✅ 无重叠" if bad == 0 else "❌ 仍有重叠")

print("④ 字号实测 (组件真实字体, 像素高):")
cw = win.curve
f_t, f_v, f_a, f_h = cw._fonts()
for nm, f in (("通道名", f_t), ("当前值", f_v), ("量程刻度/脚注", f_a), ("波形组件标题", f_h),
              ("面板标签(小)", QtGui.QFont(cw.font().family(), 14)),
              ("面板数值(大)", QtGui.QFont(cw.font().family(), 19))):
    fm = QtGui.QFontMetrics(f)
    print(f"   {nm}: {f.pointSize()}pt → 字高 {fm.height()}px, 参考 '插入力 |F|' 宽 = {fm.horizontalAdvance('插入力 |F|')}px")
print("=" * 60)
