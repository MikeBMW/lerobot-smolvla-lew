#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""measure_ui_jitter.py — 控制台卡顿的客观度量 (主线程事件循环最大间隙)

口径: 主线程跑一个 10ms 心跳 QTimer, 记录两次心跳之间的**最大间隔** = 用户感知的"卡一下"。
  A) 旧行为: 每 2s 在主线程同步跑一次硬件采集 (阻塞 I/O)
  B) 新行为: 采集在工作线程 (_HwFetcher), 主线程只贴字符串
预期: A ≈ 1.3~1.5s 卡顿 / B ≈ 几十 ms (仅剩渲染)
"""
import os
import sys
import time

sys.path.insert(0, "/home/ubuntu/zmax_rel/tools/gui")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtCore import QTimer  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
import studio  # noqa: E402

card = studio.HardwareCard()
card.show()
app.processEvents()

gaps = []
last = [time.time()]


def beat():
    now = time.time()
    gaps.append((now - last[0]) * 1000.0)
    last[0] = now


hb = QTimer()
hb.timeout.connect(beat)
hb.start(10)


def run_phase(name, seconds, sync_collect_every=None):
    global last
    gaps.clear()
    last[0] = time.time()
    killer = None
    if sync_collect_every:
        killer = QTimer()
        killer.timeout.connect(lambda: card._collect())     # 模拟旧的"主线程里采集"
        killer.start(sync_collect_every)
    t0 = time.time()
    while time.time() - t0 < seconds:
        app.processEvents()
        time.sleep(0.002)
    if killer:
        killer.stop()
    app.processEvents()
    g = sorted(gaps)[1:] or [0]
    print("  %-26s 心跳 %3d 次 · 最大间隙 **%6.1f ms** · 中位 %5.1f ms · >100ms 的次数 %d"
          % (name, len(gaps), g[-1], g[len(g) // 2], sum(1 for x in g if x > 100)))


print("=== A) 旧行为 (主线程同步采集, 每 2s 一次) ===")
run_phase("旧: 主线程采集 2s 周期", 8, sync_collect_every=2000)

print("=== B) 新行为 (采集在 _HwFetcher 工作线程) ===")
card._worker.stop()
card._worker.wait(2000)
card._worker = studio._HwFetcher(card, interval=2.0)
card._worker.got.connect(card._on_fetched)
card._worker.start()
run_phase("新: 后台线程采集", 8)
card._worker.stop()

print("\n结论: 最大间隙 >1s 就是用户说的'打开很卡'; 修复后应只剩几十 ms 的渲染间隙")
# ⚠️ cyclonedds/子线程 在解释器退出时会 core dump → 度量完直接硬退出, 不让 Qt/DDS 走清理路径
try:
    card._worker.stop()
    card._worker.wait(1500)
except Exception:
    pass
sys.stdout.flush()
os._exit(0)
