#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ff_hist_view.py — 🧠 前馈加速器激活可视化 (2026-09-04→09-05 老倪多次迭代)

默认「〰 波动视图」: 三层能量 E=Σx² 随时间的滚动波形 (同一时间轴对齐) —
  远段粗动作整体高能量, 插入精调整体回落; 三层轮廓相似=信息沿网络传递,
  看得到"波"从层1流到层3 (层间相关+时延=传递轮廓)。

右上可切「📊 分布直方图」: 本帧 512 神经元实际激活值直方图 (真实计数, 不平均)。

数据: ⚡前馈加速器探针 probe.act_raw (每层 512) + layers (能量/活跃)
用法: win = FFHistView(); win.push(probe); win.show()
"""
import numpy as np
from PyQt5.QtCore import Qt, QTimer, QRect, QPointF
from PyQt5.QtGui import QPainter, QColor, QPen, QFont, QPolygonF
from PyQt5.QtWidgets import QDialog, QPushButton

_BG_TOP = QColor("#0d1117")
_TEXT = QColor("#e6edf3")
_TEXT2 = QColor("#9da7b3")
_ZERO = QColor("#7d8590")
LAYER_COLORS = ["#58a6ff", "#00d4aa", "#ffb454"]   # 层1 蓝 / 层2 青 / 层3 橙金
LAYER_NAMES = ["第 1 层 · 输入编码", "第 2 层 · 特征组合", "第 3 层 · 决策输出"]
N_FRAMES = 600      # 滚动窗口帧数 (~12s @50Hz, 覆盖整个插拔流程全程)

# 🎯 2026-09-05 老倪: 阶段 → 色带 (横轴分段, 每段波形类型不同)
STAGE_ORDER = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"]
STAGE_COLORS = ["#58a6ff", "#8250df", "#7ee787", "#ffd02e", "#f0883e", "#a371f7", "#ff5555", "#00d4aa"]


def _map_stage(name):
    """阶段名归一: '插入 · 接触' → '插入' (引擎接触子态并入主阶段)"""
    if not name:
        return None
    for s in STAGE_ORDER:
        if s in name:
            return s
    return None


class FFHistView(QDialog):
    """前馈激活窗口: 默认三层能量波动视图 (波传递), 可切本帧直方图"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🧠 前馈加速器 · 三层激活波动 (能量随时间 · 波传递轮廓)")
        self.resize(1200, 840)
        self.setMinimumSize(960, 680)
        self.setWindowFlags(Qt.Window | Qt.WindowTitleHint | Qt.WindowSystemMenuHint
                            | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        self.buf = [[] for _ in range(3)]   # 每层 FIFO 帧 (512 float32)
        self.cur = [None, None, None]       # 最近一帧
        self.ener = [[], [], []]            # 每层每帧能量 E=Σx²
        self.prev = [None, None, None]      # 上一帧 (算帧间变化)
        self.dlt = [[], [], []]             # 每层每帧激活变化范数 ‖Δx‖₂ (事件波形)
        self.stages = []                    # 每帧阶段 (探针带 stage)
        self.info = {}
        self.view = "wave"                  # "wave" 波动 / "hist" 直方图
        self._dirty = True
        self._last_seq = 0      # 🔭 去重: 同一轮仿真帧只收一次 (播放/桥/灌全程不重复)
        self._cap_text = "🧠 等待激活数据 — 点「⚡引擎快演 ▶运行」或「⏭单步」后逐帧累积 (波动视图: 三层能量随时间, 轮廓传递=信息流动)"
        # 右上视图切换按钮
        self.btn_hist = QPushButton("📊 分布直方图", self)
        self.btn_wave = QPushButton("〰 波动视图", self)
        for b in (self.btn_hist, self.btn_wave):
            b.setStyleSheet("QPushButton{color:#e6edf3;background:#21262d;border:1px solid #30363d;"
                            "padding:3px 10px;font-size:12px;} QPushButton:hover{background:#30363d;}")
            b.hide()
        self.btn_hist.clicked.connect(lambda: self._set_view("hist"))
        self.btn_wave.clicked.connect(lambda: self._set_view("wave"))
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._throttled)
        self._timer.start(100)

    def _set_view(self, v):
        self.view = v
        self.btn_hist.setVisible(v == "wave")
        self.btn_wave.setVisible(v == "hist")
        self._sync_btns()
        self.update()

    def _sync_btns(self):
        # 放右上 (cap 条右侧)
        try:
            ww = self.width()
            self.btn_hist.setGeometry(ww - 300, 26, 130, 30)
            self.btn_wave.setGeometry(ww - 162, 26, 130, 30)
        except Exception:
            pass

    def resizeEvent(self, ev):
        try:
            super().resizeEvent(ev)
            self._sync_btns()
            self._show_btns_by_view()
        except Exception:
            pass

    def _show_btns_by_view(self):
        self.btn_hist.setVisible(self.view == "wave")
        self.btn_wave.setVisible(self.view == "hist")

    def showEvent(self, ev):
        try:
            super().showEvent(ev)
            self._show_btns_by_view()
            self._sync_btns()
        except Exception:
            pass

    # ── 数据 ──
    def reset(self):
        """新一轮仿真开始: 清缓冲与去重序号 (旧轮帧不再接收)"""
        for k in range(3):
            self.buf[k].clear()
            self.cur[k] = None
            self.ener[k].clear()
            self.dlt[k].clear()
            self.prev[k] = None
        self.stages.clear()
        self._last_seq = 0
        self._dirty = True

    def push(self, probe):
        raw = probe.get("act_raw")
        if not raw:
            return
        # 🔭 同一轮仿真帧去重 (打开窗口灌全程后, 播放/桥不再重复累积)
        sq = int(probe.get("_seq") or 0)
        if sq > 0 and self._last_seq > 0 and sq <= self._last_seq:
            return
        if sq > 0:
            self._last_seq = sq
        for i in range(3):
            a = np.asarray(raw[i], dtype=np.float32).ravel()
            if a.shape[0] != 512:
                continue
            self.buf[i].append(a)
            if len(self.buf[i]) > N_FRAMES:
                self.buf[i].pop(0)
            self.cur[i] = a
            self.ener[i].append(float((a ** 2).sum()))
            if len(self.ener[i]) > N_FRAMES:
                self.ener[i].pop(0)
            if self.prev[i] is not None:
                self.dlt[i].append(float(np.linalg.norm(a - self.prev[i])))
                if len(self.dlt[i]) > N_FRAMES:
                    self.dlt[i].pop(0)
            self.prev[i] = a
        st = probe.get("stage")
        self.stages.append(str(st) if st else "?")
        if len(self.stages) > N_FRAMES:
            self.stages.pop(0)
        self.info = {"obs": probe.get("obs", {}), "u_ff": probe.get("u_ff", []),
                     "layers": probe.get("layers", []), "stage": st}
        try:
            n = len(self.buf[0])
            u = self.info.get("u_ff", [])
            u_txt = (f"u_ff=[{u[0]:+.2f} {u[1]:+.2f} {u[2]:+.2f} · 夹爪{'闭合' if u[3] else '张开'}]"
                     if u else "u_ff=—")
            ob = self.info.get("obs", {})
            d_txt = f"手到目标 d={ob.get('d_h', 0):.2f}m" if ob and ob.get("d_h") is not None else ""
            stg = str(self.info.get("stage") or "").replace("阶段 ", "").replace("阶段:", "")
            s_txt = f"· 阶段: {stg}" if stg and stg != "?" else ""
            self._cap_text = (
                f"🧠 第 {n} 帧 {s_txt} · {u_txt} · {d_txt}\n"
                f"横轴=完整插拔流程时间 · 色带=动作阶段 · 每层波形=激活变化事件 (启动/抓取/接触/插入有尖峰) · 金底=插拔成功")
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
            p.fillRect(0, 0, r.width(), 86, QColor("#161b22"))
            lines = str(self._cap_text).split("\n")
            p.setPen(_TEXT)
            p.setFont(QFont("Sans", 12, QFont.Bold))
            fm = p.fontMetrics()
            h1 = fm.boundingRect(QRect(16, 0, r.width() - 340, 2000), Qt.TextWordWrap,
                                 lines[0]).height() + 4
            p.drawText(QRect(16, 10, r.width() - 340, h1), Qt.TextWordWrap | Qt.AlignVCenter,
                       lines[0])
            if len(lines) > 1:
                p.setPen(_TEXT2)
                p.setFont(QFont("Sans", 10))
                h2 = p.fontMetrics().boundingRect(QRect(16, 0, r.width() - 340, 2000),
                                                  Qt.TextWordWrap, lines[1]).height()
                p.drawText(QRect(16, 10 + h1 + 2, r.width() - 340, h2),
                           Qt.TextWordWrap | Qt.AlignVCenter, lines[1])
            if not any(self.buf):
                p.setPen(_TEXT2)
                p.setFont(QFont("Sans", 13))
                p.drawText(r.adjusted(20, 100, -20, -20), Qt.AlignCenter,
                           "等待激活数据…\n\n先点「⚡引擎快演 ▶运行」或「⏭单步」, 每帧 512 个神经元激活自动进来\n\n"
                           "窗口默认 = 三层能量波动视图: 每一层一条波形, 同一时间轴 —\n"
                           "看到波形起伏(远段大动作能量高, 插入精调回落), 三层轮廓相似 = 信息沿网络传递")
                p.end()
                return
            if self.view == "wave":
                self._draw_wave(p, r)
            else:
                self._draw_hist_rows(p, r)
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

    # ── 〰 波动视图 v4: 全程分阶段波形 (2026-09-05 老倪: 每层横轴=阶段, 不同类型波形对应不同阶段,
    #   体现整个插拔流程, 尤其插拔成功) ──
    def _draw_wave(self, p, r):
        W, H = r.width(), r.height()
        top = 92
        row_h = (H - top - 12) / 3.0
        n = len(self.dlt[0]) if self.dlt[0] else 0
        # 全局时间轴 (帧→s, 引擎 dt=0.02)
        T = n * 0.02
        x0 = 16
        x1 = W - 16
        for li in range(3):
            y0 = top + li * row_h
            dl = self.dlt[li]
            sts = self.stages
            m = min(len(dl), len(sts))
            # 行标题 (层名, 大字不换行风险低)
            p.setPen(_TEXT)
            p.setFont(QFont("Sans", 12, QFont.Bold))
            p.drawText(QRect(16, int(y0) + 2, W - 300, 24), Qt.TextWordWrap,
                       f"{LAYER_NAMES[li]} · 激活变化事件 ‖Δx‖")
            # 阶段色带 (行内顶部 18px): 每帧阶段 → 色块
            band_y0 = int(y0) + 30
            band_y1 = band_y0 + 16
            # 阶段边界列表
            if m >= 2:
                st_clean = [str(s).replace("阶段 ", "").replace("阶段:", "") for s in sts[:m]]
                seg = []   # (name, i0, i1)
                for i in range(m):
                    if not seg or st_clean[i] != seg[-1][0]:
                        seg.append([st_clean[i], i, i])
                    else:
                        seg[-1][2] = i
                # 色带块 + 段名 (放得下才写, 字体不遮波形区)
                for name, i0, i1 in seg:
                    if name in ("?", "None"):
                        continue
                    xa = int(x0 + (x1 - x0) * i0 / max(m - 1, 1))
                    xb = int(x0 + (x1 - x0) * max(i1, i0 + 1) / max(m - 1, 1))
                    base = _map_stage(name)
                    ci = STAGE_ORDER.index(base) if base else -1
                    col = QColor(STAGE_COLORS[ci]) if ci >= 0 else QColor("#57606a")
                    col.setAlpha(90)
                    p.setPen(Qt.NoPen)
                    p.setBrush(col)
                    p.drawRect(xa, band_y0, max(xb - xa, 1), band_y1 - band_y0)
                    # 段名 (归一后主阶段名; 白字小, 宽度够才写 → 不重叠)
                    disp = base or name
                    if ci >= 0:
                        p.setFont(QFont("Sans", 9))
                        tw = p.fontMetrics().horizontalAdvance(disp)
                        if xb - xa >= tw + 10:
                            p.setPen(QColor("#e6edf3"))
                            p.drawText(int(xa + (xb - xa - tw) / 2), band_y1 - 4, disp)
            # 波形区
            w_y0 = band_y1 + 8
            w_y1 = int(y0 + row_h) - 34
            # 底部时间轴
            p.setPen(QColor("#8b949e"))
            p.setFont(QFont("Sans", 9))
            axh = p.fontMetrics().height()
            t_y = int(y0 + row_h) - axh - 6
            if m >= 2:
                dl_arr = np.asarray(dl[:m], dtype=float)
                # 波形 y: 去基线放大 + 大尖峰截顶 (峰顶标真实值)
                pc = float(np.percentile(dl_arr, 96))
                pc = max(pc, 1e-4)
                mn = float(dl_arr.min()) * 0.9
                mx = pc * 1.15
                if mx - mn < 1e-6:
                    mx = mn + 1.0
                def Y(v):
                    return int(w_y1 - (w_y1 - w_y0) * (v - mn) / (mx - mn))
                # 网格
                p.setPen(QPen(QColor("#1e2740"), 1))
                for gy in range(3):
                    yy = w_y0 + (w_y1 - w_y0) * gy / 2
                    p.drawLine(x0, int(yy), x1, int(yy))
                # 完成段 (插拔成功) 金色底纹
                done_at = None
                for i in range(m):
                    if str(sts[i]).replace("阶段 ", "").replace("阶段:", "") in ("完成", "插入"):
                        done_at = i
                        if "完成" in str(sts[i]):
                            break
                if done_at is not None and done_at > 0:
                    xd = int(x0 + (x1 - x0) * done_at / max(m - 1, 1))
                    p.fillRect(xd, w_y0, x1 - xd, w_y1 - w_y0, QColor(255, 213, 0, 26))
                # 面积 + 线
                xs = x0 + (x1 - x0) * np.arange(m) / max(m - 1, 1)
                col = QColor(LAYER_COLORS[li])
                col.setAlpha(45)
                p.setPen(Qt.NoPen)
                p.setBrush(col)
                poly = [QPointF(float(xs[0]), float(w_y1))]
                yclip_prev = None
                for xx, v in zip(xs, dl_arr):
                    yv = Y(v)
                    poly.append(QPointF(float(xx), float(max(yv, w_y0))))
                poly.append(QPointF(float(xs[-1]), float(w_y1)))
                p.drawPolygon(QPolygonF(poly))
                p.setPen(QPen(QColor(LAYER_COLORS[li]), 2))
                for j in range(1, m):
                    y1 = Y(float(dl_arr[j - 1]))
                    y2 = Y(float(dl_arr[j]))
                    p.drawLine(int(xs[j - 1]), y1, int(xs[j]), y2)
                # 超顶尖峰 (插入/事件) 标注真实峰值
                im = int(np.argmax(dl_arr))
                if dl_arr[im] > mx:
                    p.setPen(QColor("#ff5555"))
                    p.setFont(QFont("Sans", 9, QFont.Bold))
                    p.drawText(int(xs[im]) - 20, w_y0 + 12, f"▲{dl_arr[im]:.1f}")
                # 底部信息: 范围 + 阶段读法
                p.setPen(QColor("#8b949e"))
                p.setFont(QFont("Sans", 9))
                p.drawText(int(x0), t_y,
                           f"峰值{max(dl_arr):.1f} · 平稳段细波=匀速移动 尖峰=抓取/接触/插入 · 波形↑=该层在改写表征")
                p.drawText(int(x1) - 150, t_y, "0s")
                p.drawText(int(x1) - 40, t_y, f"{T:.1f}s")
            else:
                p.setPen(QColor("#8b949e"))
                p.setFont(QFont("Sans", 10))
                p.drawText(QRect(x0, w_y0, x1 - x0, 50), Qt.TextWordWrap, "累积中… (≥2 帧画波形)")
            # 行分隔
            p.setPen(QPen(QColor("#21262d"), 1))
            p.drawLine(16, int(y0 + row_h) - 1, W - 16, int(y0 + row_h) - 1)
        # 全窗底部: 流程总结 (插拔成功环节 — 引擎 done=插入到底, 末段为 插入/完成 即成功)
        try:
            if not self.stages:
                return
            last_base = _map_stage(str(self.stages[-1])) or ""
            reached_insert = any(_map_stage(str(s)) == "插入" for s in self.stages)
            ok_done = reached_insert and (last_base in ("插入", "完成"))
            verdict = "✅ 插拔成功 (已走完 接近→对位→下降→抓取→抬起→转移→插入)" if ok_done else "▶ 流程进行中…"
            col = QColor("#00d4aa") if ok_done else QColor("#8b949e")
            p.setPen(col)
            p.setFont(QFont("Sans", 13, QFont.Bold))
            p.drawText(QRect(16, H - 34, W - 32, 26), Qt.TextWordWrap,
                       f"{verdict} · 已播 {n} 帧/{T:.1f}s · 色带=阶段 · 金底=插拔收尾段")
        except Exception:
            pass

    # ── 📊 直方图视图: 本帧 512 实际激活值 (真实计数) ──
    def _draw_hist_rows(self, p, r):
        W, H = r.width(), r.height()
        top = 92
        row_h = (H - top - 10) / 3.0
        info_w = 330
        for li in range(3):
            y0 = top + li * row_h
            buf = np.concatenate(self.buf[li]) if self.buf[li] else np.zeros(1)
            cur0 = self.cur[li]
            AX = max(float(np.percentile(buf[buf > 0], 99)) if (buf > 0).any() else 0.15, 0.15)
            nz = int((cur0 == 0).sum()) if cur0 is not None and cur0.size else 0
            ppos = cur0[cur0 > 0] if cur0 is not None else np.zeros(0)
            mc = float(ppos.mean()) if ppos.size else 0.0
            ec = float((cur0 ** 2).sum()) if cur0 is not None and cur0.size else 0.0
            # 左列
            p.setPen(_TEXT)
            p.setFont(QFont("Sans", 12, QFont.Bold))
            fm = p.fontMetrics()
            h = fm.boundingRect(QRect(0, 0, info_w - 36, 2000), Qt.TextWordWrap,
                                LAYER_NAMES[li]).height()
            p.drawText(QRect(16, int(y0) + 4, info_w - 36, h), Qt.TextWordWrap, LAYER_NAMES[li])
            yy = int(y0) + 4 + h + 6
            p.setPen(_TEXT2)
            p.setFont(QFont("Sans", 10))
            p.drawText(QRect(16, yy, info_w - 36, 30), Qt.TextWordWrap,
                       f"0值 {nz}/512 · 非零均值 {mc:.2f}")
            yy += 34
            p.setPen(_TEXT)
            p.setFont(QFont("Sans", 12, QFont.Bold))
            p.drawText(QRect(16, yy, info_w - 36, 24), Qt.TextWordWrap, f"能量 E={ec:.0f}")
            # 右直方图
            hx0 = info_w + 8
            hx1 = W - 20
            y_top = int(y0) + 30
            y_bot = int(y0 + row_h) - 24
            p.setPen(_TEXT2)
            p.setFont(QFont("Sans", 9))
            axh = p.fontMetrics().height()
            y_bot = int(y0 + row_h) - 8 - axh
            if cur0 is not None and ppos.size >= 2:
                hist, _ = np.histogram(ppos, bins=60, range=(0.0, AX))
                hmax = max(float(hist.max()), 1.0)
                bw = (hx1 - hx0) / 60
                p.setPen(_TEXT2)
                p.setFont(QFont("Sans", 9))
                for _f, _lbl in ((0.0, "0"), (0.5, f"{int(hmax / 2)}"), (1.0, f"{int(hmax)}")):
                    yy2 = int(y_bot - (y_bot - y_top) * _f)
                    p.drawLine(int(hx0 - 6), yy2, int(hx0 - 2), yy2)
                    p.drawText(int(hx0 - 46), int(yy2 + 4), f"{_lbl}个")
                p.setPen(QPen(QColor("#1e2740"), 1))
                for gy in range(5):
                    yy2 = y_top + (y_bot - y_top) * gy / 4
                    p.drawLine(int(hx0), int(yy2), int(hx1), int(yy2))
                p.setPen(Qt.NoPen)
                p.setBrush(_TEXT)
                for bi in range(60):
                    hh = (y_bot - y_top) * hist[bi] / hmax
                    if hh > 0.5:
                        p.drawRect(int(hx0 + bw * bi) + 1, int(y_bot - hh),
                                   max(int(bw) - 2, 1), int(hh))
                p.setPen(QPen(QColor("#ff5555"), 1.5, Qt.DashLine))
                p.drawLine(int(hx0), y_top, int(hx0), y_bot)
                p.setPen(QColor("#ff5555"))
                p.setFont(QFont("Sans", 9))
                p.drawText(int(hx0 + 4), int(y_top + 14), f"0值 ×{nz}")
            else:
                p.setPen(_TEXT2)
                p.setFont(QFont("Sans", 10))
                p.drawText(QRect(hx0, y_top, hx1 - hx0, 40), Qt.TextWordWrap, "本帧无激活")
            p.setPen(_TEXT2)
            p.setFont(QFont("Sans", 9))
            p.drawText(int(hx0), int(y_bot + axh - 4), "0")
            p.drawText(int(hx1 - 200), int(y_bot + axh - 4), f"激活值 → (0~{AX:.2f})")
