#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🚌 DDS 总线控制台 (对标 Vector CANoe) —— 全链路 topic 可视化

老倪 2026-09-29: 「所有的数据都要有 topic; 从状态空间工程开始, 所有节点之间的数据要可视化、
能够被检测、被观察; 量产期间我可以不序列化为 topic, 但工程上我可以随时探测系统, 保证数据质量。
参考 Vector CANoe, 做一个 DDS 总线, 全面检查系统数据; 状态空间工程导出的 json 可以加载到
DDS 总线上, 实现全局数据可视化。」

CANoe 对标:
  Measurement bar → 顶部总线状态条(档位/速率/报文数/错误数/数据龄)
  Topology        → 🚌 总线架构 (报文在总线上 + 74 个画布节点按层挂在总线上)
  Trace           → 📋 报文追踪 (逐条报文, 可暂停/过滤/导出)
  Statistics      → 📊 统计 (实测Hz·抖动·丢包估算·载荷·配对·裁决)
  Symbol/Signal   → 🔌 信号 (报文→层→节点→端口, 182 条连线信号 + 实时值)
  Error frame     → ⚠ 质量告警 (规则不过 + 闭环门)
  Restbus         → 📥 回灌 (把工程 json 发到总线上, 让全图无真机也能被观察)

数据来源(只读, 不自己采数 —— 免得又一处口径):
  live.json   探针 2s 刷新(实测 Hz/帧龄/配对/字段真值)
  trace.jsonl 探针落盘的报文追踪(最近 600 条)
  loop.json   闭环证据采集器 15s
  busdb.json  总线数据库(节点/信号/报文)—— 由画布 json 派生
