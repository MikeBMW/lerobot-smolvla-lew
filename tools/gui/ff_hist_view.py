#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ff_hist_view.py — 🧠 前馈加速器隐层激活直方图 (2026-09-04 老倪, v3 重设计)

消费 ⚡前馈加速器探针 (parallel.py probe.act_raw: 每层 512 全量 ReLU 激活)
→ 三层激活分布直方图 + 实时数值面板。

怎么读 (窗口内也有图例文字):
  - 直方图横轴 = 神经元输出值; 0 处竖虚线 = ReLU 截断 — 落在 0 的 = 休眠单元
  - 白色柱 = 近 150 帧累积分布 (哪些单元经常工作); 朱红线 = 最近一帧 (此刻谁在响应)
  - 右侧长尾 = "正在工作"的特征单元; 层活跃数随任务阶段变化

用法 (由 node_logic.py 🧠前馈激活 节点实例化, 主线程):
  win = FFHistView(); win.push(probe); win.show()
"""
import numpy as np
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPainter, QColor, QPen, QFont
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel

# 🎨 深色面板 (数据视图风格, 单色系克制)
_BG_TOP = QColor("#0d1117")
_GRID = QColor("#1e2740")
_CURVE = QColor("#e6edf3")       # 直方图 (白灰)
_CURVE_LIVE = QColor("#ff5555")  # 最近一帧叠加 (朱红)
_TEXT = QColor("#e6edf3")
_TEXT2 = QColor("#9da7b3")
_ZERO = QColor("#7d8590")        # ReLU 0 截断虚线

LAYER_NAMES = [
    "第 1 层 · 输入编码",
    "第 2 层 · 特征组合",
    "第 3 层 · 决策输出",
]
LAYER_DESC = [
    "W0: 39D 观测 → 512 特征 (读出手/目标/速度关系)",
    "W1: 512 → 512 特征交互 (非线性组合)",
    "W2: 512 → 512 决策特征 (解码成动作前最后一跳)",
]
N_FRAMES = 150     # FIFO 累积帧数 (直方图统计窗口)
N_BINS = 60


class FFHistView(QDialog):
    """三层激活直方图窗口。push(probe) 每帧喂入, 内部 FIFO + 节流重绘。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🧠 前馈加速器 · 隐层激活直方图 — 它在想什么")
        self.resize(1200, 840)
        self.setMinimumSize(960, 680)
        # 🔧 2026-09-05 老倪: 最小化/最大化按钮无效 — 显式顶级窗口类型 + 按钮
        self.setWindowFlags(Qt.Window | Qt.WindowTitleHint | Qt.WindowSystemMenuHint
                            | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        self.buf = [[] for _ in range(3)]   # 每层 FIFO: 帧列表 (各 512 float32)
        self.cur = [None, None, None]       # 最近一帧 (叠加朱红)
        self.info = {}                      # 当前帧语义 (obs/u_ff)
        self._dirty = True
        self._cap_text = "🧠 等待激活数据 — 点「⚡引擎快演 ▶运行」或「⏭单步」后自动累积 (白柱=近150帧分布 · 朱红线=最近一帧)"
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
        # 状态行随帧更新 (自解释)
        try:
            n = len(self.buf[0])
            ob = self.info.get("obs", {})
            u = self.info.get("u_ff", [])
            u_txt = (f"输出 u_ff=[{u[0]:+.2f} {u[1]:+.2f} {u[2]:+.2f} m/s · 夹爪{'闭合' if u[3] else '张开'}]"
                     if u else "输出 u_ff=—")
            d_txt = f"手到目标 d={ob.get('d_h', 0):.2f}m" if ob and ob.get("d_h") is not None else ""
            self._cap_text = (
                f"🧠 累积 {n}/150 帧 · {u_txt} · {d_txt}\n"
                f"白柱=近150帧激活分布 · 朱红=最近一帧 · 0处高峰=休眠单元 · 右尾=正在工作的特征")
        except Exception:
            pass
        self._dirty = True

    def _throttled(self):
        if self._dirty and self.isVisible():
            self._dirty = False
            self.update()

    # ── 绘制 ──
    def paintEvent(self, ev):
        try:
            p = QPainter(self)
            r = self.rect()
            p.fillRect(r, _BG_TOP)
            # 顶部状态条 (QPainter 自绘, 无布局依赖)
            p.fillRect(0, 0, r.width(), 60, QColor("#161b22"))
            lines = str(self._cap_text).split("\n")
            p.setPen(_TEXT)
            p.setFont(QFont("Sans", 13, QFont.Bold))
            p.drawText(16, 22, lines[0])
            if len(lines) > 1:
                p.setPen(_TEXT2)
                p.setFont(QFont("Sans", 10))
                p.drawText(16, 44, lines[1])
            top = 68
            if not any(self.buf):
                p.setPen(_TEXT2)
                p.setFont(QFont("Sans", 13))
                p.drawText(r.adjusted(20, top, -20, -20), Qt.AlignCenter,
                           "等待激活数据…\n\n先点「⚡引擎快演 ▶运行」或「⏭单步」, 每帧的 512 个神经元激活会自动进来")
                p.end()
                return
            W, H = r.width(), r.height()
            row_h = (H - top - 14) / 3.0
            for i in range(3):
                y0 = top + i * row_h
                self._draw_row(p, i, W, y0, row_h)
            p.end()
        except Exception:
            try:
                p = QPainter(self)
                p.fillRect(self.rect(), _BG_TOP)
                p.setPen(_TEXT2)
                p.drawText(self.rect(), Qt.AlignCenter, "绘图异常")
                p.end()
            except Exception:
                pass

    def _draw_row(self, p, li, W, y0, row_h):
        """一行 = 左侧语义面板 + 右侧大直方图"""
        # ── 左侧: 层信息 (固定宽 300) ──
        lx = 24
        info_w = 300
        p.setPen(_TEXT)
        p.setFont(QFont("Sans", 13, QFont.Bold))
        p.drawText(lx, int(y0 + 26), LAYER_NAMES[li])
        p.setPen(_TEXT2)
        p.setFont(QFont("Sans", 10))
        p.drawText(lx, int(y0 + 46), LAYER_DESC[li])
        # 活跃度条 + 数字 (大字)
        ls = (self.info.get("layers") or [{}] * 3)[li]
        act = ls.get("active", 0)
        e = ls.get("act_l2", 0.0)
        bar_y = int(y0 + 58)
        p.setPen(QPen(_ZERO, 1))
        p.drawRect(lx, bar_y, 200, 14)
        if act:
            p.fillRect(lx + 1, bar_y + 1, int(198 * act / 512), 12, _CURVE)
        p.setPen(_TEXT)
        p.setFont(QFont("Sans", 12, QFont.Bold))
        p.drawText(lx, int(y0 + 94), f"活跃 {act}/512 神经元")
        p.setPen(_TEXT2)
        p.setFont(QFont("Sans", 10))
        p.drawText(lx, int(y0 + 112), f"能量(Σ激活²) E={e:.1f}")
        p.drawText(lx, int(y0 + 130), f"休眠率 {(512-act)/512*100:.0f}% (0=截断)")
        # 分隔线
        p.setPen(QPen(_GRID, 1))
        p.drawLine(int(info_w + 12), int(y0 + 4), int(info_w + 12), int(y0 + row_h - 12))

        # ── 右侧: 直方图 (大字轴标) ──
        hx0 = info_w + 34
        hx1 = W - 24
        y_top = int(y0 + 24)
        y_bot = int(y0 + row_h - 26)
        buf = np.concatenate(self.buf[li]) if self.buf[li] else np.zeros(1)
        if buf.size < 8:
            return
        vmax = float(np.percentile(buf, 99.5))
        vmax = max(vmax, 0.05)
        hist, _ = np.histogram(buf, bins=N_BINS, range=(0.0, vmax))
        hmax = max(float(hist.max()), 1.0)
        bw = (hx1 - hx0) / N_BINS
        # 网格 (横向 4 条)
        p.setPen(QPen(_GRID, 1))
        for gy in range(5):
            yy = y_top + (y_bot - y_top) * gy / 4
            p.drawLine(hx0, int(yy), hx1, int(yy))
        # 直方图主体 (白柱)
        p.setPen(Qt.NoPen)
        p.setBrush(_CURVE)
        for bi in range(N_BINS):
            hh = (y_bot - y_top) * hist[bi] / hmax
            if hh > 0.5:
                p.drawRect(int(hx0 + bw * bi) + 1, int(y_bot - hh), max(int(bw) - 2, 1), int(hh))
        # x=0 ReLU 截断线 (虚线 + 标注)
        zx = hx0
        p.setPen(QPen(_ZERO, 1, Qt.DashLine))
        p.drawLine(int(zx), y_top, int(zx), y_bot)
        p.setPen(_TEXT2)
        p.setFont(QFont("Sans", 9))
        p.drawText(int(zx) + 6, int(y_bot - 10), "x=0 (ReLU 截断: 此处高峰=休眠)")
        # 最近一帧叠加 (朱红, 只看分布走向: 用细线勾出单帧直方图)
        if self.cur[li] is not None:
            c = self.cur[li]
            ch, _ = np.histogram(c, bins=N_BINS, range=(0.0, vmax))
            pen = QPen(_CURVE_LIVE, 2.5)
            p.setPen(pen)
            prev = None
            for bi in range(N_BINS):
                hh = (y_bot - y_top) * ch[bi] / max(float(ch.max()), 1e-6)
                xx = int(hx0 + bw * bi + bw / 2)
                yy = int(y_bot - hh)
                if prev is not None:
                    p.drawLine(prev[0], prev[1], xx, yy)
                prev = (xx, yy)
        # 轴说明 (横轴)
        p.setPen(_TEXT2)
        p.setFont(QFont("Sans", 10))
        p.drawText(hx0, int(y_bot + 18), "0")
        p.drawText(int(hx1 - 90), int(y_bot + 18), f"激活值 → (峰值 {vmax:.2f})")
        p.setPen(_TEXT)
        p.setFont(QFont("Sans", 10, QFont.Bold))
        p.drawText(hx0, int(y_top - 8), f"512 个神经元输出分布 ({N_FRAMES} 帧累积)")

        # ── 右侧数值: 该层近期 u_ff 参考 ──
        u = self.info.get("u_ff") or []
        if u and li == 2:
            p.setPen(_CURVE_LIVE)
            p.setFont(QFont("Sans", 12, QFont.Bold))
            p.drawText(W - 300, int(y0 + 40), f"当前输出 u_ff=[{u[0]:+.2f}, {u[1]:+.2f}, {u[2]:+.2f}]")
            p.setPen(_TEXT2)
            p.setFont(QFont("Sans", 10))
            p.drawText(W - 300, int(y0 + 60),
                       f"夹爪指令 {'1 闭合 (近距)' if u[3] else '0 张开 (远距)'} · 单位 m/s")
