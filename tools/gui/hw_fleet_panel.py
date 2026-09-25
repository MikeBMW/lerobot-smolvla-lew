#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hw_fleet_panel.py — APP 多机硬件集群面板 (数据经 DDS 传送)
================================================================
订阅 DDS 话题 zmax/hw/metrics, 把各机器 (mac / 4060 / orin / ecs)
的 负载·存储·算力 同时显示。每台一张卡片, 掉线自动置灰。

前置: 各机器跑 `python3 tools/gui/hw_dds.py publish --role <role>`
集成: from hw_fleet_panel import HwFleetPanel
      layout.addWidget(HwFleetPanel(parent=self))
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (QFrame, QGridLayout, QGroupBox, QHBoxLayout,
                             QLabel, QProgressBar, QVBoxLayout, QWidget)

# 角色显示配置: role -> (中文名, 图标, 主题色)
ROLE_STYLE = {
    "mac":  ("Mac (小芳)", "🍎", "#58a6ff"),
    "4060": ("4060 (静静)", "🎮", "#3fb950"),
    "orin": ("Orin (端侧)", "🤖", "#e0a030"),
    "ecs":  ("ECS (云)", "☁️", "#a371f7"),
}
_UNKNOWN_STYLE = ("未知节点", "❓", "#8b949e")

_REFRESH_MS = 2000
_STALE_S = 15.0


def _paint(bar, v):
    v = float(v or 0)
    bar.setValue(int(max(0, min(100, v))))
    c = "#e05252" if v > 85 else ("#e0a030" if v > 65 else "#3fb950")
    bar.setStyleSheet(
        "QProgressBar{border:1px solid #3a3f46;border-radius:3px;background:#1b1f24;"
        "text-align:center;color:#e6edf3;font-size:10px;}"
        f"QProgressBar::chunk{{background:{c};border-radius:2px;}}")


def _bar():
    b = QProgressBar()
    b.setRange(0, 100)
    b.setTextVisible(True)
    b.setFormat("%p%")
    b.setFixedHeight(15)
    _paint(b, 0)
    return b


class NodeCard(QFrame):
    """单台机器的硬件卡片"""

    def __init__(self, role: str, parent=None):
        super().__init__(parent)
        name, icon, color = ROLE_STYLE.get(role, _UNKNOWN_STYLE)
        self.role = role
        self._accent = color
        # ⚠️ 不用 "NodeCard{...}" 选择器 — Qt QSS 无法解析自定义 Python 类名 (会报
        #    "Could not parse stylesheet"), 直接写属性即可作用于本控件
        self.setStyleSheet(
            f"background:#11161d;border:1px solid #30363d;border-left:3px solid {color};"
            "border-radius:5px;")
        g = QGridLayout(self)
        g.setContentsMargins(8, 6, 8, 6)
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(3)

        self.lbl_title = QLabel(f"{icon} {name}")
        self.lbl_title.setStyleSheet(f"color:{color};font-weight:bold;font-size:11px;")
        g.addWidget(self.lbl_title, 0, 0, 1, 3)

        self.lbl_host = QLabel("—")
        self.lbl_host.setStyleSheet("color:#8b949e;font-size:9px;")
        g.addWidget(self.lbl_host, 0, 3)

        self.bars = {}
        for r, key in enumerate(("CPU", "内存", "GPU", "磁盘"), start=1):
            k = QLabel(key)
            k.setFixedWidth(30)
            k.setStyleSheet("color:#c9d1d9;font-size:10px;")
            g.addWidget(k, r, 0)
            b = _bar()
            self.bars[key] = b
            g.addWidget(b, r, 1)
            d = QLabel("—")
            d.setStyleSheet("color:#8b949e;font-size:9px;")
            g.addWidget(d, r, 2, 1, 2)
            setattr(self, f"det_{key}", d)

        self.lbl_compute = QLabel("算力 —")
        self.lbl_compute.setStyleSheet("color:#e6edf3;font-size:10px;")
        g.addWidget(self.lbl_compute, 5, 0, 1, 4)

        self.lbl_train = QLabel("⏹ 空闲")
        self.lbl_train.setStyleSheet("color:#8b949e;font-size:9px;")
        g.addWidget(self.lbl_train, 6, 0, 1, 4)

    def update_from(self, m: dict | None):
        if not m:
            self.lbl_host.setText("⚠️ 离线 (无 DDS 数据)")
            for k in self.bars:
                _paint(self.bars[k], 0)
                getattr(self, f"det_{k}").setText("—")
            self.lbl_compute.setText("算力 —")
            self.lbl_train.setText("⏹ 离线")
            self.setStyleSheet(
                "background:#0d1117;border:1px solid #21262d;border-left:3px solid #30363d;"
                "border-radius:5px;")
            return
        # 恢复在线样式 (带主题色边条)
        self.setStyleSheet(
            f"background:#11161d;border:1px solid #30363d;border-left:3px solid {self._accent};"
            "border-radius:5px;")
        c, mm, k, g, cp = m["cpu"], m["mem"], m["disk"], m["gpu"], m["compute"]
        age = m.get("age_s", 0)
        self.lbl_host.setText(f"{m.get('host','')[:34]} · {age}s前")

        _paint(self.bars["CPU"], c.get("percent"))
        self.det_CPU.setText(f"{c.get('cores')}核 · 负载{c.get('load1')}")

        _paint(self.bars["内存"], mm.get("percent"))
        self.det_内存.setText(f"{mm.get('used_gb')}/{mm.get('total_gb')}GB")

        _paint(self.bars["GPU"], g.get("util_pct"))
        self.det_GPU.setText(f"{str(g.get('backend','')).upper()} · 显存{g.get('mem_used_gb')}GB")

        _paint(self.bars["磁盘"], k.get("percent"))
        self.det_磁盘.setText(f"可用{k.get('free_gb')}GB / {k.get('total_gb')}GB")

        tm, tn = cp.get("tflops_measured"), cp.get("tflops_nominal")
        txt = f"算力 实测 {tm} TFLOPS" if tm else f"算力 标称 {tn} TFLOPS [未实测]"
        self.lbl_compute.setText(txt + f"  ·  GPU {g.get('name','')[:24]}")

        if m["training"]["active"]:
            self.lbl_train.setText(f"🏋️ 训练进行中 × {m['training']['count']}")
            self.lbl_train.setStyleSheet("color:#3fb950;font-size:9px;font-weight:bold;")
        else:
            self.lbl_train.setText("⏹ 空闲")
            self.lbl_train.setStyleSheet("color:#8b949e;font-size:9px;")


