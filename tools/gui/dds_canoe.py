#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🌐 全局数据空间 —— CANoe 风格重做 (2026-09-29 老倪: 「参考 Vector CANoe demo 重新设计 UI」)

设计口径(照 CANoe 主窗口的多窗格范式, 而不是"12 个 Tab 堆叠"):
  ┌ 测量条 ───────────────────────────────────────────────────────────────┐
  │ ●测量状态 | 档位 | 刷新龄/拍照时间 | 报文 注册/允许/活跃 | 灯 🟢🟡🔴⚫ | 记录/刷新/导出/经典视图 │
  ├ 信号浏览器 ──┬ Trace (报文/信号) ──────────────┬ 详情 (选中信号的属性+质量判据) ─┤
  │ 报文(14)     │ 时刻 报文 类型 序号 字节 载荷摘要 │ topic/type/QoS/Hz/丢包/帧龄/rules │
  │ 信号(182)    │ …值变化行高亮, 新帧在顶…        │ 双击可复制                        │
  │ 节点(74)     │                                   │                                   │
  ├ 数据闭环 S0..S5 ─────────────────────┬ ⚠ 质量告警(红/黄/黑) ─────────────────────┤
  └───────────────────────────────────────┴────────────────────────────────────────────┘

数据源(全部真实, 不造假):
  busdb.json   画布导出的 DBC(节点/信号/报文)   live.json  每话题质量(hz/丢包/jitter/帧龄/规则/灯)
  trace.jsonl  总线帧流(topic/type/序号/字节/载荷)  loop.json 数据闭环阶段(门/owner/证据)
