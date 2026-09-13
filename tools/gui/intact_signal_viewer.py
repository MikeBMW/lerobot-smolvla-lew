# -*- coding: utf-8 -*-
"""🎛 INTACT / L4·SW 互动查看器 (老倪 2026-09-13: "可以像 L2 L3 的 dreamview 一样, 变成互动,
可以看到任意帧的信号么")

与 DreamView3D (L2/L3 的 3D 分层视图) 同款交互思路 —— 只是这里看的是 **真渲染帧 + 逐帧信号**:
  · 时间轴滑块: 拖到任意帧 (或 ◀▶ 单帧步进 / ⏮⏭ 首尾 / ▶ 10fps 连续播放)
  · 画面: stable-world 环境真渲染帧 (224² → 放大, 像素 std 可查真伪)
  · 信号表: 该帧的 step / 回合 / 模型动作 4D (dx,dy,dz,gripper) / frame_std / done / 真推理次数
  · 曲线图: 动作 4 维随帧变化 + 游标线跟着滑块走 (任意帧信号一眼可见)
数据源: 自动扫描 reports/**/frames/ 目录 (L4·SW 实况导出) 及其同名 status.jsonl (逐帧信号日志;
        由 tools/intact_sw_bridge.py 每步追加一行)。
提示: 逐帧信号日志只有 bridge 新版本才有; 旧产物只有帧 (此时信号表显示"—", 不编数值)。
"""
from __future__ import annotations

import glob
import json
import os

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QSlider,
                             QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

try:
    import pyqtgraph as pg
except Exception:                                        # 无 pyqtgraph 也能用 (只是没曲线图)
    pg = None

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
REPORTS = os.path.join(REPO, "reports")
ACT_NAMES = ["动作[0]", "动作[1]", "动作[2]", "动作[3]"]   # 维度名随任务不同 (cube=5D/插拔=4D), 不硬套 dx/dy/dz


def discover_spools() -> list:
    """扫出所有含 frames/*.jpg 的目录 (每个 = 一次 L4·SW 实况导出)"""
    out = []
    for p in glob.glob(os.path.join(REPORTS, "**", "frames"), recursive=True):
        try:
            if glob.glob(os.path.join(p, "*.jpg")):
                out.append(os.path.dirname(p))
        except Exception:
            pass
    d = os.path.join(REPORTS, "intact_sw")
    if os.path.isdir(d) and d not in out:
        out.append(d)                                    # 即使为空也先列出来 (提示"尚未跑过")
    return sorted(set(out))


