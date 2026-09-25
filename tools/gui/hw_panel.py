#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hw_panel.py — APP 训练硬件面板 (负载 / 存储 / 算力)
========================================================
自包含 Qt 控件: 数据来自 hw_monitor.probe(), 定时刷新。
集成方式 (studio.py 一行即可):
    from hw_panel import HwMonitorPanel
    layout.addWidget(HwMonitorPanel(parent=self))
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from PyQt5.QtCore import Qt, QTimer
    from PyQt5.QtGui import QFont
    from PyQt5.QtWidgets import (QFrame, QGridLayout, QGroupBox, QHBoxLayout,
                                 QLabel, QProgressBar, QVBoxLayout, QWidget)
except Exception:  # pragma: no cover
    QWidget = object  # type: ignore

try:
    from hw_monitor import probe as _probe
except Exception:  # pragma: no cover
    from tools.gui.hw_monitor import probe as _probe  # type: ignore


_REFRESH_MS = 2000  # 2s 刷新


def _bar(v, color_hi="#e05252", color_mid="#e0a030", color_lo="#3fb950"):
    """按百分比给进度条配色 (>85 红 / >65 黄 / 其余绿)"""
    b = QProgressBar()
    b.setRange(0, 100)
    b.setTextVisible(True)
    b.setFormat("%p%")          # ← Qt 占位符: 随 value 自动更新 (写死 f"{v}%" 会永远显示初值)
    b.setFixedHeight(16)
    _paint(b, v, color_hi, color_mid, color_lo)
    return b


def _paint(bar, v, color_hi="#e05252", color_mid="#e0a030", color_lo="#3fb950"):
    """更新进度条 值 + 配色 (刷新时调用, 颜色随负载实时变)"""
    v = float(v or 0)
    bar.setValue(int(max(0, min(100, v))))
    c = color_hi if v > 85 else (color_mid if v > 65 else color_lo)
    bar.setStyleSheet(
        "QProgressBar{border:1px solid #3a3f46;border-radius:3px;background:#1b1f24;"
        "text-align:center;color:#e6edf3;font-size:10px;}"
        f"QProgressBar::chunk{{background:{c};border-radius:2px;}}"
    )


