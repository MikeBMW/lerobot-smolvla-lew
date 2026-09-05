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
from PyQt5.QtCore import Qt, QTimer, QRect
from PyQt5.QtGui import QPainter, QColor, QPen, QFont
from PyQt5.QtWidgets import QDialog

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
        self._cap_text = "🧠 等待激活数据 — 点「⚡引擎快演 ▶运行」或「⏭单步」后逐帧累积 (直方图=本帧 512 神经元实际激活值)"
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
            u_txt = (f"输出 u_ff=[{u[0]:+.2f} {u[1]:+.2f} {u[2]:+.2f} · 夹爪{'闭合' if u[3] else '张开'}]"
                     if u else "输出 u_ff=—")
            d_txt = f"手到目标 d={ob.get('d_h', 0):.2f}m" if ob and ob.get("d_h") is not None else ""
            self._cap_text = (
                f"🧠 累积 {n}/150 帧用于定轴 · 本帧 {u_txt} · {d_txt}\n"
                f"直方图 = 本帧 512 个神经元的实际激活值 (真实计数, 不做平均) · 0值单列标注")
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
            # 顶部状态条: 画在矩形内自动换行 (任何 DPI/文字长度不重叠)
            sb = QRect(16, 10, r.width() - 32, 76)
            p.fillRect(0, 0, r.width(), 86, QColor("#161b22"))
            lines = str(self._cap_text).split("\n")
            p.setPen(_TEXT)
            p.setFont(QFont("Sans", 12, QFont.Bold))
            fm = p.fontMetrics()
            h1 = fm.boundingRect(QRect(0, 0, sb.width(), 2000),
                                 Qt.TextWordWrap, lines[0]).height() + 4
            p.drawText(QRect(sb.x(), sb.y(), sb.width(), h1),
                       Qt.TextWordWrap | Qt.AlignVCenter, lines[0])
            if len(lines) > 1:
                p.setPen(_TEXT2)
                p.setFont(QFont("Sans", 10))
                fm = p.fontMetrics()
                h2 = fm.boundingRect(QRect(0, 0, sb.width(), 2000),
                                     Qt.TextWordWrap, lines[1]).height()
                p.drawText(QRect(sb.x(), sb.y() + h1 + 4, sb.width(), h2),
                           Qt.TextWordWrap | Qt.AlignVCenter, lines[1])
            top = 92
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
        """一行 = 左侧语义面板 + 右侧大直方图.
        全部文字用矩形自动换行 (TextWordWrap), 行高=字体实际高度流式累加 — 任何 DPI/文字长度不重叠"""
        info_w = 330
        # ── 左侧列 (wrap 流式) ──
        lx = 20
        col_w = info_w - 36
        yy = int(y0) + 4
        p.setPen(_TEXT)
        p.setFont(QFont("Sans", 12, QFont.Bold))
        fm = p.fontMetrics()
        h = fm.boundingRect(QRect(0, 0, col_w, 2000), Qt.TextWordWrap,
                            LAYER_NAMES[li]).height()
        p.drawText(QRect(lx, yy, col_w, h), Qt.TextWordWrap, LAYER_NAMES[li])
        yy += h + 6
        p.setPen(_TEXT2)
        p.setFont(QFont("Sans", 10))
        fm = p.fontMetrics()
        h = fm.boundingRect(QRect(0, 0, col_w, 2000), Qt.TextWordWrap,
                            LAYER_DESC[li]).height()
        p.drawText(QRect(lx, yy, col_w, h), Qt.TextWordWrap, LAYER_DESC[li])
        yy += h + 8
        # 活跃度条
        ls = (self.info.get("layers") or [{}] * 3)[li]
        act = ls.get("active", 0)
        e = ls.get("act_l2", 0.0)
        p.setPen(QPen(_ZERO, 1))
        p.drawRect(lx, int(yy), 210, 16)
        if act:
            p.fillRect(lx + 1, int(yy) + 1, int(208 * act / 512), 14, _CURVE)
        yy += 28
        p.setPen(_TEXT)
        p.setFont(QFont("Sans", 12, QFont.Bold))
        fm = p.fontMetrics()
        h = fm.boundingRect(QRect(0, 0, col_w, 2000), Qt.TextWordWrap,
                            f"活跃 {act}/512").height()
        p.drawText(QRect(lx, yy, col_w, h), Qt.TextWordWrap, f"活跃 {act}/512 神经元")
        yy += h + 6
        p.setPen(_TEXT2)
        p.setFont(QFont("Sans", 10))
        fm = p.fontMetrics()
        h = fm.boundingRect(QRect(0, 0, col_w, 2000), Qt.TextWordWrap,
                            f"能量 E={e:.1f} · 休眠率 {(512 - act) / 512 * 100:.0f}%").height()
        p.drawText(QRect(lx, yy, col_w, h), Qt.TextWordWrap,
                   f"能量 E={e:.1f} · 休眠率 {(512 - act) / 512 * 100:.0f}%")
        # 分隔线
        p.setPen(QPen(QColor("#30363d"), 1))
        p.drawLine(int(info_w + 4), int(y0 + 2), int(info_w + 4), int(y0 + row_h - 16))

        # ── 右侧: 大直方图 (非零激活分布) ──
        hx0 = info_w + 30
        hx1 = W - 20
        buf = np.concatenate(self.buf[li]) if self.buf[li] else np.zeros(1)
        pos = buf[buf > 0]
        # ── 右侧: 本帧实际激活直方图 (真实计数, 不累积平均 — 2026-09-05 老倪) ──
        hx0 = info_w + 52          # 左留 y 轴刻度
        hx1 = W - 20
        buf = np.concatenate(self.buf[li]) if self.buf[li] else np.zeros(1)
        cur0 = self.cur[li]
        # 横轴范围固定 (用累积 p99, 防单帧极值让轴每帧乱跳)
        AX = max(float(np.percentile(buf[buf > 0], 99)) if (buf > 0).any() else 0.15, 0.15)
        # 标题: 本帧真实数字 (0 值个数/非零均值/能量)
        nz = int((cur0 == 0).sum()) if cur0 is not None and cur0.size else 0
        ppos = cur0[cur0 > 0] if cur0 is not None else np.zeros(0)
        mc = float(ppos.mean()) if ppos.size else 0.0
        ec = float((cur0 ** 2).sum()) if cur0 is not None and cur0.size else 0.0
        p.setPen(_TEXT)
        p.setFont(QFont("Sans", 12, QFont.Bold))
        fm = p.fontMetrics()
        ttl = f"本帧实际激活分布: 512 神经元中 0 值 {nz} 个 · 非零均值 {mc:.2f} · 能量 {ec:.1f}"
        th = fm.boundingRect(QRect(0, 0, hx1 - hx0 + 40, 2000), Qt.TextWordWrap, ttl).height()
        p.drawText(QRect(hx0 - 40, int(y0) + 2, hx1 - hx0 + 40, th), Qt.TextWordWrap, ttl)
        y_top = int(y0) + 2 + th + 6
        p.setPen(_TEXT2)
        p.setFont(QFont("Sans", 10))
        axh = p.fontMetrics().height()
        y_bot = int(y0 + row_h) - 8 - axh
        if cur0 is not None and ppos.size >= 2:
            # 只统计非零值 (0 已单列数字); 柱高=该区间实际神经元个数
            hist, _ = np.histogram(ppos, bins=N_BINS, range=(0.0, AX))
            hmax = max(float(hist.max()), 1.0)
            bw = (hx1 - hx0) / N_BINS
            # y 轴刻度 (实际整数个数)
            p.setPen(_TEXT2)
            p.setFont(QFont("Sans", 9))
            for _f, _lbl in ((0.0, "0"), (0.5, f"{int(hmax / 2)}"), (1.0, f"{int(hmax)}")):
                yy2 = int(y_bot - (y_bot - y_top) * _f)
                p.drawLine(int(hx0 - 6), yy2, int(hx0 - 2), yy2)
                p.drawText(int(hx0 - 46), int(yy2 + 4), f"{_lbl}个")
            # 网格
            p.setPen(QPen(QColor("#1e2740"), 1))
            for gy in range(5):
                yy2 = y_top + (y_bot - y_top) * gy / 4
                p.drawLine(int(hx0), int(yy2), int(hx1), int(yy2))
            # 白柱 = 本帧真实计数
            p.setPen(Qt.NoPen)
            p.setBrush(_CURVE)
            for bi in range(N_BINS):
                hh = (y_bot - y_top) * hist[bi] / hmax
                if hh > 0.5:
                    p.drawRect(int(hx0 + bw * bi) + 1, int(y_bot - hh), max(int(bw) - 2, 1), int(hh))
            # 0 值标注 (虚线 + 个数, 不占柱)
            p.setPen(QPen(_CURVE_LIVE, 1.5, Qt.DashLine))
            p.drawLine(int(hx0), y_top, int(hx0), y_bot)
            p.setPen(_CURVE_LIVE)
            p.setFont(QFont("Sans", 9))
            p.drawText(int(hx0 + 4), int(y_top + 14), f"0值 ×{nz}")
        else:
            p.setPen(_TEXT2)
            p.setFont(QFont("Sans", 10))
            p.drawText(QRect(hx0, y_top, hx1 - hx0, 60), Qt.TextWordWrap, "本帧无激活(全部休眠)")
        # 轴标
        p.setPen(_TEXT2)
        p.setFont(QFont("Sans", 10))
        p.drawText(int(hx0), int(y_bot + axh - 4), "0")
        p.drawText(int(hx1 - 210), int(y_bot + axh - 4), f"激活值 → (横轴 0~{AX:.2f})")
