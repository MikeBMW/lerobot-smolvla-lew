#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ff_hist_view.py — 🧠 前馈加速器隐层激活直方图 (2026-09-04 老倪)

消费 ⚡前馈加速器探针 (parallel.py probe.act_raw: 每层 512 全量 ReLU 激活)
→ 三层激活分布直方图 + 实时数值面板。看到的东西:
  - x=0 处高峰 = ReLU 截断 (休眠神经元, 稀疏激活)
  - 右侧长尾 = 当前状态"正在工作"的特征单元
  - 层活跃数/能量随任务阶段变化 (远段粗动作 vs 近段精调)

用法 (由 node_logic.py 🧠前馈激活 节点实例化, 主线程):
  win = FFHistView(); win.push(probe); win.show()
"""
import numpy as np
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPainter, QColor, QPen, QFont, QLinearGradient
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel

# 🎨 深色面板 (数据视图风格, 单色系克制)
_BG_TOP = QColor("#0d1117")
_BG_BOT = QColor("#161b22")
_GRID = QColor("#1e2740")
_GRID_MAJOR = QColor("#30363d")
_CURVE = QColor("#e6edf3")       # 直方图 (白灰)
_CURVE_LIVE = QColor("#b70032")  # 最近一帧叠加 (朱红, 单点强调)
_TEXT = QColor("#c9d1d9")
_TEXT2 = QColor("#8b949e")
_ZERO = QColor("#57606a")        # ReLU 0 截断虚线

LAYER_NAMES = ["层1 · 编码 (39D→512)", "层2 · 特征组合 (512→512)", "层3 · 决策 (512→512)"]
N_FRAMES = 150     # FIFO 累积帧数 (直方图统计窗口)
N_BINS = 64


class FFHistView(QDialog):
    """三层激活直方图窗口。push(probe) 每帧喂入, 内部 FIFO + 节流重绘。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🧠 前馈加速器 · 隐层激活直方图 (512×3)")
        self.resize(880, 620)
        self.setMinimumSize(640, 480)
        self.buf = [[] for _ in range(3)]   # 每层 FIFO: 帧列表 (各 512 float32)
        self.cur = [None, None, None]       # 最近一帧 (叠加朱红)
        self.info = {}                      # 当前帧语义 (obs/u_ff)
        self._last_paint = 0.0
        self._dirty = True
        # 标题栏
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._cap = QLabel("🧠 前馈加速器隐层激活 — 等待数据 (先运行 ⚡前馈加速器, 再运行本节点)")
        self._cap.setStyleSheet("color:#8b949e; padding:6px 10px; font-size:13px;")
        lay.addWidget(self._cap)
        # 节流重绘 (≤10Hz, 避免每 tick 全量重绘卡 GUI)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._throttled)
        self._timer.start(100)

    # ── 数据入口 ──
    def push(self, probe):
        """喂一帧探针: act_raw=[x1,x2,x3] 每层 512"""
        raw = probe.get("act_raw")
        if not raw:
            return
        import time
        for i in range(3):
            a = np.asarray(raw[i], dtype=np.float32).ravel()
            if a.shape[0] != 512:
                continue
            self.buf[i].append(a)
            if len(self.buf[i]) > N_FRAMES:
                self.buf[i].pop(0)
            self.cur[i] = a
        self.info = {"obs": probe.get("obs", {}), "u_ff": probe.get("u_ff", []),
                     "layers": probe.get("layers", [])}
        self._dirty = True

    def _throttled(self):
        if self._dirty and self.isVisible():
            self._dirty = False
            self.update()

    # ── 绘制 ──
    def paintEvent(self, ev):
        p = QPainter(self)
        r = self.rect()
        g = QLinearGradient(r.topLeft(), r.bottomLeft())
        g.setColorAt(0, _BG_TOP)
        g.setColorAt(1, _BG_BOT)
        p.fillRect(r, g)

        if not any(self.buf):
            p.setPen(_TEXT2)
            p.setFont(QFont("Sans", 12))
            p.drawText(r, Qt.AlignCenter, "⚡ 前馈加速器运行后, 本节点自动累积激活分布…")
            p.end()
            return

        W, H = r.width(), r.height()
        top = 34
        row_h = (H - top - 26) / 3.0
        # 统计窗口: 累积激活值 + 单帧
        for i in range(3):
            y0 = top + i * row_h
            self._draw_row(p, i, W, y0, row_h)
        p.end()

    def _draw_row(self, p, li, W, y0, row_h):
        hist_h = row_h - 34
        x0, x1 = 96, W - 16
        yb = int(y0 + 18 + hist_h)          # 直方图底
        # 标题
        p.setPen(_TEXT)
        p.setFont(QFont("Sans", 10, QFont.Bold))
        p.drawText(14, int(y0 + 16), LAYER_NAMES[li])
        ls = (self.info.get("layers") or [{}] * 3)[li]
        if ls:
            p.setPen(_TEXT2)
            p.setFont(QFont("Sans", 9))
            p.drawText(14, int(y0 + 32),
                       f"活跃 {ls.get('active', 0)}/512 · 能量 E={ls.get('act_l2', 0):.1f}")
        # 数据
        buf = np.concatenate(self.buf[li]) if self.buf[li] else np.zeros(1)
        if buf.size < 8:
            return
        vmax = float(np.percentile(buf, 99.5))
        vmax = max(vmax, 0.05)
        hist, edges = np.histogram(buf, bins=N_BINS, range=(0.0, vmax))
        hmax = max(float(hist.max()), 1.0)
        # 网格 + 直方图
        bw = (x1 - x0) / N_BINS
        p.setPen(QPen(_GRID, 1))
        for gx in range(5):
            xx = x0 + (x1 - x0) * gx / 4
            p.drawLine(int(xx), int(y0 + 18), int(xx), yb)
        # 直方图主体
        p.setPen(Qt.NoPen)
        p.setBrush(_CURVE)
        for bi in range(N_BINS):
            hh = hist_h * hist[bi] / hmax
            p.drawRect(int(x0 + bw * bi) + 1, int(yb - hh), max(int(bw) - 2, 1), int(hh))
        # x=0 ReLU 截断线 (分布左边界)
        zx = x0 + (0.0 / vmax) * (x1 - x0)
        p.setPen(QPen(_ZERO, 1, Qt.DashLine))
        p.drawLine(int(zx), int(y0 + 18), int(zx), yb)
        # 轴刻度
        p.setPen(_TEXT2)
        p.setFont(QFont("Sans", 8))
        p.drawText(int(x0), yb + 14, "0")
        p.drawText(int(x1 - 30), yb + 14, f"{vmax:.1f}")
        # 最近一帧叠加 (朱红细线, 即时响应)
        if self.cur[li] is not None:
            c = self.cur[li]
            p.setPen(QPen(_CURVE_LIVE, 1))
            prev = None
            for j in range(c.shape[0]):
                v = float(c[j])
                if v <= 0:
                    continue
                xx = x0 + (min(v, vmax) / vmax) * (x1 - x0)
                yy = y0 + 18 + hist_h
                if prev is not None:
                    p.drawLine(int(prev[0]), int(prev[1] - 1), int(xx), int(yy - 1))
                prev = (xx, yy)
        # 右侧数值: u_ff
        u = self.info.get("u_ff") or []
        if u:
            p.setPen(_CURVE_LIVE)
            p.setFont(QFont("Sans", 9, QFont.Bold))
            p.drawText(W - 200, int(y0 + 16), f"u_ff=[{u[0]:+.3f} {u[1]:+.3f} {u[2]:+.3f} g{u[3]:.0f}]")
        # obs 摘要 (当前帧)
        ob = self.info.get("obs") or {}
        if ob and li == 0:
            p.setPen(_TEXT2)
            p.setFont(QFont("Sans", 9))
            p.drawText(int(x0), int(y0 + 16),
                       f"手{ob.get('hand', [])} → 目标{ob.get('target', [])} · "
                       f"d={ob.get('d_h', 0):.3f} 夹爪={ob.get('gripper', 0):.2f}")
