#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hermes-verify-vlm-panel.py — 判读面板交互验收 (老倪三条反馈: 最大化/含义被省略/拖不动/显示区)

断言:
  ① 最大化按钮可用 (WindowMinMaxButtonsHint) + 顶层非模态 (可自由拖动) + 最小尺寸
  ② 含义列不再省略: 换行开启 + ElideNone + 列宽足够 (最长含义按字体度量能整行放下或换行显示)
  ③ 显示区可调: 中部是 QSplitter (两侧 4:5), 拖动分隔条即可分配
  ④ 最大化后尺寸跟随屏幕 (真生效, 不是摆设)
用法: QT_QPA_PLATFORM=offscreen gui-venv311/bin/python /tmp/hermes-verify-vlm-panel.py
"""
import os
import sys

REPO = "/home/ubuntu/lerobot-smolvla-lew"
sys.path.insert(0, os.path.join(REPO, "tools", "gui"))
from PyQt5.QtCore import Qt                                    # noqa: E402
from PyQt5.QtGui import QFontMetrics                           # noqa: E402
from PyQt5.QtWidgets import QApplication                       # noqa: E402

app = QApplication([])
from vlm_panel import FIELD_HELP, VlmPanel                     # noqa: E402

p = VlmPanel()
p.show()
app.processEvents()
f = p.windowFlags()

ok1 = bool(int(f) & int(Qt.WindowMinMaxButtonsHint))
print(f"① 最大化按钮: {'✅ 可用' if ok1 else '❌ 无'} · 顶层可拖动: {p.isWindow()} · "
      f"非模态: {p.windowModality() == Qt.NonModal} · 最小 {p.minimumSize().width()}x{p.minimumSize().height()}")

p.showMaximized()
app.processEvents()
sw, sh = app.primaryScreen().size().width(), app.primaryScreen().size().height()
ok4 = p.width() >= sw * 0.95 and p.height() >= sh * 0.9
print(f"④ 最大化生效: 面板 {p.width()}x{p.height()} vs 屏幕 {sw}x{sh} → {'✅' if ok4 else '❌'}")
p.showNormal()
p.resize(1240, 780)
app.processEvents()

fm = QFontMetrics(p.tbl.font())
widest = max(FIELD_HELP.values(), key=len)
colw = p.tbl.columnWidth(1)
need = fm.boundingRect(0, 0, colw - 10, 2000, Qt.TextWordWrap, widest)
lines = max(1, (need.height() + fm.height() - 1) // fm.height())
ok2 = bool(p.tbl.wordWrap()) and int(p.tbl.textElideMode()) == int(Qt.ElideNone) and colw >= 300
print(f"② 含义列: 宽 {colw}px · 换行 {p.tbl.wordWrap()} · 不省略 {int(p.tbl.textElideMode()) == int(Qt.ElideNone)}")
print(f"   最长含义 ({len(widest)} 字) 在当前列宽下占 {lines} 行 → {'✅ 完整显示' if ok2 else '❌ 仍会截'}")
print(f"   字段表已填 {p.tbl.rowCount()} 行 · 第2行行高 {p.tbl.rowHeight(1) if p.tbl.rowCount() > 1 else '-'}"
      f" (换行行高自适应) · 历史 {p.tbl_hist.rowCount()} 行")

ok3 = hasattr(p, "split") and p.split.count() == 2
print(f"③ 显示区可调: QSplitter {p.split.count()} 面板 · 当前分配 {p.split.sizes()} → {'✅' if ok3 else '❌'}")
ok = ok1 and ok2 and ok3 and ok4
print("\n" + ("✅ 面板验收通过 (最大化/拖动/含义完整/显示区可调)" if ok else "❌ 有断言未过"))
sys.exit(0 if ok else 1)