class HwMonitorPanel(QWidget):
    """训练硬件面板: 负载(CPU/内存/GPU) · 存储(磁盘) · 算力(TFLOPS)"""

    def __init__(self, parent=None, refresh_ms: int = _REFRESH_MS, title: str = "🖥 训练硬件"):
        super().__init__(parent)
        self._last = None
        self._build(title)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(refresh_ms)
        self.refresh()

    # ── UI ──
    def _build(self, title: str):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        box = QGroupBox(title)
        box.setStyleSheet("QGroupBox{color:#e6edf3;font-weight:bold;border:1px solid #30363d;"
                          "border-radius:5px;margin-top:7px;padding-top:6px;}"
                          "QGroupBox::title{subcontrol-origin:margin;left:9px;padding:0 4px;}")
        g = QGridLayout(box)
        g.setHorizontalSpacing(9)
        g.setVerticalSpacing(4)

        self.lbl_sys = QLabel("—")
        self.lbl_sys.setStyleSheet("color:#8b949e;font-size:10px;")
        g.addWidget(self.lbl_sys, 0, 0, 1, 4)

        # 负载
        g.addWidget(self._k("CPU"), 1, 0)
        self.bar_cpu = _bar(0)
        g.addWidget(self.bar_cpu, 1, 1)
        self.lbl_cpu = QLabel("—")
        self.lbl_cpu.setStyleSheet("color:#8b949e;font-size:10px;")
        g.addWidget(self.lbl_cpu, 1, 2, 1, 2)

        g.addWidget(self._k("内存"), 2, 0)
        self.bar_mem = _bar(0)
        g.addWidget(self.bar_mem, 2, 1)
        self.lbl_mem = QLabel("—")
        self.lbl_mem.setStyleSheet("color:#8b949e;font-size:10px;")
        g.addWidget(self.lbl_mem, 2, 2, 1, 2)

        g.addWidget(self._k("GPU"), 3, 0)
        self.bar_gpu = _bar(0)
        g.addWidget(self.bar_gpu, 3, 1)
        self.lbl_gpu = QLabel("—")
        self.lbl_gpu.setStyleSheet("color:#8b949e;font-size:10px;")
        g.addWidget(self.lbl_gpu, 3, 2, 1, 2)

        # 存储
        g.addWidget(self._k("存储"), 4, 0)
        self.bar_disk = _bar(0)
        g.addWidget(self.bar_disk, 4, 1)
        self.lbl_disk = QLabel("—")
        self.lbl_disk.setStyleSheet("color:#8b949e;font-size:10px;")
        g.addWidget(self.lbl_disk, 4, 2, 1, 2)

        # 算力
        g.addWidget(self._k("算力"), 5, 0)
        self.lbl_compute = QLabel("—")
        self.lbl_compute.setStyleSheet("color:#e6edf3;font-size:11px;")
        g.addWidget(self.lbl_compute, 5, 1, 1, 3)

        # 训练状态
        self.lbl_train = QLabel("⏹ 无训练进程")
        self.lbl_train.setStyleSheet("color:#8b949e;font-size:10px;")
        g.addWidget(self.lbl_train, 6, 0, 1, 4)

        # 告警
        self.lbl_warn = QLabel("")
        self.lbl_warn.setWordWrap(True)
        self.lbl_warn.setStyleSheet("color:#e0a030;font-size:10px;")
        g.addWidget(self.lbl_warn, 7, 0, 1, 4)

        root.addWidget(box)

    @staticmethod
    def _k(t: str) -> QLabel:
        l = QLabel(t)
        l.setFixedWidth(34)
        l.setStyleSheet("color:#c9d1d9;font-size:10px;")
        return l

    # ── 刷新 ──
    def refresh(self):
        try:
            d = _probe()
        except Exception as e:
            self.lbl_sys.setText(f"硬件探测失败: {type(e).__name__}: {str(e)[:50]}")
            return
        self._last = d
        c, m, k, gp, cp, tr = d["cpu"], d["mem"], d["disk"], d["gpu"], d["compute"], d["training"]

        self.lbl_sys.setText(f"{d['host']} · {self._last and ''}".rstrip(" ·"))

        _paint(self.bar_cpu, c.get("percent"))
        self.lbl_cpu.setText(f"{c['cores']}核 · 负载 {c.get('load1')}/{c.get('load5')}/{c.get('load15')}")

        _paint(self.bar_mem, m.get("percent"))
        sw = m.get("swap_percent")
        self.lbl_mem.setText(f"{m.get('used_gb')}/{m.get('total_gb')}GB · 可用{m.get('avail_gb')}GB"
                             + (f" · swap {sw}%" if sw is not None else ""))

        _paint(self.bar_gpu, gp.get("util_pct"))
        vram = gp.get("mem_used_gb")
        self.lbl_gpu.setText(f"{str(gp.get('backend','')).upper()} {gp.get('name','')}"
                             + (f" · 显存{vram}GB" if vram is not None else ""))

        _paint(self.bar_disk, k.get("percent"))
        self.lbl_disk.setText(f"{k.get('used_gb')}/{k.get('total_gb')}GB · 可用{k.get('free_gb')}GB")

        tf, eff, meas = cp.get("tflops_fp32"), cp.get("tflops_effective"), cp.get("tflops_measured")
        if meas is not None:
            txt = f"实测 {meas} TFLOPS FP32"
        else:
            txt = f"标称 {tf} TFLOPS FP32 [未实测]"
        if eff is not None:
            txt += f" · 当前有效 ≈ {eff} TFLOPS"
        if cp.get("note"):
            txt += f" ({cp['note']})"
        self.lbl_compute.setText(txt)

        if tr.get("active"):
            names = ", ".join(sorted({p["name"] for p in tr["procs"]})[:3])
            self.lbl_train.setText(f"🏋️ 训练进行中 · {tr['count']} 进程 ({names})")
            self.lbl_train.setStyleSheet("color:#3fb950;font-size:10px;font-weight:bold;")
        else:
            self.lbl_train.setText("⏹ 无训练进程")
            self.lbl_train.setStyleSheet("color:#8b949e;font-size:10px;")

        self.lbl_warn.setText("  ".join("⚠️ " + w for w in d.get("warn", [])))

    # ── 给外部取原始数据 (画曲线/上报) ──
    def snapshot(self) -> dict | None:
        return self._last


if __name__ == "__main__":  # 独立预览
    from PyQt5.QtWidgets import QApplication
    app = QApplication(sys.argv)
    w = HwMonitorPanel()
    w.resize(560, 230)
    w.show()
    sys.exit(app.exec_())
