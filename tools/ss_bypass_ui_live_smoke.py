#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真实 X 显示 (非 offscreen) 冒烟: 把旁路窗真的显示到 :0, 截图取证后自动关闭

不碰控制台 (独立进程), 只读数据源。
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, "/home/ubuntu/lerobot-smolvla-lew/tools/gui")
from PyQt5 import QtCore, QtWidgets          # noqa: E402

import ss_bypass_view as V                    # noqa: E402

OUT = os.path.expanduser("~/zmax_data/20260918_bypass_ui")
os.makedirs(OUT, exist_ok=True)
app = QtWidgets.QApplication(sys.argv)
win = V.SSBypassView()
win.show()
for _ in range(40):                            # 等窗口映到 X 并刷新 5 次
    app.processEvents()
    time.sleep(0.25)
win.refresh()
app.processEvents()
png = os.path.join(OUT, "live_screen.png")
win.grab().save(png)
geo = win.geometry()
minsz = win.minimumSizeHint()
print("窗口几何:", geo.x(), geo.y(), geo.width(), geo.height(), "| 内容最小尺寸:", minsz.width(), minsz.height())
print("屏幕: eDP-1 3200x2000 +2400x0, DP-1-0 3840x2160 +3200+0 (总 7040x2160) → 窗口放得下:",
      minsz.height() <= 2000 and minsz.width() <= 3840)
print("截图 (Qt 自抓, 可直接打开看):", png)
print("插入力 |F| =", win.labs["p_pose_fmag"].text(), "| 真机波形点数:",
      {k: len(v) for k, v in win.curve_real.data.items()})
print("refresh 异常自检 lat_foot =", win.lab_foot.text()[:80])
win.close()
print("已关闭 (未影响控制台)")