class HwFleetPanel(QWidget):
    """多机硬件集群面板 — DDS 订阅 zmax/hw/metrics"""

    def __init__(self, parent=None, roles=("mac", "4060", "orin"), refresh_ms=_REFRESH_MS):
        super().__init__(parent)
        self._sub = None
        self._sub_err = ""
        self._cards: dict = {}
        self._roles = list(roles)
        self._build()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(refresh_ms)
        self.refresh()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        box = QGroupBox("🏋️ 训练硬件集群 (DDS 实时)")
        box.setStyleSheet("QGroupBox{color:#e6edf3;font-weight:bold;border:1px solid #30363d;"
                          "border-radius:5px;margin-top:7px;padding-top:6px;}"
                          "QGroupBox::title{subcontrol-origin:margin;left:9px;padding:0 4px;}")
        v = QVBoxLayout(box)
        v.setSpacing(5)
        for r in self._roles:
            c = NodeCard(r)
            self._cards[r] = c
            v.addWidget(c)
        self.lbl_status = QLabel("DDS: 初始化…")
        self.lbl_status.setStyleSheet("color:#8b949e;font-size:9px;")
        v.addWidget(self.lbl_status)
        root.addWidget(box)

    def _ensure_sub(self):
        if self._sub is not None:
            return True
        try:
            from hw_dds import HwSubscriber  # noqa: PLC0415
            self._sub = HwSubscriber(stale_s=_STALE_S)
            return True
        except Exception as e:
            self._sub_err = f"{type(e).__name__}: {str(e)[:70]}"
            return False

    def refresh(self):
        if not self._ensure_sub():
            self.lbl_status.setText(f"DDS 不可用: {self._sub_err} (需 pip install cyclonedds)")
            for c in self._cards.values():
                c.update_from(None)
            return
        try:
            self._sub.poll()
            on = self._sub.online()
        except Exception as e:
            self.lbl_status.setText(f"DDS 订阅异常: {type(e).__name__}: {str(e)[:60]}")
            return
        # 已知机器
        for r, card in self._cards.items():
            card.update_from(on.get(r))
        # 发现的新机器 (动态加卡)
        for r, m in on.items():
            if r not in self._cards:
                card = NodeCard(r)
                self._cards[r] = card
                self.layout().itemAt(0).widget().layout().insertWidget(
                    self.layout().itemAt(0).widget().layout().count() - 1, card)
                card.update_from(m)
        n_on = len(on)
        roles_on = ", ".join(sorted(on.keys())) or "无"
        self.lbl_status.setText(f"DDS ✅ 在线 {n_on} 台 [{roles_on}] · 超时判据 {_STALE_S}s")

    def snapshot(self) -> dict:
        """给外部取全部机器数据"""
        return dict(self._sub.latest) if self._sub else {}


if __name__ == "__main__":  # 独立预览
    from PyQt5.QtWidgets import QApplication
    app = QApplication(sys.argv)
    app.setStyleSheet("QWidget{background:#0d1117;}")
    w = HwFleetPanel()
    w.resize(620, 460)
    w.show()
    sys.exit(app.exec_())
