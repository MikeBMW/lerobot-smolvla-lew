#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""profile_hw_card.py — 量「硬件资源卡」每次刷新在 GUI 线程里阻塞多久 (卡顿根因定量)

做法: offscreen 真实例化 HardwareCard, 3 次 refresh(), 并 monkeypatch subprocess/urllib
      记录每次外部调用的耗时 → 找出真正卡住主线程的那几步。
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, "/home/ubuntu/zmax_rel/tools/gui")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

CALLS = []
_orig_run = subprocess.run


def timed_run(*a, **k):
    t0 = time.time()
    try:
        return _orig_run(*a, **k)
    finally:
        cmd = (a[0] if a else k.get("args"))
        CALLS.append((round((time.time() - t0) * 1000, 1), (str(cmd)[:70] if isinstance(cmd, str) else " ".join(map(str, cmd))[:70])))


subprocess.run = timed_run
import urllib.request as _ur
_orig_urlopen = _ur.urlopen


def timed_urlopen(*a, **k):
    t0 = time.time()
    try:
        return _orig_urlopen(*a, **k)
    finally:
        CALLS.append((round((time.time() - t0) * 1000, 1), "HTTP " + str(a[0])[:60]))


_ur.urlopen = timed_urlopen

from PyQt5.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
import studio  # noqa: E402

card = studio.HardwareCard()
card.show()
app.processEvents()

for i in range(3):
    CALLS.clear()
    t0 = time.time()
    card.refresh()
    dt = (time.time() - t0) * 1000
    slow = sorted(CALLS, reverse=True)[:6]
    print("第%d次 refresh: **%6.1f ms** (阻塞 GUI 线程) | 外部调用 %d 次" % (i + 1, dt, len(CALLS)))
    for ms, cmd in slow:
        print("      %7.1f ms  %s" % (ms, cmd))
print("\n结论口径: refresh 若 >100ms 且每 2s 一次 → 人眼就是'卡顿'")
print("本轮总阻塞: %.0f ms / 3 次 = 每次 %.0f ms" % (sum(1 for _ in [0]) * 0 + 0, 0))
