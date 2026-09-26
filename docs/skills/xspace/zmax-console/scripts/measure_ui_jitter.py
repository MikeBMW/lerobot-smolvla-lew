#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""measure_ui_jitter.py — 客观度量 Qt 界面"卡不卡"(主线程事件循环最大间隙)

用途: 任何"界面卡顿/打开就卡/点一下卡住"的投诉, 先用它把"卡多久"量出来, 再改。
口径: 主线程跑 10ms 心跳 QTimer, 记录**两次心跳之间的最大间隔** = 用户感知的"卡一下"。
      最大间隙 >1000ms 就是"打开很卡"; >100ms 已可感知; 健康应 <30ms。

两阶段对照(把待测的阻塞调用放进来即可):
  A) 旧行为: 在 GUI 线程同步调用采集函数 (模拟"定时器回调里做 I/O")
  B) 新行为: 采集在 QThread, GUI 侧只贴字符串
实测样例(2026-09-26 工位机控制台): A 最大间隙 1415.2ms / 4 次卡顿 · B 15.8ms / 0 次

用法(按需改 PHASE_A/B 里的两个函数, 然后在项目 venv 里跑):
  QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python scripts/measure_ui_jitter.py
⚠️ cyclonedds / 第三方后台线程在解释器退出时会 core dump → 末尾用 os._exit 硬退出。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtCore import QTimer                                    # noqa: E402
from PyQt5.QtWidgets import QApplication                           # noqa: E402

app = QApplication(sys.argv)
gaps, last = [], [time.time()]


def beat():
    now = time.time()
    gaps.append((now - last[0]) * 1000.0)
    last[0] = now


QTimer(app, timeout=beat).start(10)                                # 10ms 心跳


def phase(name, seconds, sync_call=None, period_ms=2000):
    """sync_call: 放在 GUI 线程里同步执行的函数 (None = 只测当前状态)"""
    gaps.clear()
    last[0] = time.time()
    killer = None
    if sync_call is not None:
        killer = QTimer(app, timeout=sync_call)
        killer.start(period_ms)
    t0 = time.time()
    while time.time() - t0 < seconds:
        app.processEvents()
        time.sleep(0.002)
    if killer:
        killer.stop()
    app.processEvents()
    g = sorted(gaps)[1:] or [0]
    print("  %-28s 心跳 %3d 次 · 最大间隙 **%7.1f ms** · 中位 %5.1f ms · >100ms %d 次"
          % (name, len(gaps), g[-1], g[len(g) // 2], sum(1 for x in g if x > 100)))


if __name__ == "__main__":
    print("用法: 把待测函数接进来。示例(控制台硬件卡):")
    print("  import studio; card = studio.HardwareCard()")
    print("  phase('A 旧: 主线程采集 2s 周期', 8, sync_call=card._collect)")
    print("  card._worker.start(); phase('B 新: 后台线程采集', 8)")
    phase("基线(无阻塞调用)", 4)
    sys.stdout.flush()
    os._exit(0)      # 防第三方线程在退出时 core dump
