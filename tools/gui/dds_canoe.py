#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🌐 全局数据空间 —— CANoe 主窗口范式 (2026-09-29 老倪「参考 Vector CANoe demo 重新设计 UI」)

版式**照 CANoe 16 主界面逐像素基准**(子代理读官方截图所得):
  · 顶部测量组 (CANoe: Start 黄闪电 / Stop 灰八边形 / Step / Online Mode / dec|hex|sym|num)
  · 上排左 **Data 面板 = 信号表**  (CANoe 列: Name | Value | Unit | Last Value Time [s] | Bar)
  · 上排右 详情/判据面板
  · 中 **Trace 整宽** (CANoe 列: Time | Name | Object Type | Classification | Probability [%] |
                        Sender Name | Sender Id | Tracking Id | Group) + 面板工具条(⏸/Δt/🔍/🗑/导出)
  · 底 标签栏 (CANoe: Configuration | Measurement | Data Window) → 数据闭环 | 质量告警 + 右下计时/拍照
数据全真实: busdb.json(画布 DBC 74节点/182信号/14报文) · live.json(每话题质量) ·
trace.jsonl(总线帧) · loop.json(闭环阶段)。缺测一律 '—' (不许 0 冒充); 实时量带帧龄与拍照时间。
"""
from __future__ import annotations

import json
import os
import time

from PyQt5.QtCore import Qt, QRectF, QTimer
from PyQt5.QtGui import QColor, QFont, QGuiApplication, QPainter
from PyQt5.QtWidgets import (QAbstractItemView, QCheckBox, QFrame, QHBoxLayout, QHeaderView, QLabel,
                             QLineEdit, QPushButton, QSplitter, QStyledItemDelegate, QTableWidget,
                             QTableWidgetItem, QTextEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                             QWidget)

# ── 调色板(与控制台主色一致) ──
C_BG, C_BG2, C_CARD, C_BORDER = "#0d1117", "#161b22", "#1c2333", "#30363d"
C_WHITE, C_GRAY, C_DIM, C_BLUE = "#ffffff", "#8b949e", "#6e7681", "#58a6ff"
C_HEAD = "#b6c2cf"          # 表头文字: 原 #8b949e 在表头条上仅 5.1:1(质检最弱文本) → 提亮  # C_DIM 提亮: 原 #484f58 对比度仅 2.3:1(质检: 几乎看不见)
C_GREEN, C_YELLOW, C_RED, C_PURPLE = "#3fb950", "#d29922", "#f85149", "#bc8cff"
C_BAR = "#2f81f7"     # CANoe 的 Bar 是实心蓝 #0072C5, 深色主题里提亮
C_SEL = "#243a52"     # CANoe 选中行浅蓝 #AFD7F1 的深色对应

DS_DIR = os.environ.get("ZMAX_DATASPACE_DIR", "/home/ubuntu/zmax_data/dataspace")
LIVE, TRACE = os.path.join(DS_DIR, "live.json"), os.path.join(DS_DIR, "trace.jsonl")
LOOP, BUSDB = os.path.join(DS_DIR, "loop.json"), os.path.join(DS_DIR, "busdb.json")

LV_COLOR = {"L5": C_PURPLE, "L4": C_BLUE, "L3": "#2fc4b2", "L2": C_GREEN, "meta": C_GRAY}
VERDICT_COLOR = {"ok": C_GREEN, "pass": C_GREEN, "warn": C_YELLOW, "fail": C_RED,
                 "unknown": C_GRAY, "stale": C_YELLOW}
LAMP_ICON = {"green": "🟢", "yellow": "🟡", "red": "🔴", "black": "⚫"}
MONO, UI = "Consolas", "Arial"


def _j(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                        # noqa: BLE001
        return default if default is not None else {}


def _blank(v):
    """缺测(-1/-1.0/None/空) → '—' (全空间统一: 不许用 0 冒充)"""
    if v is None or v == "":
        return "—"
    try:
        if isinstance(v, (int, float)) and float(v) < 0:
            return "—"
    except Exception:                                                        # noqa: BLE001
        pass
    return v


def _num(v, nd=2, suffix=""):
    v = _blank(v)
    if v == "—":
        return "—"
    try:
        return f"{float(v):.{nd}f}{suffix}"
    except Exception:                                                        # noqa: BLE001
        return f"{v}{suffix}"


def _pad(label, width=14):
    """中文按 2 列宽补齐 → 详情面板的值列能对齐成一竖线(质检: 破折号 x2560-2576 漂移)"""
    w = sum(2 if ord(ch) > 0x2E80 else 1 for ch in str(label))
    return str(label) + " " * max(1, width - w)


def _hhmmss(t):
    try:
        return time.strftime("%H:%M:%S", time.localtime(float(t)))
    except Exception:                                                        # noqa: BLE001
        return "—"


def _rel(t0, t):
    """相对测量起点的秒 (CANoe Trace 的 Time 列 = 测量时间, 3 位小数)"""
    try:
        return "%9.3f" % (float(t) - float(t0))
    except Exception:                                                        # noqa: BLE001
        return "—"


class BarDelegate(QStyledItemDelegate):
    """CANoe 的 Bar 列: 实心蓝条 = 实测值 / 设计值, 0 或无量纲不画。"""

    def paint(self, p, opt, idx):
        super().paint(p, opt, idx)
        try:
            ratio = float(idx.data(Qt.UserRole))
        except Exception:                                                    # noqa: BLE001
            ratio = -1.0
        if ratio <= 0:
            return
        r = opt.rect
        w = max(2, int((r.width() - 26) * min(1.0, ratio)))
        p.save()
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(C_CARD))                                    # 底轨(质检: 无轨道无法判满格)
        p.drawRoundedRect(QRectF(r.x() + 6, r.y() + r.height() * 0.28,
                                 max(6, r.width() - 26), r.height() * 0.44), 2, 2)
        p.restore()
        p.save()
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(C_BAR))
        p.drawRoundedRect(QRectF(r.x() + 4, r.y() + r.height() * 0.28, w, r.height() * 0.44), 2, 2)
        p.restore()


class BusView(QWidget):
    """CANoe 范式的多窗格数据空间视图"""

    def __init__(self, main_win=None, parent=None):
        super().__init__(parent)
        self.main = main_win
        self._busdb, self._live, self._loop = {}, {}, {}
        self._t0 = None
        self._sel_kind = self._sel_obj = None
        self._trace_rows = []
        self._filter = ""
        self._dt_mode = False
        self.setObjectName("DdsCanoeView")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"#DdsCanoeView {{ background:{C_BG}; }}")
        self._build()
        self.reload(force_tree=True)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.reload)
        self._timer.start(1500)

    # ─────────────────── 骨架 ───────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)
        root.addWidget(self._measure_bar())

        vs = QSplitter(Qt.Vertical)
        vs.setChildrenCollapsible(False)
        hs = QSplitter(Qt.Horizontal)
        hs.setChildrenCollapsible(False)
        hs.addWidget(self._data_panel())
        hs.addWidget(self._detail_panel())
        hs.setStretchFactor(0, 3)
        hs.setStretchFactor(1, 2)
        hs.setSizes([1620, 1080])
        vs.addWidget(hs)
        vs.addWidget(self._trace_panel())
        vs.addWidget(self._bottom_tabs())
        vs.setStretchFactor(0, 3)
        vs.setStretchFactor(1, 3)
        vs.setStretchFactor(2, 2)
        vs.setSizes([760, 720, 470])
        root.addWidget(vs, 1)

    def _panel(self, title, color=C_BLUE):
        box = QFrame()
        box.setStyleSheet(f"QFrame {{ background:{C_BG2}; border:1px solid {C_BORDER}; border-radius:6px; }}")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(8, 6, 8, 8)
        lay.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(8)
        t = QLabel(title)
        t.setFont(QFont(UI, 10, QFont.Bold))
        t.setStyleSheet(f"color:{color}; background:transparent; border:none;")
        head.addWidget(t)
        head.addStretch()
        lay.addLayout(head)
        return box, lay, head

    def _sm_btn(self, txt, tip, fn, color=C_GRAY, checkable=False, width=None):
        b = QPushButton(txt)
        b.setFont(QFont(UI, 9))
        b.setToolTip(tip)
        b.setCheckable(checkable)
        if width:
            b.setFixedWidth(width)
        b.setStyleSheet(
            f"QPushButton {{ background:{C_CARD}; color:{color}; border:1px solid {C_BORDER};"
            f" border-radius:4px; padding:4px 10px; }}"
            f"QPushButton:hover {{ border-color:{C_BLUE}; color:{C_WHITE}; }}"
            f"QPushButton:checked {{ color:{C_YELLOW}; border-color:{C_YELLOW}; }}")
        b.clicked.connect(fn)
        return b

    def _measure_bar(self):
        """CANoe 顶部测量组: Start(黄闪电)/Stop(灰八边形) 大按钮 + 计数/灯 + 计时"""
        bar = QFrame()
        bar.setStyleSheet(f"QFrame {{ background:{C_BG2}; border:1px solid {C_BORDER}; border-radius:6px; }}")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(16)

        self.btn_start = QPushButton("⚡\nStart")
        self.btn_start.setFont(QFont(UI, 10, QFont.Bold))
        self.btn_start.setFixedSize(76, 54)
        self.btn_start.setToolTip("开始: 恢复 Trace 滚动并立刻重读总线(live.json / trace.jsonl) — 等价 CANoe Start")
        self.btn_start.setStyleSheet(
            f"QPushButton {{ background:{C_CARD}; color:{C_YELLOW}; border:2px solid {C_YELLOW};"
            f" border-radius:5px; }} QPushButton:hover {{ background:#2a2312; }}")
        self.btn_start.clicked.connect(self._on_start)
        lay.addWidget(self.btn_start)

        self.btn_stop = QPushButton("⬢\nStop")
        self.btn_stop.setFont(QFont(UI, 10, QFont.Bold))
        self.btn_stop.setFixedSize(76, 54)
        self.btn_stop.setToolTip("停止: 冻结 Trace 视图(总线与数据源照收, 等价 CANoe Stop)")
        self.btn_stop.setStyleSheet(
            f"QPushButton {{ background:{C_CARD}; color:{C_GRAY}; border:2px solid {C_GRAY};"
            f" border-radius:5px; }} QPushButton:hover {{ color:{C_WHITE}; border-color:{C_WHITE}; }}")
        self.btn_stop.clicked.connect(self._on_stop)
        self.btn_stop.setEnabled(False)
        lay.addWidget(self.btn_stop)

        self.lb_state = QLabel("● 测量 运行中")
        self.lb_state.setFont(QFont(UI, 11, QFont.Bold))
        self.lb_state.setStyleSheet(f"color:{C_GREEN}; background:transparent; border:none;")
        self.lb_mode = QLabel("档位 —")
        self.lb_mode.setFont(QFont(MONO, 10))
        self.lb_mode.setStyleSheet(f"color:{C_BLUE}; background:transparent; border:none;")
        self.lb_fresh = QLabel("刷新龄 —")
        self.lb_fresh.setFont(QFont(MONO, 10))
        self.lb_fresh.setStyleSheet(f"color:{C_GRAY}; background:transparent; border:none;")
        self.lb_msgs = QLabel("报文 —")
        self.lb_msgs.setFont(QFont(MONO, 10))
        self.lb_msgs.setStyleSheet(f"color:{C_WHITE}; background:transparent; border:none;")
        self.lb_lamps = QLabel("灯 —")
        self.lb_lamps.setFont(QFont(UI, 11))
        self.lb_lamps.setStyleSheet(f"color:{C_WHITE}; background:transparent; border:none;")
        self.lb_clock = QLabel("0:00:00")
        self.lb_clock.setFont(QFont(MONO, 10, QFont.Bold))
        self.lb_clock.setStyleSheet(f"color:{C_WHITE}; background:transparent; border:none;")
        for w in (self.lb_state, self.lb_mode, self.lb_fresh, self.lb_msgs, self.lb_lamps, self.lb_clock):
            lay.addWidget(w)
        lay.addStretch()
        self.lb_mid = QLabel("—")
        self.lb_mid.setFont(QFont(MONO, 9))
        self.lb_mid.setStyleSheet(f"color:{C_GRAY}; background:transparent; border:none;")
        lay.addWidget(self.lb_mid)
        lay.addStretch()
        lay.addWidget(self._sm_btn("🔄 刷新", "立刻重读 live.json / trace.jsonl",
                                   lambda: self.reload(force_tree=True)))
        self.btn_classic = self._sm_btn("🗂 经典视图", "切回原来的 12 个 Tab 视图(旧入口不丢)",
                                        self._toggle_classic, color=C_GRAY, checkable=True)
        lay.addWidget(self.btn_classic)
        return bar

    def _data_panel(self):
        """CANoe 的 Data 面板: 信号表(Name | Value | Unit | Last Value Time [s] | Bar)"""
        box, lay, head = self._panel("📋 Data — 信号表 (报文 / 信号 / 节点)", C_BLUE)
        self.chk_only_alive = QCheckBox("只看活报文")
        self.chk_only_alive.setFont(QFont(UI, 9))
        self.chk_only_alive.setStyleSheet(f"color:{C_GRAY}; background:transparent;")
        self.chk_only_alive.stateChanged.connect(lambda *_: self.reload(force_tree=True))
        head.addWidget(self.chk_only_alive)
        head.addWidget(self._sm_btn("展开/收起", "展开或收起 报文/信号/节点 三组", self._toggle_all))
        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["Name", "Value", "Unit", "Last Value Time [s]",
                                   "Bar  实测/设计"])
        self.tree.setStyleSheet(
            f"QTreeWidget {{ background:{C_BG}; color:{C_WHITE}; border:none; font-family:{UI}; font-size:10pt; }}"
            f"QTreeWidget::item {{ padding:6px 2px; }}"                        # 行高与 Trace/闭环表齐(质检: 46.5px vs 60px)
            f"QTreeWidget::item:selected {{ background:{C_SEL}; }}"
            f"QHeaderView::section {{ background:{C_CARD}; color:{C_HEAD}; border:none; padding:4px; }}")
        self.tree.setUniformRowHeights(True)
        self.tree.header().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)   # 列头左对齐=与内容同列
        self.tree.setItemDelegateForColumn(4, BarDelegate(self.tree))
        h = self.tree.header()
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        for i, w in ((1, 120), (2, 80), (3, 180), (4, 160)):
            h.setSectionResizeMode(i, QHeaderView.Interactive)   # 🐛 卡顿真根因: ResizeToContents
            self.tree.setColumnWidth(i, w)                       #   每秒重建时逐格重算列宽(192DPI 极贵)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.itemClicked.connect(self._on_tree_click)
        lay.addWidget(self.tree, 1)
        return box

    def _detail_panel(self):
        box, lay, head = self._panel("🔎 详情 — 选中对象 (属性 + 质量判据)", C_YELLOW)
        head.addWidget(self._sm_btn("📋 复制", "复制右侧详情文本(可直接粘到 CLI / 邮件)", self.copy_detail))
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setFont(QFont(MONO, 10))
        self.detail.setStyleSheet(f"QTextEdit {{ background:{C_BG}; color:{C_WHITE}; border:none; }}")
        self.detail.setText("点左侧 Data 表 或 Trace 任意一行 → 这里显示该对象的完整属性与质量判据(逐条)。")
        lay.addWidget(self.detail, 1)
        return box

    def _trace_panel(self):
        """CANoe 的 Trace 面板: 整宽 + 自带工具条(刷新/清除/暂停/Δt/搜索/导出)"""
        box, lay, head = self._panel("📋 Trace — 总线帧流 (最新在顶 · 测量时间)", C_GREEN)
        self.btn_pause = self._sm_btn("⏸ 暂停", "暂停/恢复 Trace 滚动(数据照收, 只冻结视图)",
                                      self._toggle_pause, checkable=True)
        self.btn_dt = self._sm_btn("Δt", "Time 列切「与同话题上一帧的时间差」(CANoe Δt)",
                                   self._toggle_dt, checkable=True)
        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText("🔍 过滤 (话题名 / 类型, 支持子串)")
        self.ed_search.setFont(QFont(MONO, 9))
        self.ed_search.setFixedWidth(320)
        self.ed_search.setStyleSheet(f"QLineEdit {{ background:{C_BG}; color:{C_WHITE};"
                                     f" border:1px solid {C_BORDER}; border-radius:4px; padding:4px 8px; }}")
        self.ed_search.textChanged.connect(self._on_filter)
        head.addWidget(self.btn_pause)
        head.addWidget(self.btn_dt)
        head.addWidget(self.ed_search)
        head.addWidget(self._sm_btn("🗑 清屏", "只清 Trace 视图, 不动 trace.jsonl 原始记录", self._clear_trace))
        head.addWidget(self._sm_btn("📤 导出 CSV", "导出当前 Trace 表(Excel 可开)", self.export_trace))

        self.tb = QTableWidget(0, 9)
        self.tb.setHorizontalHeaderLabels(
            ["Time", "Name", "Object Type", "Classification", "Probability [%]", "Sender Name",
             "Sender Id", "Tracking Id", "Group"])
        self.tb.setStyleSheet(
            f"QTableWidget {{ background:{C_BG}; color:{C_WHITE}; border:none; gridline-color:#21262d;"
            f" font-family:{MONO}; font-size:10pt; }}"
            f"QTableWidget::item {{ padding:2px 6px; }}"
            f"QTableWidget::item:selected {{ background:{C_SEL}; color:{C_WHITE}; }}"
            f"QHeaderView::section {{ background:{C_CARD}; color:{C_HEAD}; border:none; padding:4px;"
            f" font-family:{UI}; }}")
        self.tb.verticalHeader().setVisible(False)
        self.tb.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tb.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tb.setShowGrid(True)
        self.tb.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        th = self.tb.horizontalHeader()
        for i, w in ((0, 160), (2, 180), (3, 160), (4, 140), (5, 260), (6, 170), (7, 140), (8, 120)):
            th.setSectionResizeMode(i, QHeaderView.Interactive)  # 🐛 同上(卡死根因)
            self.tb.setColumnWidth(i, w)
        th.setSectionResizeMode(1, QHeaderView.Stretch)
        self.tb.itemClicked.connect(self._on_trace_click)
        lay.addWidget(self.tb, 1)
        return box

    def _bottom_tabs(self):
        """CANoe 底部标签栏 → 数据闭环 | 质量告警 (+ 右下计时/拍照)"""
        box = QFrame()
        box.setStyleSheet(f"QFrame {{ background:{C_BG2}; border:1px solid {C_BORDER}; border-radius:6px; }}")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(6)
        tabrow = QHBoxLayout()
        tabrow.setSpacing(6)
        self._btns = {}
        for key, txt in (("loop", "🔁 数据闭环"), ("alert", "⚠ 质量告警")):
            b = QPushButton(txt)
            b.setFont(QFont(UI, 10, QFont.Bold))
            b.setCheckable(True)
            b.setStyleSheet(
                f"QPushButton {{ background:transparent; color:{C_GRAY}; border:none;"
                f" border-bottom:2px solid transparent; padding:4px 12px; }}"
                f"QPushButton:checked {{ color:{C_BLUE}; border-bottom:2px solid {C_BLUE}; }}")
            b.clicked.connect(lambda _=False, k=key: self._show_bottom(k))
            self._btns[key] = b
            tabrow.addWidget(b)
        self._btns["loop"].setChecked(True)
        tabrow.addStretch()
        self.lb_stamp = QLabel("拍照 —")
        self.lb_stamp.setFont(QFont(MONO, 9))
        self.lb_stamp.setStyleSheet(f"color:{C_GRAY}; background:transparent; border:none;")
        tabrow.addWidget(self.lb_stamp)
        lay.addLayout(tabrow)

        self.tb_loop = QTableWidget(0, 5)
        self.tb_loop.setHorizontalHeaderLabels(["阶段", "名称", "质量门 (gate)", "owner", "状态 / 证据"])
        self.tb_alert = QTableWidget(0, 3)
        self.tb_alert.setHorizontalHeaderLabels(["级别", "对象", "问题 (规则: 实测)"])
        for t in (self.tb_loop, self.tb_alert):
            t.setStyleSheet(
                f"QTableWidget {{ background:{C_BG}; color:{C_WHITE}; border:none; gridline-color:#21262d;"
                f" font-family:{UI}; font-size:9pt; }}"
                f"QTableWidget::item {{ padding:2px 6px; }}"
                f"QTableWidget::item:selected {{ background:{C_SEL}; }}"
                f"QHeaderView::section {{ background:{C_CARD}; color:{C_HEAD}; border:none; padding:4px; }}")
            t.verticalHeader().setVisible(False)
            t.setEditTriggers(QAbstractItemView.NoEditTriggers)
            t.setSelectionBehavior(QAbstractItemView.SelectRows)
            lay.addWidget(t, 1)
        self.tb_loop.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.tb_alert.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        lh = self.tb_loop.horizontalHeader()
        for i, w in ((0, 110), (1, 240), (2, 340), (3, 160)):   # 🐛 ResizeToContents → 固定宽
            lh.setSectionResizeMode(i, QHeaderView.Interactive)
            self.tb_loop.setColumnWidth(i, w)
        lh.setSectionResizeMode(4, QHeaderView.Stretch)
        ah = self.tb_alert.horizontalHeader()
        for i, w in ((0, 130), (1, 280)):
            ah.setSectionResizeMode(i, QHeaderView.Interactive)
            self.tb_alert.setColumnWidth(i, w)
        ah.setSectionResizeMode(2, QHeaderView.Stretch)
        self.tb_alert.hide()
        return box

    def _show_bottom(self, key):
        for k, b in self._btns.items():
            b.setChecked(k == key)
        self.tb_loop.setVisible(key == "loop")
        self.tb_alert.setVisible(key == "alert")

    def _toggle_all(self):
        roots = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        want = not all(r.isExpanded() for r in roots if r)
        for r in roots:
            if r:
                r.setExpanded(want)

    def _on_start(self):
        self.btn_pause.setChecked(False)
        self.btn_pause.setText("⏸ 暂停")
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.lb_state.setText("● 测量 运行中")
        self.reload(force_tree=True)

    def _on_stop(self):
        self.btn_pause.setChecked(True)
        self.btn_pause.setText("▶ 继续")
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.lb_state.setText("■ 测量 已停止")

    def _toggle_pause(self):
        on = self.btn_pause.isChecked()
        self.btn_pause.setText("▶ 继续" if on else "⏸ 暂停")
        self.btn_start.setEnabled(on)
        self.btn_stop.setEnabled(not on)
        self.lb_state.setText("■ 测量 已停止" if on else "● 测量 运行中")
        if not on:
            self.reload()

    def _toggle_dt(self):
        self._dt_mode = self.btn_dt.isChecked()
        self._fill_trace()

    def _on_filter(self, txt):
        self._filter = (txt or "").strip().lower()
        self._fill_trace()

    def _clear_trace(self):
        self.tb.setRowCount(0)
        self._trace_rows = []

    def export_trace(self):
        from PyQt5.QtWidgets import QFileDialog, QMessageBox
        path, _ = QFileDialog.getSaveFileName(
            self, "导出 Trace CSV",
            os.path.expanduser("~/zmax_data/dataspace/trace_%s.csv" % time.strftime("%Y%m%d_%H%M%S")),
            "CSV (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(",".join('"%s"' % self.tb.horizontalHeaderItem(c).text()
                                 for c in range(self.tb.columnCount())) + "\n")
                for r in range(self.tb.rowCount()):
                    vals = []
                    for c in range(self.tb.columnCount()):
                        it = self.tb.item(r, c)
                        vals.append('"%s"' % ((it.text() if it else "").replace('"', '""')))
                    f.write(",".join(vals) + "\n")
            QMessageBox.information(self, "导出完成", "已导出 %d 行:\n%s" % (self.tb.rowCount(), path))
        except Exception as e:                                               # noqa: BLE001
            QMessageBox.warning(self, "导出失败", repr(e))

    # ─────────────────── 经典视图切换 ───────────────────
    def _toggle_classic(self):
        cb = getattr(self.main, "_canoe_classic_cb", None)
        if cb:
            cb(self.btn_classic.isChecked())

    # ─────────────────── 数据刷新 ───────────────────
    def reload(self, force_tree=False):
        # 🐛 2026-09-29 老倪「全局数据空间怎么卡住了」真根因: 1s 定时器**无条件**重建 500 行×9 列的表
        #   (每轮 4500 个 QTableWidgetItem + 整页重排) ⇒ 进程 CPU 实测 81.7%, 页面像冻住。
        #   修法三条: ①不在看的页直接不刷新 ②trace 没变(体积+mtime)就整轮跳过 ③行数 500→150。
        if not self.isVisible():
            return
        try:
            self._live = _j(LIVE, {}) or {}
            self._loop = _j(LOOP, {}) or {}
            if force_tree or self.tree.topLevelItemCount() == 0:
                if not self._busdb:
                    self._busdb = _j(BUSDB, {})
                self._fill_tree()
            self._update_values()
            if self._sel_obj is None and self.tree.topLevelItemCount():
                _root = self.tree.topLevelItem(0)
                if _root is not None and _root.childCount():
                    _it = _root.child(0)
                    self.tree.setCurrentItem(_it)          # 默认选中第一条报文(详情面板立刻有内容)
                    _d = _it.data(0, Qt.UserRole)
                    if _d:
                        self._sel_kind, self._sel_obj = _d
                        self._it_default = _it
            self._fill_measure_bar()
            if not self.btn_pause.isChecked():
                self._fill_trace(force=bool(force_tree))
            self._fill_loop()
            self._fill_alerts()
            if self._sel_obj:
                self._fill_detail()
        except Exception as e:                                               # noqa: BLE001
            import traceback
            self.detail.setText("⚠ 刷新异常: %r\n%s" % (e, traceback.format_exc()[-800:]))

    def _topics(self):
        return (self._live or {}).get("topics") or {}

    def _read_trace(self, n=300):
        rows = []
        if os.path.exists(TRACE):
            try:
                with open(TRACE, "rb") as f:      # 有界读: 只取尾部 256KB(文件长大也不会拖慢)
                    f.seek(0, os.SEEK_END)
                    f.seek(max(0, f.tell() - 262144))
                    _tail = f.read().decode("utf-8", "replace").splitlines()
                for ln in _tail[-n:]:
                        ln = ln.strip()
                        if not ln:
                            continue
                        try:
                            rows.append(json.loads(ln))
                        except Exception:                                    # noqa: BLE001
                            continue
            except Exception:                                                # noqa: BLE001
                rows = []
        return rows

    def _last_frame(self):
        """每话题最后一帧时刻 → Data 表 Last Value Time 列"""
        out = {}
        for rec in self._trace_rows[-600:]:
            t = rec.get("topic")
            if not t:
                continue
            out[t] = rec.get("t")                       # 全路径 zmax/xxx
            out[str(t).split("/")[-1]] = rec.get("t")   # 🐛 短名 xxx —— live.json 的键是短名(质检: 整列 '—')
        return out

    def _fill_tree(self):
        """CANoe 的 Symbols 树: 报文(话题) → 信号(画布连线, 按层) → 节点(按层)"""
        self.tree.clear()
        db = self._busdb or {}
        topics = self._topics()
        only_alive = bool(self.chk_only_alive.isChecked())
        f_tr = QFont(UI, 10, QFont.Bold)

        msgs = db.get("messages") or {}
        root_m = QTreeWidgetItem(["🚌 报文 (Messages %d)" % len(msgs), "", "", "", ""])
        root_m.setFont(0, f_tr)
        root_m.setForeground(0, QColor(C_BLUE))
        self.tree.addTopLevelItem(root_m)
        for key in sorted(msgs):
            m = msgs[key] or {}
            if only_alive and not topics.get(key):
                continue
            it = QTreeWidgetItem([str(m.get("topic", key)), "", "", "", ""])
            it.setData(0, Qt.UserRole, ("topic", key))
            it.setFont(0, QFont(MONO, 10))
            it.setToolTip(0, "类型 %s · 设计 %.2fHz · QoS %s\n生产者 %s" % (
                m.get("type", "—"), float(m.get("hz_design") or 0), m.get("qos", "—"), m.get("producer", "—")))
            root_m.addChild(it)
        root_m.setExpanded(True)

        sigs = db.get("signals") or []
        by_layer = {}
        for s in sigs:
            by_layer.setdefault(s.get("layer") or "meta", []).append(s)
        root_s = QTreeWidgetItem(["🔗 信号 (画布连线 %d)" % len(sigs), "", "", "", ""])
        root_s.setFont(0, f_tr)
        root_s.setForeground(0, QColor(C_GREEN))
        self.tree.addTopLevelItem(root_s)
        order = ["L5", "L4", "L3", "L2", "meta"]
        for ly in [x for x in order if x in by_layer] + [x for x in sorted(by_layer) if x not in order]:
            items = by_layer[ly]
            lyr = QTreeWidgetItem(["%s  层内信号 %d" % (ly, len(items)), "", "", "", ""])
            lyr.setFont(0, QFont(UI, 10, QFont.Bold))
            lyr.setForeground(0, QColor(LV_COLOR.get(ly, C_GRAY)))
            root_s.addChild(lyr)
            for s in items:
                name = "%s → %s" % (str(s.get("src_name", s.get("src", "?")))[:30],
                                    str(s.get("dst_name", s.get("dst", "?")))[:30])
                it = QTreeWidgetItem(["%s  %s" % (s.get("sid", "?"), name), "", "", "", ""])
                it.setData(0, Qt.UserRole, ("signal", s.get("sid")))
                it.setToolTip(0, "连线 %s · 端口 %s→%s\n标签 %s\n话题 %s" % (
                    s.get("link_id", "—"), s.get("src_port", "?"), s.get("dst_port", "?"),
                    s.get("label", "—"), s.get("topic", "—")))
                lyr.addChild(it)
        root_s.setExpanded(False)

        nodes = db.get("nodes") or {}
        by_ly = {}
        for nid, n in nodes.items():
            by_ly.setdefault(n.get("layer") or "meta", []).append((nid, n))
        root_n = QTreeWidgetItem(["🧩 节点 (Nodes %d)" % len(nodes), "", "", "", ""])
        root_n.setFont(0, f_tr)
        root_n.setForeground(0, QColor(C_PURPLE))
        self.tree.addTopLevelItem(root_n)
        for ly in [x for x in order if x in by_ly] + [x for x in sorted(by_ly) if x not in order]:
            lyr = QTreeWidgetItem(["%s  节点 %d" % (ly, len(by_ly[ly])), "", "", "", ""])
            lyr.setFont(0, QFont(UI, 10, QFont.Bold))
            lyr.setForeground(0, QColor(LV_COLOR.get(ly, C_GRAY)))
            root_n.addChild(lyr)
            for nid, n in sorted(by_ly[ly], key=lambda x: x[0]):
                it = QTreeWidgetItem(["%s %s" % (n.get("icon", ""), n.get("name", nid)), "", "", "",
                                      "tx%d rx%d" % (n.get("tx", 0), n.get("rx", 0))])
                it.setData(0, Qt.UserRole, ("node", nid))
                it.setToolTip(0, "id %s · 类型 %s · 画布坐标 (%s,%s)" % (
                    nid, n.get("type", "—"), n.get("x"), n.get("y")))
                lyr.addChild(it)
        root_n.setExpanded(False)

    def _update_values(self):
        if not self._trace_rows:                   # 🐛 质检: Last Value Time 整列 '—' —— 首刷顺序问题
            self._trace_rows = self._read_trace()  #   (值更新早于 trace 读取) ⇒ 这里补读一次
        """Data 表: Value=实测 Hz · Unit=Hz · Last Value Time=该话题最后一帧 · Bar=实测/设计(CANoe 实心蓝条)"""
        topics = self._topics()
        last = self._last_frame()
        root_m = self.tree.topLevelItem(0)
        if root_m is None:
            return
        for i in range(root_m.childCount()):
            it = root_m.child(i)
            data = it.data(0, Qt.UserRole)
            if not data:
                continue
            _, key = data
            t = topics.get(key) or {}
            m = ((self._busdb.get("messages") or {}).get(key) or {})
            hz_d = float(m.get("hz_design") or 0) or 0.0
            if not t:
                it.setText(1, "—")
                it.setText(2, "Hz")
                it.setText(3, "—")
                it.setText(4, "")
                it.setData(4, Qt.UserRole, -1.0)
                it.setForeground(1, QColor(C_DIM))
                it.setForeground(3, QColor(C_DIM))
                continue
            hz = float(t.get("hz") or -1)
            it.setText(1, _num(hz, 2))
            it.setText(2, "Hz")
            tsp = last.get(key)
            if tsp:
                age = time.time() - float(tsp)
                it.setText(3, _num(age, 2) if age >= 0 else "—")
                it.setToolTip(3, "最后一帧 %s" % _hhmmss(tsp))
            else:
                it.setText(3, "—")
                it.setToolTip(3, "本窗口内没抓到该话题的帧")
            ratio = (hz / hz_d) if (hz > 0 and hz_d > 0) else -1.0
            it.setData(4, Qt.UserRole, ratio)
            it.setText(4, "%d%%" % int(min(1.0, ratio) * 100) if ratio > 0 else "")
            it.setForeground(1, QColor(VERDICT_COLOR.get(t.get("verdict", "unknown"), C_WHITE)))
            it.setForeground(3, QColor(C_GRAY))

    def _fill_measure_bar(self):
        live = self._live or {}
        age = time.time() - float(live.get("ts") or 0) if live.get("ts") else None
        self.lb_mode.setText("档位 %s" % (live.get("mode") or "—"))
        self.lb_mode.setToolTip(live.get("mode_desc", ""))
        self.lb_fresh.setText("刷新龄 %s · 拍照 %s" % (
            ("%.1fs" % age) if age is not None else "—", _hhmmss(live.get("ts"))))
        self.lb_msgs.setText("报文 活跃%s/允许%s/注册%s" % (
            live.get("n_topic_alive", "—"), live.get("n_topics_allowed", "—"),
            live.get("n_topics_registered", "—")))
        tally = live.get("lamp_tally") or {}
        txt = "  ".join(f"{LAMP_ICON.get(k, '')}{tally.get(k, 0)}"
                        for k in ("green", "yellow", "red", "black"))
        self.lb_lamps.setText("灯 " + (txt if txt.strip() else "—"))
        st_col = C_GREEN if (age is not None and age < 5) else (C_YELLOW if age is not None and age < 30 else C_RED)
        self.lb_state.setStyleSheet(f"color:{st_col}; background:transparent; border:none;")
        if self._t0:
            el = int(time.time() - self._t0)
            self.lb_clock.setText("%d:%02d:%02d" % (el // 3600, (el % 3600) // 60, el % 60))
        self.lb_stamp.setText("拍照 %s" % _hhmmss(live.get("ts")))
        try:                                    # 中段读数(质检: 顶栏 733px 死区)
            self.lb_mid.setText("Trace %d 行 · 过滤 %s · Δt %s · 帧龄 %s · 闭环 %s"
                                % (self.tb.rowCount(), ("'%s'" % self._filter) if self._filter else "关",
                                   "开" if self._dt_mode else "关",
                                   _num((live.get("topics") or {}).get(
                                       next(iter(self._topics()), ""), {}).get("age_s"), 2, "s"),
                                   "%s/%s" % (sum(1 for s in ((self._loop or {}).get("stages") or [])
                                                  if s.get("status") in ("pass", "ok")),
                                              len(((self._loop or {}).get("stages") or [])))))
        except Exception:                                                       # noqa: BLE001
            pass

    def _trace_sig(self):
        try:
            st = os.stat(TRACE)
            return (st.st_size, int(st.st_mtime))
        except Exception:                                                        # noqa: BLE001
            return None

    def _fill_trace(self, force=False):
        sig = self._trace_sig()
        if not force and sig == getattr(self, "_trace_sig_last", None):
            return self.tb.rowCount()            # 文件没动 ⇒ 不重建(卡顿根因就是这里每秒重建)
        self._trace_sig_last = sig
        rows = self._read_trace()
        if not rows:
            self._trace_rows = []
            self.tb.setRowCount(1)
            self.tb.setItem(0, 0, QTableWidgetItem("—"))
            self.tb.setItem(0, 1, QTableWidgetItem("没有 trace 帧(总线未记录 / trace.jsonl 为空)"))
            return
        self._trace_rows = rows
        if self._t0 is None:
            try:
                self._t0 = min(float(r.get("t") or 0) for r in rows)
            except Exception:                                                # noqa: BLE001
                self._t0 = None
        prev_t = {}
        for r in rows:
            prev_t[r.get("topic")] = r.get("t")
        rows = rows[::-1]                                    # 最新在顶
        if self._filter:
            f = self._filter
            rows = [r for r in rows if f in str(r.get("topic", "")).lower()
                    or f in str(r.get("type", "")).lower()]
        topics = self._topics()
        self.tb.setUpdatesEnabled(False)
        self.tb.setRowCount(min(len(rows), 150))
        for r, rec in enumerate(rows[:150]):
            topic = str(rec.get("topic", "?"))
            key = topic.split("/")[-1]
            live_t = topics.get(key) or topics.get(topic) or {}
            try:
                t = float(rec.get("t") or 0)
            except Exception:                                                # noqa: BLE001
                t = 0.0
            if self._dt_mode:
                p = prev_t.get(topic)
                tt = _num(t - float(p), 3) if p and float(p) < t else "—"
            else:
                tt = _rel(self._t0, t)
            score = live_t.get("score")
            cells = [
                tt,
                topic,
                str(rec.get("type", "—")),
                str(live_t.get("verdict", "—")),
                _num(score * 100 if isinstance(score, (int, float)) and score >= 0 else -1, 1)
                if score is not None else "—",
                str(live_t.get("producer") or live_t.get("source")
                    or ((self._busdb.get("messages") or {}).get(key) or {}).get("producer")
                    or "—")[:24],
                str(((self._busdb.get("messages") or {}).get(key) or {}).get("sender")
                    or live_t.get("publisher") or key or "—")[:22],
                str(rec.get("n", "—")),
                str(live_t.get("qos") or "—"),
            ]
            for c, txt in enumerate(cells):
                item = QTableWidgetItem(str(txt))
                item.setFont(QFont(MONO if c in (0, 1, 5, 7) else UI, 10))
                if c == 0:
                    item.setForeground(QColor(C_BLUE))
                elif c == 1:
                    item.setToolTip(topic)
                elif c == 4:
                    try:
                        v = float(score) * 100
                        item.setForeground(QColor(C_GREEN if v >= 99 else C_YELLOW if v > 0 else C_GRAY))
                    except Exception:                                        # noqa: BLE001
                        pass
                if r % 2:                                              # 质检: 整行变灰让半张表"褪色" ⇒ 改浅底斑马纹
                    item.setBackground(QColor("#12171e"))
                self.tb.setItem(r, c, item)
        self.tb.setUpdatesEnabled(True)

    def _fill_loop(self):
        stages = (self._loop or {}).get("stages") or []
        self.tb_loop.setRowCount(len(stages))
        for i, s in enumerate(stages):
            st = s.get("status", "unknown")
            cells = [s.get("id", "—"), s.get("name", "—"), s.get("gate", "—"), s.get("owner", "—"),
                     "%s %s" % (st, s.get("evidence", ""))]
            for c, txt in enumerate(cells):
                item = QTableWidgetItem(str(txt)[:300])
                if c == 4:
                    item.setForeground(QColor(VERDICT_COLOR.get(st, C_GRAY)))
                elif c == 0:
                    item.setForeground(QColor(C_BLUE))
                    item.setFont(QFont(MONO, 9, QFont.Bold))
                if c == 2:
                    item.setToolTip(str(txt))
                self.tb_loop.setItem(i, c, item)

    def _fill_alerts(self):
        alerts = []
        for key, t in (self._topics() or {}).items():
            for r in (t.get("rules") or []):
                if not r.get("ok"):
                    alerts.append((r.get("level", "warn"), t.get("topic", key),
                                   "%s: %s" % (r.get("rule", "—"), r.get("msg", ""))))
        seen, uniq = set(), []
        for a in alerts:                                                       # 质检: 同一规则+同文本重复出现 ⇒ 去重
            k = (a[0], a[1], a[2])
            if k not in seen:
                seen.add(k)
                uniq.append(a)
        alerts = uniq
        rank = {"fail": 0, "error": 0, "warn": 1, "unknown": 2}
        alerts.sort(key=lambda a: rank.get(a[0], 9))
        self.tb_alert.setRowCount(len(alerts))
        for i, (lvl, obj, msg) in enumerate(alerts):
            icon = {"fail": "🔴", "error": "🔴", "warn": "🟡"}.get(lvl, "⚪")
            col = {"fail": C_RED, "error": C_RED, "warn": C_YELLOW}.get(lvl, C_GRAY)
            for c, txt in enumerate([f"{icon} {lvl}", obj, msg]):
                item = QTableWidgetItem(str(txt)[:300])
                if c == 0:
                    item.setForeground(QColor(col))
                if c == 1:
                    item.setFont(QFont(MONO, 9))
                self.tb_alert.setItem(i, c, item)
        self._btns["alert"].setText("⚠ 质量告警 (%d)" % len(alerts))

    # ─────────────────── 选中 → 详情 ───────────────────
    def _on_tree_click(self, it, _col):
        data = it.data(0, Qt.UserRole)
        if not data:
            return
        self._sel_kind, self._sel_obj = data
        self._fill_detail()

    def _on_trace_click(self, it):
        top = self.tb.item(it.row(), 1)
        if top is not None:
            self._sel_kind, self._sel_obj = "topic", top.text()
            self._fill_detail()

    def _detail_text(self):
        if not self._sel_obj:
            return "点左侧 Data 表 或 Trace 任意一行 → 这里显示该对象的完整属性与质量判据(逐条)。"
        kind, key = self._sel_kind, self._sel_obj
        topics, db = self._topics(), (self._busdb or {})
        out = []
        if kind == "topic":
            t = topics.get(key) or {}
            m = (db.get("messages") or {}).get(key) or {}
            lamp_txt = "%s %s" % (LAMP_ICON.get(t.get("lamp") or "", "—"),
                                  t.get("lamp_reason") or "")
            out += ["🚌 报文  %s" % (t.get("topic") or m.get("topic") or key),
                    "─" * 52,
                    _pad("类型", 14) + str(t.get("type") or m.get("type", "—")),
                    _pad("QoS", 14) + str(t.get("qos") or m.get("qos", "—")),
                    _pad("设计频率", 14) + _num(t.get("hz_design") or m.get("hz_design"), 2, " Hz"),
                    _pad("实测频率", 14) + _num(t.get("hz"), 2, " Hz"),
                    _pad("抖动", 14) + _num(t.get("jitter_ms"), 2, " ms"),
                    _pad("丢包", 14) + _num(t.get("loss_pct"), 1, " %"),
                    _pad("帧龄", 14) + _num(t.get("age_s"), 2, " s"),
                    _pad("累计报文", 14) + str(t.get("count", "—")),
                    _pad("字节", 14) + str(t.get("bytes", "—")),
                    _pad("匹配发布者", 14) + str(t.get("matched_pubs", "—")),
                    _pad("质量判决", 14) + "%s (score %s)" % (t.get("verdict", "—"), _num(t.get("score"), 2)),
                    _pad("灯", 14) + lamp_txt.strip(),
                    _pad("生产者", 14) + str(m.get("producer", "—")),
                    "", "质量判据(逐条)"]
            for r in (t.get("rules") or []):
                out.append("  %s %-12s %s" % ("✔" if r.get("ok") else "✘", r.get("rule", ""), r.get("msg", "")))
            f = t.get("fields") or {}
            if f:
                out += ["", "载荷字段(实测值)"]
                for k in list(f)[:24]:
                    out.append("  " + _pad(k, 18) + str(f[k]))
        elif kind == "signal":
            for s in (db.get("signals") or []):
                if s.get("sid") == key:
                    out += ["🔗 信号  %s  (连线 %s)" % (key, s.get("link_id", "—")), "─" * 52,
                            _pad("来源", 14) + "%s . %s" % (s.get("src"), s.get("src_port", "?")),
                            _pad("", 14) + str(s.get("src_name", "")),
                            _pad("去向", 14) + "%s . %s" % (s.get("dst"), s.get("dst_port", "?")),
                            _pad("", 14) + str(s.get("dst_name", "")),
                            _pad("标签", 14) + str(s.get("label", "—")),
                            _pad("层级", 14) + str(s.get("layer", "—")),
                            _pad("话题", 14) + str(s.get("topic", "—"))]
                    break
        else:
            n = (db.get("nodes") or {}).get(key) or {}
            out += ["🧩 节点  %s" % key, "─" * 52,
                    _pad("名称", 14) + str(n.get("name", "—")),
                    _pad("类型", 14) + str(n.get("type", "—")),
                    _pad("层级", 14) + str(n.get("layer", "—")),
                    _pad("画布坐标", 14) + "(%s, %s)" % (n.get("x"), n.get("y")),
                    _pad("出/入线数", 14) + "tx %s / rx %s" % (n.get("tx", 0), n.get("rx", 0))]
        return "\n".join(out)

    def _fill_detail(self):
        self.detail.setText(self._detail_text())

    def copy_detail(self):
        try:
            QGuiApplication.clipboard().setText(self._detail_text())
            self.detail.setToolTip("已复制到剪贴板")
        except Exception:                                                    # noqa: BLE001
            pass


def build_view(main_win=None) -> QWidget:
    return BusView(main_win=main_win)
