#!/usr/bin/env python3
"""抓指定窗口的画面 → PNG (用 Qt 自己抓, 不依赖 ImageMagick)

用法: DISPLAY=:0 gui-venv311/bin/python tools/grab_window_png.py <window_id> <out.png>
窗口 id 用 `wmctrl -l` 第一列 (0x...)
"""
import os
import sys

os.environ.setdefault("DISPLAY", ":0")
from PyQt5 import QtCore, QtGui, QtWidgets              # noqa: E402

wid = int(sys.argv[1], 0)
out = sys.argv[2]
app = QtWidgets.QApplication(sys.argv[:1])
scr = QtWidgets.QApplication.primaryScreen()
pm = scr.grabWindow(wid)
if pm.isNull():
    print("抓图失败 (窗口 id 不对?)")
    sys.exit(1)
pm.save(out, "PNG")
img = pm.toImage().convertToFormat(QtGui.QImage.Format_RGB888)
print(f"已抓图 {out}: {img.width()}x{img.height()}")
sys.exit(0)