规矩: 缺测 = -1.0 显示 "—"; 实时量一律带帧龄/拍照时间; 数值可选中可复制; 页面不许出现横向拉条。
"""
from __future__ import annotations

import copy
import json
import os
import time

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QGuiApplication
from PyQt5.QtWidgets import (QAbstractItemView, QCheckBox, QFrame, QHBoxLayout, QHeaderView, QLabel,
                             QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QTextEdit,
                             QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

# ── 调色板(与控制台主色一致) ──
C_BG, C_BG2, C_CARD, C_BORDER = "#0d1117", "#161b22", "#1c2333", "#30363d"
C_WHITE, C_GRAY, C_DIM, C_BLUE = "#ffffff", "#8b949e", "#484f58", "#58a6ff"
C_GREEN, C_YELLOW, C_RED, C_PURPLE = "#3fb950", "#d29922", "#f85149", "#bc8cff"

DS_DIR = os.environ.get("ZMAX_DATASPACE_DIR", "/home/ubuntu/zmax_data/dataspace")
LIVE = os.path.join(DS_DIR, "live.json")
TRACE = os.path.join(DS_DIR, "trace.jsonl")
LOOP = os.path.join(DS_DIR, "loop.json")
BUSDB = os.path.join(DS_DIR, "busdb.json")

LV_COLOR = {"L5": C_PURPLE, "L4": C_BLUE, "L3": "#2fc4b2", "L2": C_GREEN, "meta": C_GRAY}
VERDICT_COLOR = {"ok": C_GREEN, "pass": C_GREEN, "warn": C_YELLOW, "fail": C_RED,
                 "unknown": C_GRAY, "stale": C_YELLOW}
LAMP_ICON = {"green": "🟢", "yellow": "🟡", "red": "🔴", "black": "⚫"}

MONO = "Consolas"
UI = "Arial"


def _j(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                    # noqa: BLE001
        return default if default is not None else {}


def _blank(v):
    """缺测(-1/-1.0/None/空) → '—' (全空间统一: 不许用 0 冒充)"""
    if v is None or v == "":
        return "—"
    try:
        if isinstance(v, (int, float)) and float(v) < 0:
            return "—"
        if isinstance(v, (int, float)) and float(v) == 0 and v != 0:
            return "—"
    except Exception:                                                    # noqa: BLE001
        pass
    return v


def _num(v, nd=2, suffix=""):
    v = _blank(v)
    if v == "—":
        return "—"
    try:
        return f"{float(v):.{nd}f}{suffix}"
    except Exception:                                                    # noqa: BLE001
        return f"{v}{suffix}"


def _hhmmss(t):
    try:
        return time.strftime("%H:%M:%S", time.localtime(float(t)))
    except Exception:                                                    # noqa: BLE001
        return "—"


class BusView(QWidget):
    """CANoe 风格的多窗格视图: 测量条 + 三段窗格 + 底部两栏。"""

    def __init__(self, main_win=None, parent=None):
        super().__init__(parent)
        self.main = main_win
        self._busdb = _j(BUSDB, {})
        self._live = {}
        self._loop = {}
        self._trace_rows = []
        self._sel_topic = None
        self._sel_kind = None
        self._sig_values = {}
        self._last_trace_n = 0
        self.setObjectName("DdsCanoeView")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"#DdsCanoeView {{ background:{C_BG}; }}")
        self._build()
        self.reload(force_tree=True)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.reload)
        self._timer.start(1000)

    # ────────────────────────── 构建 ──────────────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)
        root.addWidget(self._build_measure_bar())

        vsplit = QSplitter(Qt.Vertical)
        vsplit.setChildrenCollapsible(False)
        hsplit = QSplitter(Qt.Horizontal)
        hsplit.setChildrenCollapsible(False)
        hsplit.addWidget(self._build_tree())
        hsplit.addWidget(self._build_trace())
        hsplit.addWidget(self._build_detail())
        hsplit.setStretchFactor(0, 0)
        hsplit.setStretchFactor(1, 3)
        hsplit.setStretchFactor(2, 0)
        hsplit.setSizes([420, 1200, 400])
        vsplit.addWidget(hsplit)
        vsplit.addWidget(self._build_bottom())
        vsplit.setStretchFactor(0, 3)
        vsplit.setStretchFactor(1, 1)
        vsplit.setSizes([1250, 330])
        root.addWidget(vsplit, 1)

    def _panel(self, title, color=C_BLUE, extra=None):
        """带标题的面板(所有窗格统一外观)"""
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
        if extra is not None:
            head.addWidget(extra)
        lay.addLayout(head)
        return box, lay, head

    def _build_measure_bar(self):
        bar = QFrame()
        bar.setStyleSheet(f"QFrame {{ background:{C_BG2}; border:1px solid {C_BORDER}; border-radius:6px; }}")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(14)

        self.lb_state = QLabel("● 测量")
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

        for w in (self.lb_state, self.lb_mode, self.lb_fresh, self.lb_msgs, self.lb_lamps):
            lay.addWidget(w)
        lay.addStretch()

        def _btn(txt, tip, fn, color=C_WHITE):
            b = QPushButton(txt)
            b.setFont(QFont(UI, 10))
            b.setToolTip(tip)
            b.setStyleSheet(f"QPushButton {{ background:{C_CARD}; color:{color}; border:1px solid {C_BORDER};"
                            f" border-radius:4px; padding:5px 12px; }}"
                            f"QPushButton:hover {{ border-color:{C_BLUE}; color:{C_WHITE}; }}")
            b.clicked.connect(fn)
            return b

        self.btn_rec = QPushButton("⏺ 记录")
        self.btn_rec.setCheckable(True)
        self.btn_rec.setFont(QFont(UI, 10))
        self.btn_rec.setToolTip("暂停/恢复 Trace 滚动(测量条那把「开始/停止」)")
        self.btn_rec.setStyleSheet(f"QPushButton {{ background:{C_CARD}; color:{C_GREEN}; border:1px solid {C_BORDER};"
                                   f" border-radius:4px; padding:5px 12px; }}"
                                   f"QPushButton:checked {{ background:#3a1d1d; color:{C_RED}; border-color:{C_RED}; }}")
        lay.addWidget(self.btn_rec)
        lay.addWidget(_btn("🔄 刷新", "立刻重读 live.json / trace.jsonl", lambda: self.reload(force_tree=True)))
        lay.addWidget(_btn("📤 导出 CSV", "导出 Trace 表(可复制/可导入 Excel)", self.export_trace))
        lay.addWidget(_btn("📋 复制详情", "复制右侧详情文本", self.copy_detail))
        self.btn_classic = QPushButton("🗂 经典视图")
        self.btn_classic.setCheckable(True)
        self.btn_classic.setFont(QFont(UI, 10))
        self.btn_classic.setToolTip("切回原来的 12 个 Tab 视图(旧入口不丢)")
        self.btn_classic.setStyleSheet(f"QPushButton {{ background:{C_CARD}; color:{C_GRAY}; border:1px solid {C_BORDER};"
                                       f" border-radius:4px; padding:5px 12px; }}"
                                       f"QPushButton:checked {{ color:{C_BLUE}; border-color:{C_BLUE}; }}")
        self.btn_classic.clicked.connect(self._toggle_classic)
        lay.addWidget(self.btn_classic)
        return bar

    def _build_tree(self):
        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["名称 / 信号", "值", "单位", "质量"])
        self.tree.setStyleSheet(
            f"QTreeWidget {{ background:{C_BG}; color:{C_WHITE}; border:none; font-family:{UI}; font-size:10pt; }}"
            f"QTreeWidget::item {{ padding:3px 2px; }}"
            f"QTreeWidget::item:selected {{ background:#2a3644; }}"
            f"QHeaderView::section {{ background:{C_CARD}; color:{C_GRAY}; border:none; padding:4px; }}")
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(False)
        h = self.tree.header()
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in (1, 2, 3):
            h.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.itemClicked.connect(self._on_tree_click)
        box, lay, _ = self._panel("🔌 信号浏览器 (报文/信号/节点)", C_BLUE)
        lay.addWidget(self.tree, 1)
        return box

    def _build_trace(self):
        self.tb = QTableWidget(0, 7)
        self.tb.setHorizontalHeaderLabels(["时刻", "报文", "类型", "序号", "字节", "值/载荷摘要", "方向"])
        self.tb.setStyleSheet(
            f"QTableWidget {{ background:{C_BG}; color:{C_WHITE}; border:none; gridline-color:#21262d;"
            f" font-family:{MONO}; font-size:10pt; }}"
            f"QTableWidget::item {{ padding:2px 6px; }}"
            f"QTableWidget::item:selected {{ background:#2a3644; color:{C_WHITE}; }}"
            f"QHeaderView::section {{ background:{C_CARD}; color:{C_GRAY}; border:none; padding:4px;"
            f" font-family:{UI}; }}")
        self.tb.verticalHeader().setVisible(False)
        self.tb.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tb.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tb.setShowGrid(True)
        h = self.tb.horizontalHeader()
        for i in range(7):
            h.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(5, QHeaderView.Stretch)
        self.tb.itemClicked.connect(self._on_trace_click)
        box, lay, _ = self._panel("📋 Trace — 总线帧流 (最新在顶)", C_GREEN)
        lay.addWidget(self.tb, 1)
        return box

    def _build_detail(self):
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setFont(QFont(MONO, 10))
        self.detail.setStyleSheet(f"QTextEdit {{ background:{C_BG}; color:{C_WHITE}; border:none; }}")
        self.detail.setText("点左侧信号浏览器 或 Trace 任意一行 → 这里显示该对象的完整属性与质量判据。")
        box, lay, _ = self._panel("🔎 详情 (选中对象)", C_YELLOW)
        lay.addWidget(self.detail, 1)
        return box

    def _build_bottom(self):
        wrap = QWidget()
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        # 数据闭环阶段
        self.tb_loop = QTableWidget(0, 5)
        self.tb_loop.setHorizontalHeaderLabels(["阶段", "名称", "质量门 (gate)", "owner", "状态/证据"])
        self.tb_loop.setStyleSheet(
            f"QTableWidget {{ background:{C_BG}; color:{C_WHITE}; border:none; gridline-color:#21262d;"
            f" font-family:{UI}; font-size:9pt; }}"
            f"QTableWidget::item {{ padding:2px 6px; }}"
            f"QHeaderView::section {{ background:{C_CARD}; color:{C_GRAY}; border:none; padding:4px; }}")
        self.tb_loop.verticalHeader().setVisible(False)
        self.tb_loop.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tb_loop.setSelectionBehavior(QAbstractItemView.SelectRows)
        lh = self.tb_loop.horizontalHeader()
        for i in (0, 1, 3):
            lh.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        lh.setSectionResizeMode(2, QHeaderView.Interactive)
        lh.setSectionResizeMode(4, QHeaderView.Stretch)
        box1, lay1, _ = self._panel("🔁 数据闭环 (环节 → 质量门 → 证据)", "#2fc4b2")
        lay1.addWidget(self.tb_loop, 1)
        box1.setMinimumWidth(560)
        lay.addWidget(box1, 3)

        # 质量告警
        self.tb_alert = QTableWidget(0, 3)
        self.tb_alert.setHorizontalHeaderLabels(["级别", "对象", "问题"])
        self.tb_alert.setStyleSheet(
            f"QTableWidget {{ background:{C_BG}; color:{C_WHITE}; border:none; gridline-color:#21262d;"
            f" font-family:{UI}; font-size:9pt; }}"
            f"QTableWidget::item {{ padding:2px 6px; }}"
            f"QHeaderView::section {{ background:{C_CARD}; color:{C_GRAY}; border:none; padding:4px; }}")
        self.tb_alert.verticalHeader().setVisible(False)
        self.tb_alert.setEditTriggers(QAbstractItemView.NoEditTriggers)
        ah = self.tb_alert.horizontalHeader()
        ah.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        ah.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        ah.setSectionResizeMode(2, QHeaderView.Stretch)
        box2, lay2, _ = self._panel("⚠ 质量告警 (规则不过的项)", C_RED)
        lay2.addWidget(self.tb_alert, 1)
        lay.addWidget(box2, 2)
        return wrap

    # ────────────────────────── 经典视图切换 ──────────────────────────
    def _toggle_classic(self):
        cb = getattr(self.main, "_canoe_classic_cb", None)
        if cb:
            cb(self.btn_classic.isChecked())

    # ────────────────────────── 数据刷新 ──────────────────────────
    def reload(self, force_tree=False):
        try:
            self._live = _j(LIVE, {}) or {}
            self._loop = _j(LOOP, {}) or {}
            if force_tree or self.tree.topLevelItemCount() == 0:
                if not self._busdb:
                    self._busdb = _j(BUSDB, {})
                self._fill_tree()
            self._update_values()
            self._fill_measure_bar()
            self._fill_trace()
            self._fill_loop()
            self._fill_alerts()
            if self._sel_topic:
                self._fill_detail()
        except Exception as e:                                               # noqa: BLE001
            import traceback
            self.detail.setText("⚠ 刷新异常: %r\n%s" % (e, traceback.format_exc()[-800:]))

    def _fill_measure_bar(self):
        live = self._live or {}
        age = time.time() - float(live.get("ts") or 0) if live.get("ts") else None
        mode = live.get("mode") or "—"
        n_alive = live.get("n_topic_alive", "—")
        n_all = live.get("n_topics_allowed", "—")
        n_reg = live.get("n_topics_registered", "—")
        self.lb_state.setText("● 测量")
        st_col = C_GREEN if (age is not None and age < 5) else (C_YELLOW if age is not None and age < 30 else C_RED)
        self.lb_state.setStyleSheet(f"color:{st_col}; background:transparent; border:none;")
        self.lb_mode.setText(f"档位 {mode}")
        self.lb_mode.setToolTip(live.get("mode_desc", ""))
        self.lb_fresh.setText("刷新龄 %s · 拍照 %s" % (
            ("%.1fs" % age) if age is not None else "—", _hhmmss(live.get("ts"))))
        self.lb_msgs.setText(f"报文 活跃{n_alive}/允许{n_all}/注册{n_reg}")
        tally = live.get("lamp_tally") or {}
        txt = "  ".join(f"{LAMP_ICON.get(k, '')}{tally.get(k, 0)}" for k in ("green", "yellow", "red", "black"))
        self.lb_lamps.setText("灯 " + (txt if txt.strip() else "—"))

    def _topics(self):
        return (self._live or {}).get("topics") or {}

    def _fill_tree(self):
        """左: 报文(话题) → 信号(画布连线) → 节点(画布节点), 按层分组(CANoe 的 Symbols 树)"""
        self.tree.clear()
        db = self._busdb or {}
        f_tr = QFont(UI, 10, QFont.Bold)
        # ① 报文
        root_m = QTreeWidgetItem(["🚌 报文 (%d)" % len(db.get("messages") or {}), "", "", ""])
        root_m.setFont(0, f_tr)
        root_m.setForeground(0, QColor(C_BLUE))
        self.tree.addTopLevelItem(root_m)
        msgs = db.get("messages") or {}
        for key in sorted(msgs):
            m = msgs[key] or {}
            it = QTreeWidgetItem([f"{m.get('topic', key)}", "", "", ""])
            it.setData(0, Qt.UserRole, ("topic", key))
            it.setFont(0, QFont(MONO, 10))
            it.setToolTip(0, "类型 %s · 设计 %.2fHz · QoS %s\n生产者 %s" % (
                m.get("type", "—"), float(m.get("hz_design") or 0), m.get("qos", "—"), m.get("producer", "—")))
            self.tree.addTopLevelItem(it) if False else root_m.addChild(it)
        # ② 信号(连线)
        sigs = db.get("signals") or []
        by_layer = {}
        for s in sigs:
            by_layer.setdefault(s.get("layer") or "meta", []).append(s)
        root_s = QTreeWidgetItem(["🔗 信号 (画布连线 %d)" % len(sigs), "", "", ""])
        root_s.setFont(0, f_tr)
        root_s.setForeground(0, QColor(C_GREEN))
        self.tree.addTopLevelItem(root_s)
        order = ["L5", "L4", "L3", "L2", "meta"]
        for ly in [x for x in order if x in by_layer] + [x for x in sorted(by_layer) if x not in order]:
            items = by_layer[ly]
            lyr = QTreeWidgetItem(["%s  层内信号 %d" % (ly, len(items)), "", "", ""])
            lyr.setFont(0, QFont(UI, 10, QFont.Bold))
            lyr.setForeground(0, QColor(LV_COLOR.get(ly, C_GRAY)))
            root_s.addChild(lyr)
            for s in items:
                name = "%s → %s" % (str(s.get("src_name", s.get("src", "?")))[:26],
                                    str(s.get("dst_name", s.get("dst", "?")))[:26])
                it = QTreeWidgetItem([f"{s.get('sid', '?')}  {name}", "", "", ""])
                it.setData(0, Qt.UserRole, ("signal", s.get("sid")))
                it.setToolTip(0, "连线 %s · 端口 %s→%s\n标签 %s\n话题 %s" % (
                    s.get("link_id", "—"), s.get("src_port", "?"), s.get("dst_port", "?"),
                    s.get("label", "—"), s.get("topic", "—")))
                lyr.addChild(it)
            if ly != "meta":
                lyr.setExpanded(False)
        root_s.setExpanded(False)
        # ③ 节点
        nodes = db.get("nodes") or {}
        root_n = QTreeWidgetItem(["🧩 节点 (%d)" % len(nodes), "", "", ""])
        root_n.setFont(0, f_tr)
        root_n.setForeground(0, QColor(C_PURPLE))
        self.tree.addTopLevelItem(root_n)
        by_ly = {}
        for nid, n in nodes.items():
            by_ly.setdefault(n.get("layer") or "meta", []).append((nid, n))
        for ly in [x for x in order if x in by_ly] + [x for x in sorted(by_ly) if x not in order]:
            lyr = QTreeWidgetItem(["%s  节点 %d" % (ly, len(by_ly[ly])), "", "", ""])
            lyr.setFont(0, QFont(UI, 10, QFont.Bold))
            lyr.setForeground(0, QColor(LV_COLOR.get(ly, C_GRAY)))
            root_n.addChild(lyr)
            for nid, n in sorted(by_ly[ly], key=lambda x: x[0]):
                it = QTreeWidgetItem([f"{n.get('icon', '')} {n.get('name', nid)}", "", "",
                                      "tx%d rx%d" % (n.get("tx", 0), n.get("rx", 0))])
                it.setData(0, Qt.UserRole, ("node", nid))
                it.setToolTip(0, "id %s · 类型 %s · 画布坐标 (%s,%s)" % (
                    nid, n.get("type", "—"), n.get("x"), n.get("y")))
                lyr.addChild(it)
        root_m.setExpanded(True)
        root_s.setExpanded(True)
        root_n.setExpanded(False)

    def _update_values(self):
        """给树里的「报文」行填实时值(Hz/帧龄/灯)"""
        topics = self._topics()
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
            if not t:
                it.setText(1, "—")
                it.setText(3, "⚫ 无信号")
                it.setForeground(3, QColor(C_DIM))
                continue
            it.setText(1, _num(t.get("hz"), 2, "Hz"))
            it.setText(2, "字节 %s" % t.get("bytes", "—"))
            v = t.get("verdict", "unknown")
            lamp = t.get("lamp") or ("green" if v in ("ok", "pass") else
                                     "yellow" if v == "warn" else "red" if v == "fail" else "black")
            it.setText(3, "%s %s" % (LAMP_ICON.get(lamp, ""), v))
            it.setForeground(3, QColor(VERDICT_COLOR.get(v, C_GRAY)))
            it.setForeground(1, QColor(C_WHITE))

    def _fill_trace(self):
        rows = []
        if os.path.exists(TRACE):
            try:
                with open(TRACE, encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()[-400:]
                for ln in lines:
                    ln = ln.strip()
                    if not ln:
                        continue
                    try:
                        rows.append(json.loads(ln))
                    except Exception:                                        # noqa: BLE001
                        continue
            except Exception:                                                # noqa: BLE001
                rows = []
        if not rows:
            self.tb.setRowCount(1)
            self.tb.setItem(0, 0, QTableWidgetItem("—"))
            self.tb.setItem(0, 5, QTableWidgetItem("没有 trace 帧(总线未记录 / trace.jsonl 为空)"))
            return
        rows = rows[::-1]                     # 最新在顶
        prev_val = {}
        self.tb.setUpdatesEnabled(False)
        self.tb.setRowCount(min(len(rows), 400))
        for r, rec in enumerate(rows[:400]):
            digest = str(rec.get("digest", ""))
            val = digest
            try:
                d = json.loads(digest) if digest.startswith("{") else {}
            except Exception:                                                # noqa: BLE001
                d = {}
            if d:
                if isinstance(d.get("vec"), list) and d["vec"]:
                    val = "vec[%d] = [%s]" % (len(d["vec"]), ", ".join("%.3f" % x for x in d["vec"][:6]))
                elif d.get("joints"):
                    val = "joints = [%s]" % ", ".join("%.3f" % x for x in d["joints"][:6])
                elif "hz" in d:
                    val = "hz=%.2f latency=%s frame_age=%s" % (
                        float(d.get("hz") or -1), _num(d.get("latency_ms"), 1, "ms"), _num(d.get("frame_age_s"), 2, "s"))
                else:
                    val = " ".join("%s=%s" % (k, d[k]) for k in list(d)[:3])
            topic = str(rec.get("topic", "?"))
            cells = [
                _hhmmss(rec.get("t")),
                topic,
                str(rec.get("type", "—")),
                str(rec.get("n", "—")),
                str(rec.get("bytes", "—")),
                val[:220],
                "RX",
            ]
            changed = prev_val.get(topic) != val
            prev_val[topic] = val
            for c, txt in enumerate(cells):
                item = QTableWidgetItem(txt)
                if c in (0, 3, 4, 5):
                    item.setFont(QFont(MONO, 10))
                else:
                    item.setFont(QFont(UI, 10))
                if c == 1:
                    item.setForeground(QColor(C_BLUE))
                elif c == 5 and changed:
                    item.setForeground(QColor(C_YELLOW))          # CANoe 式: 值变化行高亮
                elif r % 2:
                    item.setForeground(QColor(C_GRAY))
                self.tb.setItem(r, c, item)
        self.tb.setUpdatesEnabled(True)

    def _fill_loop(self):
        stages = (self._loop or {}).get("stages") or []
        self.tb_loop.setRowCount(len(stages))
        for i, s in enumerate(stages):
            st = s.get("status", "unknown")
            col = VERDICT_COLOR.get(st, C_GRAY)
            cells = [s.get("id", "—"), s.get("name", "—"), s.get("gate", "—"), s.get("owner", "—"),
                     "%s %s" % (st, s.get("evidence", ""))]
            for c, txt in enumerate(cells):
                item = QTableWidgetItem(str(txt)[:300])
                if c == 4:
                    item.setForeground(QColor(col))
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
                    lvl = r.get("level", "warn")
                    alerts.append((lvl, t.get("topic", key), r.get("rule", "—") + ": " + str(r.get("msg", ""))))
        rank = {"fail": 0, "error": 0, "warn": 1, "unknown": 2, "ok": 3}
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

    # ────────────────────────── 选中 → 详情 ──────────────────────────
    def _on_tree_click(self, it, _col):
        data = it.data(0, Qt.UserRole)
        if not data:
            return
        kind, key = data
        self._sel_kind, self._sel_topic = kind, key
        self._fill_detail()

    def _on_trace_click(self, it):
        row = it.row()
        top = self.tb.item(row, 1)
        if top is not None:
            self._sel_kind, self._sel_topic = "topic", top.text()
            self._fill_detail()

    def _detail_text(self):
        if not self._sel_topic:
            return "点左侧信号浏览器 或 Trace 任意一行 → 这里显示该对象的完整属性与质量判据。"
        kind, key = self._sel_kind, self._sel_topic
        topics = self._topics()
        db = self._busdb or {}
        out = []
        if kind == "topic":
            t = topics.get(key) or {}
            m = (db.get("messages") or {}).get(key) or {}
            out.append("🚌 报文  %s" % (t.get("topic") or m.get("topic") or key))
            out.append("─" * 46)
            out.append("类型        %s" % (t.get("type") or m.get("type", "—")))
            out.append("QoS         %s" % (t.get("qos") or m.get("qos", "—")))
            out.append("设计频率    %s" % _num(t.get("hz_design") or m.get("hz_design"), 2, " Hz"))
            out.append("实测频率    %s" % _num(t.get("hz"), 2, " Hz"))
            out.append("抖动        %s" % _num(t.get("jitter_ms"), 2, " ms"))
            out.append("丢包        %s" % _num(t.get("loss_pct"), 1, " %"))
            out.append("帧龄        %s" % _num(t.get("age_s"), 2, " s"))
            out.append("累计报文    %s" % t.get("count", "—"))
            out.append("字节        %s" % t.get("bytes", "—"))
            out.append("匹配发布者  %s" % t.get("matched_pubs", "—"))
            out.append("允许/在役   %s / %s" % (t.get("allowed", "—"), "—"))
            out.append("质量判决    %s (score %s)" % (t.get("verdict", "—"), _num(t.get("score"), 2)))
            out.append("灯          %s %s" % (LAMP_ICON.get(t.get("lamp"), ""), t.get("lamp_reason", "")))
            out.append("生产者      %s" % m.get("producer", "—"))
            out.append("")
            out.append("质量判据(逐条)")
            for r in (t.get("rules") or []):
                out.append("  %s %-12s %s" % ("✔" if r.get("ok") else "✘", r.get("rule", ""), r.get("msg", "")))
            f = t.get("fields") or {}
            if f:
                out.append("")
                out.append("载荷字段(实测值)")
                for k in list(f)[:24]:
                    out.append("  %-16s %s" % (k, f[k]))
        else:
            sid = key
            sig = None
            for s in (db.get("signals") or []):
                if s.get("sid") == sid:
                    sig = s
                    break
            if sig:
                out.append("🔗 信号  %s  (连线 %s)" % (sid, sig.get("link_id", "—")))
                out.append("─" * 46)
                out.append("来源        %s . %s" % (sig.get("src"), sig.get("src_port", "?")))
                out.append("            %s" % sig.get("src_name", ""))
                out.append("去向        %s . %s" % (sig.get("dst"), sig.get("dst_port", "?")))
                out.append("            %s" % sig.get("dst_name", ""))
                out.append("标签        %s" % sig.get("label", "—"))
                out.append("层级        %s" % sig.get("layer", "—"))
                out.append("话题        %s" % sig.get("topic", "—"))
        return "\n".join(out)

    def _fill_detail(self):
        self.detail.setText(self._detail_text())

    def copy_detail(self):
        try:
            cb = QGuiApplication.clipboard()
            cb.setText(self._detail_text())
            self.detail.setToolTip("已复制到剪贴板")
        except Exception:                                                    # noqa: BLE001
            pass

    def export_trace(self):
        from PyQt5.QtWidgets import QFileDialog, QMessageBox
        path, _ = QFileDialog.getSaveFileName(self, "导出 Trace CSV",
                                              os.path.expanduser("~/zmax_data/dataspace/trace_%s.csv"
                                                                 % time.strftime("%Y%m%d_%H%M%S")),
                                              "CSV (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("时刻,报文,类型,序号,字节,值/载荷摘要,方向\n")
                for r in range(self.tb.rowCount()):
                    vals = []
                    for c in range(self.tb.columnCount()):
                        it = self.tb.item(r, c)
                        v = (it.text() if it else "").replace('"', '""')
                        vals.append('"%s"' % v)
                    f.write(",".join(vals) + "\n")
            QMessageBox.information(self, "导出完成", "已导出 %d 行:\n%s" % (self.tb.rowCount(), path))
        except Exception as e:                                               # noqa: BLE001
            QMessageBox.warning(self, "导出失败", repr(e))


def build_view(main_win=None) -> QWidget:
    return BusView(main_win=main_win)
