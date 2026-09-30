#!/usr/bin/env python3
"""验证 yolo_input_viewer._clamp_to_screen 修复: 拖到扩展屏不许被拽回主屏 (2026-09-17)

跑法: gui-venv311/bin/python tools/verify_viewer_clamp_multiscreen.py
被测对象 = 磁盘上真实的 YoloInputViewer._clamp_to_screen (非副本), QApplication.screens() 用假屏幕注入。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "gui"))

from PyQt5 import QtCore, QtWidgets                     # noqa: E402
from PyQt5.QtCore import QRect                          # noqa: E402

import yolo_input_viewer as yiv                         # noqa: E402

_app = QtWidgets.QApplication(sys.argv[:1])


class FakeScreen:
    def __init__(self, r):
        self._r = r

    def availableGeometry(self):
        return self._r


def install_screens(rects):
    """把 QtWidgets.QApplication.screens 换成假屏幕 (PyQt 类不让改属性 → 换掉模块命名空间)"""
    class _QA:
        @staticmethod
        def screens():
            return [FakeScreen(r) for r in rects]
    class _Shim:
        QApplication = _QA
        QWidget = QtWidgets.QWidget
    yiv.QtWidgets = _Shim


class Stub:
    """只提供 clamp 需要的几何接口; 三个方法都是**磁盘上真实代码**"""
    _screens = yiv.YoloInputViewer._screens                       # 普通方法(要 self)
    _visible_ratio = staticmethod(yiv.YoloInputViewer._visible_ratio)   # ⚠️ 必须包 staticmethod:
    _clamp_to_screen = yiv.YoloInputViewer._clamp_to_screen            #   直接赋值会被当实例方法绑定 self

    def __init__(self, x, y, w, h):
        self._g = [x, y, w, h]
        self.moves, self.logs = [], []

    def width(self):
        return self._g[2]

    def height(self):
        return self._g[3]

    def x(self):
        return self._g[0]

    def y(self):
        return self._g[1]

    def setGeometry(self, x, y, w, h):
        self.moves.append((x, y, w, h))
        self._g = [x, y, w, h]

    def _log_line(self, s):
        self.logs.append(s)


LAPTOP = QRect(0, 0, 1920, 1200)            # eDP-1 笔记本屏 (primary)
HDMI = QRect(1920, 0, 1920, 1080)           # HDMI-1-0 扩展屏

CASES = [
    ("A 拖到扩展屏 (x=2000) → 不许动",        [LAPTOP, HDMI], (2000, 60, 1348, 945), "keep"),
    ("B 拖到扩展屏右缘 (x=2400) → 不许动",    [LAPTOP, HDMI], (2400, 0, 1348, 945), "keep"),
    ("C 骑在两屏之间 (x=1850) → 不许动",      [LAPTOP, HDMI], (1850, 100, 1348, 945), "keep"),
    ("D 扩展屏上最大化 (0,0,1920,1080) → 不许动", [LAPTOP, HDMI], (1920, 0, 1920, 1080), "keep"),
    ("E 拔掉 HDMI 后 x=2332 → 必须拉回笔记本屏", [LAPTOP], (2332, 60, 1348, 945), "pull"),
    ("F 窗口飞到屏外 (x=-5000) → 必须拉回",   [LAPTOP, HDMI], (-5000, 60, 1348, 945), "pull"),
    ("G 拔屏 + 窗口比屏大 (3000宽) → 拉回并收窄", [LAPTOP], (2400, 60, 3000, 1400), "pull"),
]

ok = True
for name, rects, geo, expect in CASES:
    install_screens(rects)
    s = Stub(*geo)
    moved = s._clamp_to_screen(silent=False)
    if expect == "keep":
        good = (not moved) and s.moves == []
    else:
        # 拉回后必须真的落在某块屏可见区内
        g = s._g
        good = moved and s.moves and any(
            QRect(g[0], g[1], g[2], g[3]).intersected(r).width() > 0
            and QRect(g[0], g[1], g[2], g[3]).intersected(r).height() > 0
            and QRect(g[0], g[1], g[2], g[3]).width() <= r.width()
            for r in rects)
    ok &= bool(good)
    print(f"[{'PASS' if good else 'FAIL'}] {name}")
    print(f"        {geo} → {tuple(s._g)}  moved={moved}  屏={[ (r.x(),r.y(),r.width(),r.height()) for r in rects ]}")
    if s.logs:
        print("        log:", s.logs[-1])

print("\n总判定:", "全绿 ✅" if ok else "有失败 ❌")
sys.exit(0 if ok else 1)
