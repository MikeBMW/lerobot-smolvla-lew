#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ui_jitter_probe.py — 客观量「GUI 主线程卡顿」: 10ms 心跳的最大间隙 (人眼感知的"卡一下")

用途: 用户说"界面卡/打开就卡/一顿一顿"时, 先拿到数字, 再决定改哪里; 改完复量对比。

用法 (在目标 GUI 的仓库里, 用它的 venv):
    QT_QPA_PLATFORM=offscreen <venv>/bin/python ui_jitter_probe.py --dur 8
    带被测控件 (本项目硬件卡):
    QT_QPA_PLATFORM=offscreen <venv>/bin/python ui_jitter_probe.py \
        --gui-dir tools/gui --module studio --widget HardwareCard --dur 8 \
        --old-sync-slot _collect --old-period 2000

口径 (经验值):
    max gap < 50ms    → 人眼基本无感
    max gap 100~300ms → 明显顿挫
    max gap > 1s      → "打开就卡"级别 (主线程被阻塞 I/O 冻住)

设计注:
  · 只依赖 PyQt5, 不 import 被测模块以外的第三方
  · --old-sync-slot 会在主线程按 --old-period 周期调用该"阻塞槽"来复现旧行为做 A/B
  · 结束时 os._exit(0): cyclonedds/子线程在解释器退出时会 core dump (非被测代码问题)
"""
from __future__ import annotations

import argparse
import importlib
import os
import sys
import time

ap = argparse.ArgumentParser()
ap.add_argument("--gui-dir", default="", help="GUI 代码目录 (含 studio.py 等), 会被加进 sys.path")
ap.add_argument("--module", default="", help="被测模块名 (如 studio)")
ap.add_argument("--widget", default="", help="要实例化的控件类名 (如 HardwareCard); 空=不建控件")
ap.add_argument("--dur", type=float, default=8.0, help="每段测量秒数")
ap.add_argument("--old-sync-slot", default="", help="旧行为复现: 在主线程周期性调用的阻塞方法名")
ap.add_argument("--old-period", type=int, default=2000, help="旧行为周期 ms")
a = ap.parse_args()

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if a.gui_dir:
    sys.path.insert(0, os.path.abspath(a.gui_dir))

from PyQt5.QtCore import QTimer                     # noqa: E402
from PyQt5.QtWidgets import QApplication            # noqa: E402

app = QApplication(sys.argv)
widget = None
if a.module and a.widget:
    mod = importlib.import_module(a.module)
    widget = getattr(mod, a.widget)()
    widget.show()
    app.processEvents()

gaps: list[float] = []
last = [time.time()]


def beat() -> None:
    now = time.time()
    gaps.append((now - last[0]) * 1000.0)
    last[0] = now


hb = QTimer()
hb.timeout.connect(beat)
hb.start(10)


def phase(name: str, seconds: float, sync_every_ms: int | None = None) -> None:
    gaps.clear()
    last[0] = time.time()
    killer = None
    if sync_every_ms and widget is not None and a.old_sync_slot:
        slot = getattr(widget, a.old_sync_slot)
        killer = QTimer()
        killer.timeout.connect(slot)              # 旧行为: 主线程里跑阻塞函数
        killer.start(sync_every_ms)
    t0 = time.time()
    while time.time() - t0 < seconds:
        app.processEvents()
        time.sleep(0.002)
    if killer:
        killer.stop()
    app.processEvents()
    g = sorted(gaps)[1:] or [0.0]
    print("  %-34s 心跳 %3d 次 · 最大间隙 %7.1f ms · 中位 %5.1f ms · >100ms %d 次"
          % (name, len(gaps), g[-1], g[len(g) // 2], sum(1 for x in g if x > 100)))


if a.old_sync_slot and widget is not None:
    print("=== A) 旧行为: 主线程 %s 每 %dms ===" % (a.old_sync_slot, a.old_period))
    phase("旧: 主线程阻塞槽", a.dur, sync_every_ms=a.old_period)

print("=== B) 现状 (采集应在工作线程) ===")
phase("现状: 采集后台线程", a.dur)

print("\n判读: >1s = '打开就卡'(主线程被阻塞 I/O 冻住); 修后应只剩几十 ms 渲染间隙")
sys.stdout.flush()
os._exit(0)     # 避免 cyclonedds/子线程在退出路径 core dump (与代码质量无关)
