#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""measure_hw_card_fonts.py — 客观测量「硬件资源」卡在各屏(含 192DPI)下的实际字体像素

判据: 每个可见文本行的 fontMetrics().height() (设备像素) 与 font().pixelSize() 打印出来,
      用来向用户报"放大了多少", 而不是靠感觉。
用法: QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/measure_hw_card_fonts.py
"""
import os
import sys

sys.path.insert(0, "/home/ubuntu/zmax_rel/tools/gui")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
import studio  # noqa: E402

card = studio.HardwareCard()
card.resize(1200, 400)
card.show()
app.processEvents()
card.refresh() if hasattr(card, "refresh") else None
app.processEvents()

rows = [("标题 🖥 硬件资源", getattr(card, "_title", None)),
        ("时间戳", card.lb_ts),
        ("GPU/CPU/内存/磁盘/吞吐/节点", card.lb_gpu),
        ("DDS 节点列表", card.lb_nodes),
        ("远端硬件", card.lb_remote),
        ("数据源行", card.lb_src)]
print("屏幕缩放: devicePixelRatio=%.2f · logicalDpiX=%.0f" % (app.devicePixelRatio(), app.primaryScreen().logicalDotsPerInch()))
for name, w in rows:
    if w is None:
        # 标题不是属性 → 从子控件里找第一个 QLabel
        ws = [c for c in card.findChildren(type(card.lb_ts)) if c.text().startswith("🖥")]
        w = ws[0] if ws else None
    if w is None:
        print("  %-30s (未找到)" % name); continue
    f = w.font()
    fm = w.fontMetrics()
    print("  %-30s pixelSize=%-4s pt=%.1f  行高=%3d px  文本=%r" %
          (name, f.pixelSize(), f.pointSizeF(), fm.height(), (w.text() or "")[:34]))
print("卡片最小高度提示: %d px (sizeHint)" % card.sizeHint().height())