"""
import csv
import json
import os
import subprocess
import time

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QPainter, QPen, QBrush
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QHeaderView,
                             QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
                             QSplitter, QTabWidget, QTableWidget, QTableWidgetItem, QTreeWidget,
                             QTreeWidgetItem, QVBoxLayout, QWidget)

REPO = os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax_rel")
DS_DIR = os.environ.get("ZMAX_DATASPACE_DIR", "/home/ubuntu/zmax_data/dataspace")
LIVE = os.path.join(DS_DIR, "live.json")
TRACE = os.path.join(DS_DIR, "trace.jsonl")
LOOP = os.path.join(DS_DIR, "loop.json")
BUSDB = os.path.join(DS_DIR, "busdb.json")
MODE_FILE = os.path.expanduser("~/.zmax_telemetry_mode")
DDS_PY = os.path.expanduser("~/dds-venv/bin/python")
BUS_TOOL = os.path.join(REPO, "tools/dds_bus.py")

BG, PANEL, LINE = "#14181e", "#1b2027", "#2b3340"
FG, DIM, ACC = "#d7dde5", "#8b96a5", "#4aa3ff"
OK, WARN, BAD, SILENT = "#39c46e", "#e0a33a", "#e05a5a", "#5a6675"
LV_COLOR = {"L5": "#8f7bff", "L4": "#4aa3ff", "L3": "#2fc4b2", "L2": "#39c46e", "meta": "#8b96a5"}

# 🚦 状态灯四色语义(老倪 2026-09-29): 绿=正常 红=故障 黄=报警 黑=无信号
LAMP = {"green": "#2ecc71", "yellow": "#f1c40f", "red": "#e74c3c", "black": "#000000"}
LAMP_OUT = {"green": "#1b7a45", "yellow": "#8a6d0b", "red": "#8e2a22", "black": "#6b7684"}
LAMP_TXT = {"green": "正常", "yellow": "报警", "red": "故障", "black": "无信号"}
LAMP_ICON = {"green": "🟢", "yellow": "🟡", "red": "🔴", "black": "⚫"}


def _lamps_mod():
    """拿包里那**唯一一份**灯逻辑(纯 python, 无依赖)"""
    try:
        import sys
        if os.path.join(REPO, "src") not in sys.path:
            sys.path.insert(0, os.path.join(REPO, "src"))
        from lerobot.dataspace import lamps as L
        return L
    except Exception:                                                          # noqa: BLE001
        return None


def _lamp_color(st):
    return LAMP.get(st, LAMP["black"])


def _topic_lamp(live, key):
    """取该话题的灯 + 原因; 探针完全没记录 ⇒ 明确说"本档位不发", 别让人以为是故障"""
    ts = (live.get("topics") or {})
    if key not in ts:
        return "black", "本档位不发 / 探针未订阅(非故障)"
    r = ts.get(key) or {}
    return r.get("lamp") or "black", (r.get("lamp_reason") or "")


def _draw_lamp(painter, x, y, r, st, label=False):
    """画一盏灯(黑灯加深灰描边, 免得在深色底上看不见)"""
    from PyQt5.QtCore import QRectF
    painter.setPen(QPen(QColor(LAMP_OUT.get(st, "#6b7684")), 1))
    painter.setBrush(QBrush(QColor(_lamp_color(st))))
    painter.drawEllipse(QRectF(x - r, y - r, 2 * r, 2 * r))
    if label:
        painter.setPen(QColor(FG))
        painter.drawText(int(x + r + 3), int(y + 4), LAMP_TXT.get(st, st))


DARK_QSS = """
QWidget { background:%s; color:%s; }
QTableWidget, QTreeWidget, QPlainTextEdit, QLineEdit, QComboBox, QScrollArea { background:%s; color:%s; }
QTableWidget { gridline-color:%s; }
QHeaderView::section { background:%s; color:%s; border:1px solid %s; padding:4px 6px; font-weight:bold; }
QTableWidget::item:selected, QTreeWidget::item:selected { background:#2a3644; color:#ffffff; }
QCheckBox, QLabel, QPushButton { background:transparent; color:%s; }
QPushButton { background:%s; border:1px solid %s; border-radius:4px; padding:4px 12px; }
QPushButton:hover { border:1px solid %s; }
QLineEdit { border:1px solid %s; border-radius:4px; padding:3px 6px; }
QScrollBar:vertical { background:%s; width:11px; }
QScrollBar::handle:vertical { background:#3a4652; border-radius:5px; }
""" % (BG, FG, BG, FG, LINE, PANEL, ACC, LINE, FG, PANEL, LINE, ACC, LINE, BG)


def _darkify(w):
    """给整棵子树套深色主题(控制台其余页是深色, 这几张表默认是白底=突兀且看不清)"""
    try:
        w.setStyleSheet(DARK_QSS)
    except Exception:                                                          # noqa: BLE001
        pass


def _j(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                          # noqa: BLE001
        return default


def _verdict_color(v):
    return {"ok": OK, "warn": WARN, "violation": BAD, "veto": BAD}.get(v, SILENT)


def _mode():
    try:
        with open(MODE_FILE, encoding="utf-8") as f:
            return (f.read().strip().lower() or "prod")
    except OSError:
        return "prod"


# ─────────────────────────── 🚌 总线架构视图 ───────────────────────────
class BusTopology(QWidget):
    """报文(总线干线) + 节点(按层挂在总线上) —— 一屏看清"谁在发、走哪条报文、谁在收"""\

    def __init__(self, on_pick=None, parent=None):
        super().__init__(parent)
        self.db, self.live = {}, {}
        self._node_lamps = {}
        self.on_pick = on_pick
        self.setMinimumHeight(300)
        self.setMouseTracking(True)
        self._hot = None
        self.setStyleSheet("background:%s" % BG)

    def update_data(self, db, live, node_lamps=None):
        self.db, self.live = db or {}, live or {}
        self._node_lamps = node_lamps or {}
        self.update()

    def _msgs(self):
        msgs = self.db.get("messages") or {}
        return [m for _k, m in sorted(msgs.items(), key=lambda kv: (kv[1]["kind"] != "typed", kv[0]))]

    def mouseMoveEvent(self, e):
        self._hot = self._hit(e.x(), e.y())
        self.setToolTip(self._hot[3] if self._hot else "")
        self.update()

    def mouseReleaseEvent(self, e):
        if self._hot and self.on_pick:
            self.on_pick(self._hot[2])

    def _hit(self, x, y):
        for box in getattr(self, "_boxes", []):
            if box[0] <= x <= box[2] and box[1] <= y <= box[3]:
                return box
        return None

    def paintEvent(self, _e):                                                  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        W, H = self.width(), self.height()
        p.fillRect(0, 0, W, H, QColor(BG))
        msgs = self._msgs()
        if not msgs:
            p.setPen(QColor(DIM)); p.drawText(20, 30, "总线数据库缺失 —— 先跑 tools/dds_bus.py --check 构建")
            return
        # 层带
        bands = [("L5", "L5 战略/意图"), ("L4", "L4 认知/世界模型"), ("L3", "L3 调度"),
                 ("L2", "L2 感知/执行"), ("meta", "meta 基建")]
        top, BH = 86, max(26, int((H - 100) / len(bands)))
        self._boxes = []
        # ── 报文: 总线干线 ──
        busY = 70
        p.setPen(QPen(QColor(DIM), 2)); p.setFont(QFont("Sans", 8))
        p.drawText(14, 11, "DDS 总线: ↑ 报文(话题) / ↓ 各层节点 —— 挂线把报文与节点接到同一条总线上")
        p.setPen(QPen(QColor("#4a5666"), 3))
        p.drawLine(16, busY, W - 14, busY)
        nw = max(58, min(112, int((W - 40) / max(1, len(msgs)))))
        for i, m in enumerate(msgs):
            k = next((x for x, v in (self.db.get("messages") or {}).items() if v is m), "")
            lv = (self.live.get("topics") or {}).get(k) or {}
            lst, _why = _topic_lamp(self.live, k)
            col = QColor(FG if lst == "green" else _lamp_color(lst) if lst in ("red", "yellow") else DIM)
            x = 16 + i * nw
            r = [x, 20, x + nw - 8, busY - 6]
            p.setPen(QPen(QColor(_lamp_color(lst) if lst != "black" else "#6b7684"), 2))
            p.setBrush(QBrush(QColor(PANEL)))
            p.drawRoundedRect(x, 20, nw - 8, busY - 30, 4, 4)
            _draw_lamp(p, x + nw - 16, 28, 4, lst)          # 🚦 报文状态灯
            p.setPen(col); f = QFont("Sans", 7); p.setFont(f)
            name = m["topic"].replace("zmax/", "")
            p.drawText(x + 4, 32, name[:int((nw - 12) / 5.2)])
            p.setPen(QColor(DIM)); p.setFont(QFont("Sans", 7))
            hz = lv.get("hz", -1.0)
            p.drawText(x + 4, 42, ("实测 %.2fHz" % hz) if hz >= 0 else "实测 —")
            p.drawText(x + 4, 52, "设计 %.2fHz" % (m.get("hz_design") or 0))
            ns = m.get("n_signals")
            p.drawText(x + 4, 62, ("%d 信号" % ns) if ns else ("配对%s" % lv.get("matched_pubs", "-")))
            p.setPen(QPen(QColor("#4a5666"), 2)); p.drawLine(x + (nw - 8) // 2, busY - 10, x + (nw - 8) // 2, busY)
            self._boxes.append([r[0], r[1], r[2], r[3], k or m["topic"], 0])
            self._boxes[-1][4] = k or m["topic"]
        # ── 节点: 按层挂 ──
        f = QFont("Sans", 7)
        for bi, (lkey, llabel) in enumerate(bands):
            y = top + bi * BH
            # 该层节点母线 + 从总线干线下来的立管(左), 让"节点挂在总线上"看得见
            p.setPen(QPen(QColor("#3a4652"), 2))
            p.drawLine(12, busY, 12, y - 6)
            p.drawLine(12, y - 6, W - 8, y - 6)
            p.setBrush(QBrush(QColor("#4a5666"))); p.setPen(Qt.NoPen)
            p.drawEllipse(9, y - 9, 6, 6)                       # 干线↔立管 接头
            p.setPen(QColor(LV_COLOR[lkey])); f.setBold(True); p.setFont(f)
            p.drawText(20, y + 9, llabel)
            f.setBold(False); p.setFont(f)
            nodes = [n for n in (self.db.get("nodes") or {}).values() if n["layer"] == lkey]
            per = max(1, int((W - 140) / 158))
            for i, n in enumerate(nodes):
                cx = 120 + (i % per) * 150
                cy = y + 4 + (i // per) * 17
                st = (self._node_lamps or {}).get(n["id"], ("black", "", 0, 0))[0]
                p.setPen(QPen(QColor(_lamp_color(st) if st != "black" else "#6b7684"), 1))
                p.drawLine(cx - 6, y - 6, cx - 6, cy - 8)          # 挂到总线的短接线
                p.setBrush(QBrush(QColor(PANEL)))
                p.drawRect(cx, cy - 9, 150, 14)
                p.setPen(Qt.NoPen); p.setBrush(QBrush(QColor(LV_COLOR[lkey])))
                p.drawRect(cx, cy - 9, 3, 14)                     # 左侧层色条(层归属)
                _draw_lamp(p, cx + 11, cy - 2, 4, st)             # 🚦 模块状态灯
                p.setPen(QColor(FG))
                p.drawText(cx + 19, cy + 2, ("%s ⇢%d ⇠%d" % (n["name"][:14], n["tx"], n["rx"]))[:26])
                self._boxes.append([cx, cy - 9, cx + 150, cy + 5, n["id"], 1])


# ─────────────────────────── 主面板 ───────────────────────────
class BusPanel:
    """把 CANoe 式各窗口作为 Tab 加进调用方给的 QTabWidget(不新建模块卡)"""

    def __init__(self, tabs: QTabWidget, status_hint=None):
        self.tabs = tabs
        self.live, self.loop, self.db = {}, {}, {}
        self.trace = []
        self.paused = False
        self.status_hint = status_hint or (lambda _s: None)
        self._last = 0.0
        self._build()
        self.timer = QTimer()
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    # ---------- 构建 ----------
    def _build(self):
        # ⓪ 🚦 状态灯墙(老倪: 每个模块一个状态灯 · 绿正常/红故障/黄报警/黑无信号)
        t = QWidget(); v = QVBoxLayout(t); v.setContentsMargins(6, 6, 6, 6)
        self.wall = LampWall(on_pick=self._pick_topic)
        v.addWidget(self.wall, 1)
        hint = QLabel("灯的含义: 🟢 正常(规则全过) · 🟡 报警(频率偏低/抖动大/部分信号无) · "
                      "🔴 故障(violation/veto/值域越界) · ⚫ 无信号(本档不发/窗口内 0 条/发布端没起)\n"
                      "口径来自 src/lerobot/dataspace/lamps.py(唯一真源); 数据来自探针 live.json(2s 刷新)")
        hint.setStyleSheet("color:%s;font-size:11px" % DIM)
        v.addWidget(hint)
        _darkify(t)
        self.tabs.addTab(t, "🚦 状态灯")

        # ① 总线架构
        t = QWidget()
        v = QVBoxLayout(t); v.setContentsMargins(6, 6, 6, 6)
        self.topology = BusTopology(on_pick=self._pick_topic)
        v.addWidget(self.topology, 1)
        hint = QLabel("报文(话题)=干线(挂线向下接到各层节点) · 灯的语义: 绿=正常 红=故障 黄=报警 黑=无信号 · "
                      "点报文/节点看详情 · 量产(prod)档位下总线静默是预期行为")
        hint.setStyleSheet("color:%s;font-size:11px" % DIM)
        v.addWidget(hint)
        _darkify(t)
        self.tabs.addTab(t, "🚌 总线架构")

        # ② 报文追踪 Trace
        t = QWidget(); v = QVBoxLayout(t); v.setContentsMargins(6, 6, 6, 6)
        bar = QHBoxLayout()
        self.cb_pause = QCheckBox("暂停"); self.cb_pause.stateChanged.connect(self._on_pause)
        self.ed_filter = QLineEdit(); self.ed_filter.setPlaceholderText("过滤话题/载荷关键字…")
        self.ed_filter.setMaximumWidth(260)
        b_csv = QPushButton("导出 CSV"); b_csv.clicked.connect(self._export_trace)
        b_clr = QPushButton("清屏"); b_clr.clicked.connect(lambda: (self.trace.clear(), self._fill_trace()))
        for w in (self.cb_pause, QLabel("过滤:"), self.ed_filter, b_csv, b_clr):
            bar.addWidget(w)
        bar.addStretch(1)
        v.addLayout(bar)
        self.tb_trace = QTableWidget(0, 6)
        self.tb_trace.setHorizontalHeaderLabels(["时刻(相对s)", "报文(话题)", "类型", "序号", "字节", "载荷摘要"])
        hh = self.tb_trace.horizontalHeader()
        for i, wd in ((0, 92), (1, 210), (2, 110), (3, 70), (4, 70)):
            hh.setSectionResizeMode(i, QHeaderView.Interactive)
            self.tb_trace.setColumnWidth(i, wd)
        hh.setSectionResizeMode(5, QHeaderView.Stretch)
        self.tb_trace.verticalHeader().setVisible(False)
        self.lbl_tr_n = QLabel("—")
        self.lbl_tr_n.setStyleSheet("color:%s;font-size:11px" % DIM)
        v.addWidget(self.lbl_tr_n)
        v.addWidget(self.tb_trace, 1)
        _darkify(t)
        self.tabs.addTab(t, "📋 报文追踪")

        # ③ 统计
        t = QWidget(); v = QVBoxLayout(t); v.setContentsMargins(6, 6, 6, 6)
        bar = QHBoxLayout()
        b_csv = QPushButton("导出 CSV"); b_csv.clicked.connect(self._export_stats)
        bar.addWidget(b_csv); bar.addStretch(1)
        v.addLayout(bar)
        cols = ["状态灯", "报文(话题)", "类型", "信号数", "设计Hz", "实测Hz", "条数",
                "抖动ms", "丢包%", "载荷B", "配对", "裁决"]
        self.tb_stat = QTableWidget(0, len(cols))
        self.tb_stat.setHorizontalHeaderLabels(cols)
        self.lbl_st_n = QLabel("—")
        hh = self.tb_stat.horizontalHeader()
        for i, wd in ((0, 76), (1, 210), (2, 110), (3, 62), (4, 68), (5, 68), (6, 62),
                      (7, 70), (8, 64), (9, 72), (10, 52), (11, 72)):
            hh.setSectionResizeMode(i, QHeaderView.Interactive)
            self.tb_stat.setColumnWidth(i, wd)
        hh.setSectionResizeMode(11, QHeaderView.Stretch)
        self.tb_stat.verticalHeader().setVisible(False)
        v.addWidget(self.lbl_st_n)
        v.addWidget(self.tb_stat, 1)
        _darkify(t)
        self.tabs.addTab(t, "📊 统计")

        # ④ 信号(报文→层→节点→端口)
        t = QWidget(); v = QVBoxLayout(t); v.setContentsMargins(6, 6, 6, 6)
        bar = QHBoxLayout()
        self.ed_sig = QLineEdit(); self.ed_sig.setPlaceholderText("搜节点/端口…"); self.ed_sig.setMaximumWidth(220)
        self.ed_sig.textChanged.connect(self._fill_signals)
        b_exp = QPushButton("导出信号表 CSV"); b_exp.clicked.connect(self._export_signals)
        bar.addWidget(QLabel("搜索:")); bar.addWidget(self.ed_sig); bar.addWidget(b_exp); bar.addStretch(1)
        v.addLayout(bar)
        self.tr_sig = QTreeWidget()
        self.tr_sig.setHeaderLabels(["报文 / 层 / 节点 / 端口   (信号方向: 源→目标)", "信号", "实时值"])
        self.tr_sig.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tr_sig.header().setSectionResizeMode(1, QHeaderView.Interactive)
        self.tr_sig.header().setSectionResizeMode(2, QHeaderView.Interactive)
        self.tr_sig.setColumnWidth(1, 90)
        self.tr_sig.setColumnWidth(2, 300)
        self.tr_sig.setWordWrap(False)
        self.lbl_sg_n = QLabel("—")
        self.lbl_sg_n.setStyleSheet("color:%s;font-size:11px" % DIM)
        v.addWidget(self.lbl_sg_n)
        v.addWidget(self.tr_sig, 1)
        _darkify(t)
        self.tabs.addTab(t, "🔌 信号")

        # ⑤ 质量
        t = QWidget(); v = QVBoxLayout(t); v.setContentsMargins(6, 6, 6, 6)
        self.tx_qual = QPlainTextEdit(); self.tx_qual.setReadOnly(True)
        self.tx_qual.setStyleSheet("font-family:monospace;font-size:11px;background:%s;color:%s" % (BG, FG))
        v.addWidget(self.tx_qual, 1)
        _darkify(t)
        self.tabs.addTab(t, "⚠ 质量告警")

        # ⑥ 回灌 (Restbus)
        t = QWidget(); v = QVBoxLayout(t); v.setContentsMargins(8, 8, 8, 8)
        info = QLabel(
            "📥 工程回灌 (Restbus): 把『状态空间工程导出的 json』里的连线数据发到 DDS 总线上,\n"
            "这样没有真机 / 量产不序列化时, 全图数据依然可被观察、被检查。\n"
            "口径: 回灌报文 kind='bus-sim' text 写明『工程回灌·非实测』—— 与真机实测必须区分。\n"
            "要求: 档位非 prod(量产档不序列化是预期行为)。")
        info.setStyleSheet("color:%s;font-size:11px" % FG)
        v.addWidget(info)
        bar = QHBoxLayout()
        b1 = QPushButton("🚌 回灌一次(182 信号)"); b1.clicked.connect(lambda: self._replay(once=True))
        b2 = QPushButton("▶ 持续回灌(2Hz)"); b2.clicked.connect(lambda: self._replay(once=False))
        b3 = QPushButton("⏹ 停止"); b3.clicked.connect(self._stop_replay)
        for b in (b1, b2, b3):
            bar.addWidget(b)
        bar.addStretch(1)
        v.addLayout(bar)
        self.tx_replay = QPlainTextEdit(); self.tx_replay.setReadOnly(True)
        self.tx_replay.setStyleSheet("font-family:monospace;font-size:11px;background:%s;color:%s" % (BG, FG))
        v.addWidget(self.tx_replay, 1)
        _darkify(t)
        self.tabs.addTab(t, "📥 回灌")
        self._proc = None

    # ---------- 刷新 ----------
    def refresh(self):
        try:
            self._refresh()
        except Exception as e:                                                   # noqa: BLE001
            import traceback
            try:
                self.tx_qual.appendPlainText("⚠ 刷新异常: %s\n%s" % (e, traceback.format_exc()[-300:]))
            except Exception:                                                    # noqa: BLE001
                pass

    def _refresh(self):
        self.live = _j(LIVE, {}) or {}
        self.loop = _j(LOOP, {}) or {}
        if not self.db:
            self.db = _j(BUSDB, {}) or {}
        if not self.paused:
            self._load_trace()
            self._fill_trace()
        if self.db and not getattr(self.wall, "_cards", None):
            self.wall._place(self.db)
        self.node_lamps = self._module_lamps()
        self.topology.update_data(self.db, self.live, self.node_lamps)
        try:
            self.wall.update_lamps(self.live, self.node_lamps, self.db)
        except Exception:                                                        # noqa: BLE001
            pass
        self._fill_stats()
        self._fill_signals()
        self._fill_quality()
        self._last = time.time()
        self.status_hint(self.status_line())

    def _module_lamps(self):
        """模块灯: 用包里的唯一一份灯逻辑聚合(模块灯 = 其输出信号所在话题的灯)"""
        db = self.db or {}
        L = _lamps_mod()
        tl = {k: _topic_lamp(self.live, k)[0] for k in (db.get("messages") or {})}
        out = {}
        sigs = db.get("signals") or []
        for nid, n in (db.get("nodes") or {}).items():
            if L:
                st, why, nin, nout = L.module_state(nid, sigs, tl)
            else:
                st, why, nin, nout = "black", "lamps 模块不可用", 0, 0
            out[nid] = (st, why, nin, nout)
        return out

    def status_line(self):
        d = self.live or {}
        ts = (d.get("topics") or {})
        L = _lamps_mod()
        tlamps = [ (v.get("lamp") or "black") for v in ts.values() ]
        nlamps = [ v[0] for v in (getattr(self, "node_lamps", {}) or {}).values() ]
        tal = L.tally(tlamps) if L else {}
        nal = L.tally(nlamps) if L else {}
        age = round(time.time() - self._last, 1)
        tot = sum((v.get("count") or 0) for v in ts.values())
        return ("🚦 报文灯 绿%d/黄%d/红%d/黑%d · 模块灯 绿%d/黄%d/红%d/黑%d · "
                "档位 %s · 累计报文 %d · 刷新 %.1fs 前"
                % (tal.get("green", 0), tal.get("yellow", 0), tal.get("red", 0), tal.get("black", 0),
                   nal.get("green", 0), nal.get("yellow", 0), nal.get("red", 0), nal.get("black", 0),
                   d.get("mode", "?"), tot, age))

    def _load_trace(self):
        rows = []
        try:
            with open(TRACE, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            rows.append(json.loads(line))
                        except Exception:                                        # noqa: BLE001
                            pass
        except OSError:
            pass
        self.trace = rows[-400:]

    def _fill_trace(self):
        kw = (self.ed_filter.text() or "").strip().lower()
        rows = [r for r in self.trace if not kw or kw in json.dumps(r, ensure_ascii=False).lower()]
        t0 = rows[0]["t"] if rows else 0.0
        self.lbl_tr_n.setText(("共 %d 条报文(落盘最近 %d 条 · 探针 2s 刷新)" % (len(rows), len(self.trace)))
                              if rows else
                              "暂无报文 —— 先看『🚦 状态灯』是哪一盏黑/红; 档位白名单外的话题本档不发(预期)")
        self.tb_trace.setRowCount(len(rows))
        for i, r in enumerate(rows):
            vals = ["%.3f" % (r["t"] - t0), r["topic"], r.get("type", ""), str(r.get("n", "")),
                    str(r.get("bytes", "")), r.get("digest", "")[:160]]
            for c, s in enumerate(vals):
                it = QTableWidgetItem(s)
                if c != 5:
                    it.setForeground(QColor(FG))
                self.tb_trace.setItem(i, c, it)
        if rows:
            self.tb_trace.scrollToBottom()

    def _fill_stats(self):
        rows = []
        try:
            import sys
            if os.path.join(REPO, "src") not in sys.path:
                sys.path.insert(0, os.path.join(REPO, "src"))
            from lerobot.dataspace import busdb as B
            rows = B.stats_rows(self.db, self.live) if self.db else []
        except Exception:                                                        # noqa: BLE001
            ts = (self.live.get("topics") or {})
            rows = [{"topic": v.get("topic", k), "type": (v.get("type") or "").split("::")[-1],
                     "kind": "typed", "n_signals": None, "hz_design": v.get("hz_design"),
                     "hz": v.get("hz"), "count": v.get("count"), "jitter_ms": v.get("jitter_ms"),
                     "loss_pct": v.get("loss_pct"), "bytes": v.get("bytes"),
                     "matched": v.get("matched_pubs"), "verdict": v.get("verdict", "-")}
                    for k, v in sorted(ts.items())]
        _tal = {}
        for r in rows:
            _l = ((self.live.get("topics") or {}).get(r.get("key", "")) or {}).get("lamp", "black")
            _tal[_l] = _tal.get(_l, 0) + 1
        self.lbl_st_n.setText("共 %d 条报文:  🟢 正常 %d   🟡 报警 %d   🔴 故障 %d   ⚫ 无信号 %d%s"
                              % (len(rows), _tal.get("green", 0), _tal.get("yellow", 0),
                                 _tal.get("red", 0), _tal.get("black", 0),
                                 "" if rows else "  (总线库缺失? 跑 tools/dds_bus.py --check)"))
        self.tb_stat.setRowCount(len(rows))
        for i, r in enumerate(rows):
            lv = (self.live.get("topics") or {}).get(r.get("key", ""), {})
            allowed = lv.get("allowed", True)
            lst = lv.get("lamp") or ("black" if not allowed else "-")
            vals = ["● %s" % LAMP_TXT.get(lst, lst), r["topic"], (r.get("type") or "").split("::")[-1],
                    r.get("n_signals") or "-",
                    r.get("hz_design"), "" if r.get("hz", -1) < 0 else round(r["hz"], 2),
                    r.get("count"), r.get("jitter_ms"), r.get("loss_pct"), r.get("bytes"),
                    r.get("matched"), r.get("verdict", "-")]
            for c, s in enumerate(vals):
                it = QTableWidgetItem("" if s is None else str(s))
                col = FG
                if c == 0:
                    col = _lamp_color(lst)
                elif c == 11:
                    col = _verdict_color(str(s))
                elif not allowed:
                    col = SILENT
                it.setForeground(QColor(col))
                self.tb_stat.setItem(i, c, it)

    def _fill_signals(self):
        if not self.db:
            return
        kw = (self.ed_sig.text() or "").strip().lower()
        lv = ((self.live.get("topics") or {}).get("link_value") or {})
        f = lv.get("fields") or {}
        cur = {"%s/%s" % (f.get("node_id"), f.get("port")): "%s (kind=%s seq=%s)" %
               (f.get("text", "")[:60], f.get("kind"), f.get("seq"))} if f else {}
        self.tr_sig.clear()
        for key, m in sorted((self.db.get("messages") or {}).items(),
                             key=lambda kv: (kv[1]["kind"] != "canvas_link", kv[0])):
            sigs = [s for s in (self.db.get("signals") or []) if s["topic"] == m["topic"]]
            if kw and not any(kw in json.dumps(s, ensure_ascii=False).lower() for s in sigs):
                continue
            root = QTreeWidgetItem(["%s  (%s, %s)" % (m["topic"], m["type"].split("::")[-1],
                                                      m["kind"]), "%d 信号" % len(sigs), ""])
            root.setForeground(0, QColor(ACC))
            for s in sigs:
                k = "%s/%s" % (s["src"], s["src_port"])
                it = QTreeWidgetItem(["%s · %s %s→%s %s" % (s["layer"], s["src_name"][:18],
                                                            str(s["src_port"]), s["dst_name"][:18],
                                                            str(s["dst_port"])),
                                      s["sid"], cur.get(k, "")])
                it.setForeground(0, QColor(LV_COLOR.get(s["layer"], FG)))
                root.addChild(it)
            self.tr_sig.addTopLevelItem(root)
        n_sig = len(self.db.get("signals") or [])
        self.lbl_sg_n.setText("共 %d 条连线信号 · %d 个模块(节点) · %d 条报文 —— 每条信号就是一个模块的输出/输入"
                              % (n_sig, len(self.db.get("nodes") or {}),
                                 len(self.db.get("messages") or {})))
        self.tr_sig.expandToDepth(0)

    def _fill_quality(self):
        out = []
        ts = (self.live.get("topics") or {})
        out.append("═══ 报文质量 (规则求值) ═══")
        n_bad = 0
        for k, v in sorted(ts.items()):
            for r in (v.get("rules") or []):
                if not r.get("ok"):
                    n_bad += 1
                    lvl = r.get("level", "warn")
                    out.append("[%s] %-14s %-22s %s" % (lvl.upper(), k, r.get("rule", ""),
                                                        str(r.get("msg", ""))[:110]))
        if not n_bad:
            out.append("  ✔ 无")
        out.append("")
        out.append("═══ 数据闭环 9 环节  灯语: 🟢 pass · 🔴 fail · 🟡 warn · ⚫ unknown(没证据, 不猜) ═══")
        lp = (self.loop.get("stages") or [])
        if isinstance(lp, dict):                     # 兼容两种落盘形态(字典/列表)
            lp = [dict(v, sid=k) for k, v in lp.items()]
        if not lp:
            out.append("  (loop.json 缺失 —— zmax-dataspaces-loop.service 在跑吗?)")
        for s in lp:
            gates = s.get("gates") or []
            npass = sum(1 for g in gates if g.get("ok") is True) if gates else s.get("n_pass")
            _st = str(s.get("status", "?")).lower()
            _ic = {"pass": "🟢", "ok": "🟢", "fail": "🔴", "warn": "🟡", "unknown": "⚫"}.get(_st, "⚫")
            out.append("  %s %-3s %-20s %-8s 门=%s/%s  %s" %
                       (_ic, str(s.get("id") or s.get("sid") or ""), str(s.get("name", ""))[:20],
                        str(s.get("status", "?")), npass, len(gates) or s.get("n_gate"),
                        str(s.get("evidence") or s.get("detail") or "")[:70]))
        self.tx_qual.setPlainText("\n".join(out))

    # ---------- 交互 ----------
    def _on_pause(self, st):
        self.paused = bool(st)

    def _pick_topic(self, key):
        self.status_hint("已选: %s" % key)

    def _export_trace(self):
        p, _ = QFileDialog.getSaveFileName(self.tabs, "导出报文追踪 CSV",
                                           os.path.expanduser("~/zmax_trace.csv"), "CSV (*.csv)")
        if not p:
            return
        rows = self.tb_trace
        with open(p, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow([rows.horizontalHeaderItem(i).text() for i in range(rows.columnCount())])
            for i in range(rows.rowCount()):
                w.writerow([rows.item(i, c).text() if rows.item(i, c) else "" for c in range(rows.columnCount())])
        self.status_hint("✅ 已导出 %s (%d 行)" % (p, rows.rowCount()))

    def _export_stats(self):
        p, _ = QFileDialog.getSaveFileName(self.tabs, "导出统计 CSV",
                                           os.path.expanduser("~/zmax_bus_stats.csv"), "CSV (*.csv)")
        if not p:
            return
        t = self.tb_stat
        with open(p, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow([t.horizontalHeaderItem(i).text() for i in range(t.columnCount())])
            for i in range(t.rowCount()):
                w.writerow([t.item(i, c).text() if t.item(i, c) else "" for c in range(t.columnCount())])
        self.status_hint("✅ 已导出 %s" % p)

    def _export_signals(self):
        p, _ = QFileDialog.getSaveFileName(self.tabs, "导出信号表 CSV",
                                           os.path.expanduser("~/zmax_bus_signals.csv"), "CSV (*.csv)")
        if not p:
            return
        with open(p, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["报文(topic)", "层", "信号ID", "源节点", "源端口", "目标节点", "目标端口"])
            for s in (self.db.get("signals") or []):
                w.writerow([s["topic"], s["layer"], s["sid"], s["src_name"], s["src_port"],
                            s["dst_name"], s["dst_port"]])
        self.status_hint("✅ 已导出信号表 %s (%d 条)" % (p, len(self.db.get("signals") or [])))

    # ---------- 回灌 ----------
    def _replay(self, once=True):
        if _mode() == "prod":
            self.tx_replay.appendPlainText(
                "⛔ 当前档位 prod(量产): 按设计**不序列化**。\n"
                "   要回灌请先切档: 档位下拉 → calib/test (守护 2s 内跟随), 再点回灌。")
            return
        if self._proc is not None:
            self.tx_replay.appendPlainText("⚠ 已有回灌在跑, 先用『停止』"); return
        cmd = [DDS_PY, BUS_TOOL, "--simulate"]
        cmd += ["--once"] if once else ["--watch", "--rate", "2"]
        self.tx_replay.appendPlainText("$ " + " ".join(cmd))
        self._proc = subprocess.Popen(cmd, cwd=REPO, stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT, text=True, bufsize=1)

        def _drain():
            if self._proc is None:
                return
            for _ in range(40):
                ln = self._proc.stdout.readline()
                if not ln:
                    if self._proc.poll() is not None:
                        self.tx_replay.appendPlainText("— 回灌进程结束 —")
                        self._proc = None
                        return
                    break
                self.tx_replay.appendPlainText(ln.rstrip())
            QTimer.singleShot(200, _drain)
        QTimer.singleShot(200, _drain)

    def _stop_replay(self):
        if self._proc is None:
            return
        self._proc.terminate()
        self.tx_replay.appendPlainText("⏹ 已停止回灌")
        self._proc = None


# ─────────────────────────── 🚦 状态灯墙 (每个模块一盏灯) ───────────────────────────
class LampDot(QWidget):
    """一盏灯(可点)"""

    def __init__(self, size=18, parent=None):
        super().__init__(parent)
        self.state = "black"
        self.size_ = size
        self.setFixedSize(size, size)

    def set_state(self, st):
        if st != self.state:
            self.state = st
            self.update()

    def paintEvent(self, _e):                                                  # noqa: N802
        q = QPainter(self)
        q.setRenderHint(QPainter.Antialiasing)
        r = self.size_ / 2.0 - 1
        _draw_lamp(q, self.size_ / 2.0, self.size_ / 2.0, r, self.state)


class LampWall(QWidget):
    """状态灯墙: 上半 = 报文(话题)的灯, 下半 = 模块(画布节点)的灯, 按层分组

    老倪: 「每个模块要有个状态灯 … 绿=正常 红=故障 黄=报警 黑=无信号」
    """

    def __init__(self, on_pick=None, parent=None):
        super().__init__(parent)
        from PyQt5.QtWidgets import QGridLayout, QScrollArea
        self.on_pick = on_pick
        self._cards = {}          # key → (LampDot, QLabel(name), QLabel(detail))
        self._order = []
        v = QVBoxLayout(self); v.setContentsMargins(6, 6, 6, 6); v.setSpacing(6)
        bar = QHBoxLayout()
        self.lbl_tally = QLabel("…")
        self.lbl_tally.setFont(QFont("Sans", 10))
        self.cb_nongreen = QCheckBox("只看非绿灯(故障/报警/无信号)")
        self.cb_nongreen.stateChanged.connect(lambda _s: self._apply_filter())
        bar.addWidget(self.lbl_tally); bar.addSpacing(12); bar.addWidget(self.cb_nongreen); bar.addStretch(1)
        v.addLayout(bar)
        self.area = QScrollArea(); self.area.setWidgetResizable(True)
        self.host = QWidget(); self.grid = QGridLayout(self.host)
        self.grid.setContentsMargins(4, 4, 4, 4); self.grid.setSpacing(6)
        self.area.setWidget(self.host)
        v.addWidget(self.area, 1)
        self._place({})

    # ---- 建卡(一次) ----
    def _make_card(self, key, title, sub):
        from PyQt5.QtWidgets import QFrame
        c = QFrame()
        c.setStyleSheet("QFrame{background:%s;border:1px solid %s;border-radius:4px}" % (PANEL, LINE))
        h = QHBoxLayout(c); h.setContentsMargins(6, 4, 6, 4); h.setSpacing(6)
        dot = LampDot(18)
        nm = QLabel(title); nm.setStyleSheet("color:%s;font-size:11px;font-weight:bold;border:none" % FG)
        nm.setToolTip(title)
        de = QLabel(sub); de.setStyleSheet("color:%s;font-size:10px;border:none" % DIM)
        de.setWordWrap(True)
        vv = QVBoxLayout(); vv.setSpacing(0); vv.addWidget(nm); vv.addWidget(de)
        h.addWidget(dot); h.addLayout(vv, 1)
        c.mouseReleaseEvent = lambda _e, k=key: (self.on_pick and self.on_pick(k))
        return c, dot, de

    def _place(self, db):
        """建网格(3 列): 第一节 报文灯, 之后按层 模块灯"""
        for i in reversed(range(self.grid.count())):
            w = self.grid.itemAt(i).widget()
            if w:
                w.setParent(None)
        self._cards, self._order = {}, []
        self._cells = []          # (grid_row, [keys...]) 供过滤时整行隐藏
        gr, gc, cur = 0, 0, []

        def flush():
            if cur:
                self._cells.append((gr, list(cur)))
        if db:
            def section(text):
                nonlocal gr, gc, cur
                flush(); cur = []
                lab = QLabel(text)
                lab.setStyleSheet("color:%s;font-size:10px;font-weight:bold;"
                                  "border:none;padding-top:6px" % ACC)
                self.grid.addWidget(lab, gr, 0, 1, 3)
                self.grid.setRowStretch(gr, 0)
                gr += 1; gc = 0

            def card(key, title):
                nonlocal gr, gc
                c, dot, de = self._make_card(key, title, "…")
                self.grid.addWidget(c, gr, gc)
                self._cards[key] = (dot, de, title)
                self._order.append((key, c))
                cur.append(key)
                gc += 1
                if gc >= 3:
                    gc = 0; gr += 1

            section("🚌 报文(topic)状态灯 —— 每条 topic 都是系统状态的输入/输出信号")
            for k, m in sorted((db.get("messages") or {}).items(),
                               key=lambda kv: (kv[1]["kind"] != "typed", kv[0])):
                card("T:" + k, m["topic"])
            for lk, llabel in (("L5", "L5 战略/意图"), ("L4", "L4 认知/世界模型"), ("L3", "L3 调度"),
                               ("L2", "L2 感知/执行"), ("meta", "meta 基建")):
                ns = [n for n in (db.get("nodes") or {}).values() if n["layer"] == lk]
                if not ns:
                    continue
                section("🧩 %s —— 模块状态灯 (输入/输出信号)" % llabel)
                for n in sorted(ns, key=lambda x: x["name"]):
                    card("N:" + n["id"], n["name"][:22])
            flush()
        self.grid.setColumnStretch(3, 1)

    # ---- 刷新卡内容 ----
    def update_lamps(self, live, node_lamps, db=None):
        from lerobot.dataspace import lamps as _L  # noqa: F401  (仅用于类型提示, 逻辑在包内)
        self._db_nodes = ((db or {}).get("nodes") or {})
        t_states = []
        for key, (dot, de, title) in list(self._cards.items()):
            if key.startswith("T:"):
                st, why = _topic_lamp(live, key[2:])
                dot.set_state(st)
                de.setText("● %s%s" % (LAMP_TXT.get(st, st), (" · " + why[:60]) if why else ""))
                de.setStyleSheet("color:%s;font-size:10px;border:none" % _lamp_color(st))
                t_states.append(("T", st, title))
            else:
                rec = (node_lamps or {}).get(key[2:])
                st, why, nin, nout = rec if rec else ("black", "无数据", 0, 0)
                dot.set_state(st)
                de.setText("● %s · 输入%d/输出%d%s" % (LAMP_TXT.get(st, st), nin, nout,
                                                     (" · " + why[:40]) if why else ""))
                de.setStyleSheet("color:%s;font-size:10px;border:none" % _lamp_color(st))
                t_states.append(("N", st, title))
        self._last_state = {key: dot.state for key, (dot, _de, _t) in self._cards.items()}
        L = _lamps_mod()
        tal = L.tally([s for _t, s, _n in t_states]) if L else {}
        if tal:
            per = {}
            for key, (dot, _de, _t) in self._cards.items():
                if not key.startswith("N:"):
                    continue
                for n in ((self._db_nodes or {}).get(key[2:]),):
                    if not n:
                        continue
                    per.setdefault(n["layer"], []).append(dot.state)
            lam = " · ".join("%s 绿%d/黄%d/红%d/黑%d" % (lk, L.tally(v).get("green", 0),
                                                       L.tally(v).get("yellow", 0),
                                                       L.tally(v).get("red", 0),
                                                       L.tally(v).get("black", 0))
                             for lk, v in sorted(per.items())) if per else ""
            self.lbl_tally.setText("🚦 状态灯总览:  🟢 正常 %d   🟡 报警 %d   🔴 故障 %d   ⚫ 无信号 %d"
                                   "     |  分层: %s"
                                   % (tal.get("green", 0), tal.get("yellow", 0),
                                      tal.get("red", 0), tal.get("black", 0), lam))
            worst = L.worst([s for _t, s, _n in t_states])
            from PyQt5.QtWidgets import QLabel as _QL
            _cn = {"green": "#2ecc71", "yellow": "#f1c40f", "red": "#e74c3c", "black": "#8b96a5"}[worst]
            self.lbl_tally.setStyleSheet("color:%s;font-size:11px" % _cn)
        self._t_states = t_states

    def _apply_filter(self):
        """只看非绿灯: 整行隐藏(保持网格稳定, 不重排)"""
        only = self.cb_nongreen.isChecked()
        st = getattr(self, "_last_state", {})
        for _gr, keys in getattr(self, "_cells", []):
            keep = (not only) or any(st.get(k, "black") != "green" for k in keys)
            for k in keys:
                for key, c in self._order:
                    if key == k:
                        c.setVisible(keep)


def build_tabs(tabs: QTabWidget, status_hint=None):
    """把总线各窗口加进调用方给的 QTabWidget(与既有数据空间页合并, 不新建模块卡)"""
    return BusPanel(tabs, status_hint)