class IntactSignalViewer(QWidget):
    """🎛 真帧 + 逐帧信号 互动查看器 (拖帧/播放/单步; 与 SW 实况窗口共用同一数据源)"""

    def __init__(self, spool: str | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🎛 INTACT · L4 SW 实况 — 互动查看器 (拖帧看信号)")
        self.resize(1180, 780)
        self.setStyleSheet("QWidget{background:#0d1117;color:#e6edf3;font-size:12px;}")
        self._frames, self._sig = [], []
        self._i, self._play = 0, False

        v = QVBoxLayout(self)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(6)
        bar = QHBoxLayout()
        bar.setSpacing(6)
        t = QLabel("🎛 互动查看器 · 任意帧信号")
        t.setStyleSheet("color:#00d4aa;font-size:15px;font-weight:700;")
        bar.addWidget(t)
        bar.addSpacing(10)
        bar.addWidget(QLabel("数据源:"))
        self.cmb = QComboBox()
        self.cmb.setMinimumWidth(360)
        self.cmb.currentIndexChanged.connect(self._on_src)
        bar.addWidget(self.cmb)
        b_rescan = QPushButton("🔄 扫描")
        b_rescan.clicked.connect(self.rescan)
        bar.addWidget(b_rescan)
        bar.addStretch(1)
        self.b_first = QPushButton("⏮"); self.b_prev = QPushButton("◀")
        self.b_play = QPushButton("▶ 播放"); self.b_next = QPushButton("▶")
        self.b_last = QPushButton("⏭")
        for b, fn in ((self.b_first, lambda: self.set_index(0)),
                      (self.b_prev, lambda: self.set_index(self._i - 1)),
                      (self.b_play, self.toggle_play),
                      (self.b_next, lambda: self.set_index(self._i + 1)),
                      (self.b_last, lambda: self.set_index(len(self._frames) - 1))):
            b.setStyleSheet("QPushButton{background:#21262d;border:1px solid #30363d;"
                            "border-radius:4px;padding:4px 10px;}QPushButton:hover{color:#00d4aa;"
                            "border-color:#00d4aa;}")
            b.clicked.connect(fn)
            bar.addWidget(b)
        v.addLayout(bar)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMinimum(0)
        self.slider.valueChanged.connect(self._on_slide)
        v.addWidget(self.slider)

        sp = QSplitter(Qt.Horizontal)
        self.lbl_img = QLabel("尚未选择数据源")
        self.lbl_img.setAlignment(Qt.AlignCenter)
        self.lbl_img.setMinimumWidth(360)
        self.lbl_img.setStyleSheet("background:#161b22;border:1px solid #30363d;")
        self._pm0 = None
        sp.addWidget(self.lbl_img)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        self.tbl = QTableWidget(0, 2)
        self.tbl.setHorizontalHeaderLabels(["信号", "该帧真值"])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setStyleSheet("QTableWidget{background:#161b22;gridline-color:#30363d;}"
                               "QHeaderView::section{background:#21262d;color:#c9d1d9;border:0;}")
        self.tbl.horizontalHeader().setStretchLastSection(True)
        self.tbl.setMaximumHeight(210)
        rv.addWidget(self.tbl)
        if pg is not None:
            self.plot = pg.PlotWidget()
            self.plot.setBackground("#0d1117")
            self.plot.showGrid(x=True, y=True, alpha=0.25)
            self.plot.setLabel("bottom", "帧序号")
            self.plot.setLabel("left", "模型动作 (反归一化)")
            self.plot.addLegend(offset=(8, 8))
            cols = ["#00d4aa", "#d29922", "#a371f7", "#f85149"]
            self.curves = []
            for j, nm in enumerate(ACT_NAMES):
                self.curves.append(self.plot.plot([], [], pen=pg.mkPen(cols[j], width=2), name=nm))
            self.cursor = pg.InfiniteLine(pos=0, angle=90, movable=False,
                                          pen=pg.mkPen("#8b949e", width=1, style=Qt.DashLine))
            self.plot.addItem(self.cursor)
            rv.addWidget(self.plot, 1)
        else:
            self.plot, self.curves, self.cursor = None, [], None
        sp.addWidget(right)
        sp.setSizes([520, 640])
        v.addWidget(sp, 1)

        self.info = QLabel("拖时间轴 / ◀▶ 单帧 / ▶ 连续播放 —— 对应帧的模型动作与状态会同步更新")
        self.info.setStyleSheet("color:#8b949e;")
        v.addWidget(self.info)

        self._timer = QTimer(self)
        self._timer.timeout.connect(lambda: self.set_index((self._i + 1) % max(1, len(self._frames))))
        self._timer.setInterval(100)
        self.rescan(spool)

    # ── 数据源 ──
    def rescan(self, prefer: str | None = None):
        cur = prefer or (self.cmb.currentData() if self.cmb.count() else None)
        spools = discover_spools()
        self.cmb.blockSignals(True)
        self.cmb.clear()
        for s in spools:
            self.cmb.addItem(f"{os.path.relpath(s, REPO)}  ({len(glob.glob(os.path.join(s, 'frames', '*.jpg')))} 帧)", s)
        self.cmb.blockSignals(False)
        idx = 0
        if cur:
            for i in range(self.cmb.count()):
                if self.cmb.itemData(i) == cur:
                    idx = i
                    break
        if self.cmb.count():
            self.cmb.setCurrentIndex(idx)
            self._load(self.cmb.itemData(idx))

    def _on_src(self, _):
        if self.cmb.count():
            self._load(self.cmb.currentData())

    def _load(self, spool: str | None):
        self._frames, self._sig = [], []
        if not spool:
            self.lbl_img.setText("尚未选择数据源")
            return
        fr = os.path.join(spool, "frames")
        self._frames = sorted(glob.glob(os.path.join(fr, "*.jpg")))
        jl = os.path.join(spool, "status.jsonl")
        if os.path.isfile(jl):
            with open(jl, encoding="utf-8") as fh:
                for ln in fh:
                    try:
                        self._sig.append(json.loads(ln))
                    except Exception:
                        pass
        self.slider.setMaximum(max(0, len(self._frames) - 1))
        self.slider.blockSignals(True)
        self.slider.setValue(len(self._frames) - 1)          # 默认停在最新帧
        self.slider.blockSignals(False)
        if self.plot is not None and self._sig:
            A = [s.get("action") or [0, 0, 0, 0] for s in self._sig]
            n = min(len(A), len(self._frames))
            for j in range(4):
                self.curves[j].setData(list(range(n)), [float(a[j]) for a in A[:n]])
        self.set_index(len(self._frames) - 1)

    # ── 帧操作 ──
    def toggle_play(self):
        self._play = not self._play
        self.b_play.setText("⏸ 暂停" if self._play else "▶ 播放")
        if self._play:
            self._timer.start()
        else:
            self._timer.stop()

    def _on_slide(self, i):
        self.set_index(i)

    def set_index(self, i: int):
        n = len(self._frames)
        if n == 0:
            self.lbl_img.setText("该数据源还没有帧 —— 选 L4 档点 ▶运行 (或先跑一次 SW 引擎链)")
            self.tbl.setRowCount(0)
            return
        i = max(0, min(int(i), n - 1))
        self._i = i
        if self.slider.value() != i:
            self.slider.blockSignals(True)
            self.slider.setValue(i)
            self.slider.blockSignals(False)
        from PyQt5.QtGui import QPixmap
        pm = QPixmap(self._frames[i])
        if not pm.isNull():
            self._pm0 = pm
            self._render_img()
        s = self._sig[i] if i < len(self._sig) else {}
        a = s.get("action") or [None] * 4
        rows = [
            ("帧文件", os.path.basename(self._frames[i])),
            ("帧序号", f"{i+1} / {n}"),
            ("step (引擎步)", s.get("step", "—")),
            ("回合 ep", s.get("ep", "—")),
            ("模型动作[0]", self._fmt(a, 0)),
            ("模型动作[1]", self._fmt(a, 1)),
            ("模型动作[2]", self._fmt(a, 2)),
            ("模型动作[3]", self._fmt(a, 3)),
            ("帧像素 std (>5=真图)", s.get("frame_std", "—")),
            ("本步 done (任务完成)", s.get("done", "—")),
            ("累计真推理次数", s.get("model_calls", "—")),
        ]
        self.tbl.setRowCount(len(rows))
        for r, (k, v) in enumerate(rows):
            it1, it2 = QTableWidgetItem(str(k)), QTableWidgetItem(str(v))
            it2.setForeground(Qt.green if k.startswith("模型动作") else Qt.white)
            self.tbl.setItem(r, 0, it1)
            self.tbl.setItem(r, 1, it2)
        if self.cursor is not None:
            self.cursor.setPos(i)
        self.info.setText(f"该帧: {os.path.basename(self._frames[i])} · 动作 "
                          f"[{self._fmt(a,0)}, {self._fmt(a,1)}, {self._fmt(a,2)}, {self._fmt(a,3)}] · "
                          f"std={s.get('frame_std','—')} · done={s.get('done','—')}"
                          + ("" if self._sig else "   ⚠️ 无 status.jsonl (旧产物只有帧, 信号显示 —)"))

    @staticmethod
    def _fmt(a, j):
        try:
            return f"{float(a[j]):+.4f}"
        except Exception:
            return "—"

    def _render_img(self):
        if self._pm0 is None or self._pm0.isNull():
            return
        w = max(160, self.lbl_img.width() - 6)
        h = max(160, self.lbl_img.height() - 6)
        self.lbl_img.setPixmap(self._pm0.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._render_img()


_VIEWER = None


def open_signal_viewer(spool: str | None = None):
    """单例打开 (画布节点双击 / SW 实况窗口按钮 共用)"""
    global _VIEWER
    try:
        if _VIEWER is None:
            _VIEWER = IntactSignalViewer(spool)
            _VIEWER.setWindowFlag(Qt.WindowStaysOnTopHint, False)
        if spool:
            _VIEWER.rescan(spool)
        _VIEWER.show()
        _VIEWER.raise_()
        _VIEWER.activateWindow()
        return _VIEWER
    except Exception as e:                                   # noqa: BLE001
        try:
            print(f"[互动查看器] 打开失败: {type(e).__name__}: {e}")
        except Exception:
            pass
        return None
