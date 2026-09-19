#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""su2_dialog.py — 🧩 SU(2) 统一状态空间 人机交互观测面板 (VEH.5.041 双击)

2026-09-20 老倪: 统一状态空间是二阶特殊酉群 SU(2); 这个节点要有丰富的工具,
人机交互地观察状态空间的数据 —— 所有可视化层的工具都从这一个面板进。

五个观测视图 (全部读真实数据, 无编造):
  ① 🌐 Bloch 球      — 群元素(S作为旋转)作用在参考态上的像; 轨迹 + 各层点, 可拖动旋转
  ② 🧮 层贡献/反演   — L2/L3/L4/L5 逐层剥离, 读每层"贡献了多少" + 残余(应≈0)
  ③ 📐 几何关系      — 层间不可交换性 ‖[Ui,Uj]‖ 与 Fubini–Study 距离矩阵 (热力表)
  ④ 🧩 节点映射      — 画布每个节点的数据 → 群元素 (θ/方向/收敛度), 无数值输出者明标
  ⑤ 📈 阶段轨迹      — 引擎分阶段 θ_total / 收敛度 / θ_L2 (真实逐帧均值)

数据源: module._SS_STATE (画布刚执行的当前帧) + reports/su2_state_report.json (引擎轨迹)
按钮: 🔄 重算(跑 tools/ss_su2_verify.py) · 📂 报告 · 📄 导出当前帧 · 🔭 可视化工具入口
"""
import json
import os
import sys

from PyQt5.QtCore import Qt, QProcess, QTimer
from PyQt5.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PyQt5.QtWidgets import (QComboBox, QDialog, QFormLayout, QGroupBox, QHBoxLayout,
                             QLabel, QPlainTextEdit, QPushButton, QTabWidget, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPORT = os.path.join(REPO, "reports", "su2_state_report.json")
PYBIN = os.path.join(REPO, "gui-venv311", "bin", "python")

DARK = """
QDialog, QWidget { background:#1b1e24; color:#e8e8e8; }
QLabel { color:#e8e8e8; font-size:14px; }
QLabel#head { font-size:17px; font-weight:bold; color:#ffffff; }
QTableWidget { background:#12141a; color:#e6e6e6; gridline-color:#303643;
               font-size:13px; selection-background-color:#2d4f6b; }
QHeaderView::section { background:#232833; color:#eaeaea; border:1px solid #3a3f4b; }
QTabWidget::pane { border:1px solid #3a3f4b; }
QTabBar::tab { background:#232833; color:#dcdcdc; padding:7px 14px; font-size:14px; }
QTabBar::tab:selected { background:#2d4f6b; color:#ffffff; }
QPushButton { background:#2a2f3a; color:#f0f0f0; border:1px solid #46506a;
              padding:7px 14px; border-radius:4px; font-size:14px; }
QPushButton:hover { background:#354054; }
QPlainTextEdit { background:#0f1115; color:#d6e0d6; font-family:Consolas,monospace; font-size:13px; }
QGroupBox { color:#e8e8e8; border:1px solid #3a3f4b; margin-top:8px; padding-top:6px; }
"""

# 层配色: 单色系(灰阶+一档冷色), 不用高饱和撞色 (老倪界面偏好: 单色勿彩高亮)
LAYER_COLORS = {"L2": QColor("#e6edf3"), "L3": QColor("#9fb3c8"),
                "L4": QColor("#7d8fa9"), "L5": QColor("#5b6a80"), "scene": QColor("#3fb950")}


def _load_report():
    try:
        with open(REPORT, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


class BlochSphere(QWidget):
    """Bloch 球 (QPainter 手绘, 拖动旋转/滚轮缩放) — 群元素在 S² 上的像 + 轨迹 + 各层点"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(420, 420)
        self.traj = []            # [[x,y,z], ...] 轨迹
        self.points = {}          # {"L2": [x,y,z], ...} 当前各层
        self.scene = [0.0, 0.0, 1.0]
        self.az, self.el, self.zoom = 0.6, 0.35, 1.0
        self._drag = None

    def set_data(self, traj=None, points=None, scene=None):
        if traj is not None:
            self.traj = [p for p in traj if p and len(p) == 3]
        if points is not None:
            self.points = points
        if scene is not None:
            self.scene = scene
        self.update()

    # ── 交互: 拖动旋转, 滚轮缩放 ──
    def mousePressEvent(self, e):
        self._drag = (e.x(), e.y())

    def mouseMoveEvent(self, e):
        if self._drag:
            dx, dy = e.x() - self._drag[0], e.y() - self._drag[1]
            self.az += dx * 0.01
            self.el = max(-1.5, min(1.5, self.el + dy * 0.01))
            self._drag = (e.x(), e.y())
            self.update()

    def mouseReleaseEvent(self, e):
        self._drag = None

    def wheelEvent(self, e):
        self.zoom = max(0.6, min(2.2, self.zoom * (1.1 if e.angleDelta().y() > 0 else 0.9)))
        self.update()

    def _proj(self, p):
        import math
        x, y, z = p
        ca, sa = math.cos(self.az), math.sin(self.az)
        ce, se = math.cos(self.el), math.sin(self.el)
        x1, z1 = x * ca - y * sa, x * sa + y * ca
        y1 = y * 0 + z * ce - z1 * se
        z2 = z * se + z1 * ce
        R = min(self.width(), self.height()) * 0.36 * self.zoom
        cx, cy = self.width() / 2, self.height() / 2
        return cx + x1 * R, cy - y1 * R, z2           # z2 用于前后遮挡判断

    def paintEvent(self, ev):
        import math
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#0d1117"))
        R = min(self.width(), self.height()) * 0.36 * self.zoom
        cx, cy = self.width() / 2, self.height() / 2
        # 球体轮廓 + 赤道/子午线
        p.setPen(QPen(QColor("#2b3240"), 1.2))
        p.drawEllipse(int(cx - R), int(cy - R), int(2 * R), int(2 * R))
        for ang in (0, 30, 60, 90, 120, 150):
            t = math.radians(ang)
            p.setPen(QPen(QColor("#222833"), 1 if ang % 60 else 1.4))
            p.drawEllipse(int(cx - R), int(cy - R * abs(math.cos(t))), int(2 * R),
                          int(2 * R * abs(math.cos(t))))
            p.drawEllipse(int(cx - R * abs(math.sin(t))), int(cy - R),
                          int(2 * R * abs(math.sin(t))), int(2 * R))
        # 坐标轴 (x/y/z)
        for vec, lab in (((1, 0, 0), "x"), ((0, 1, 0), "y"), ((0, 0, 1), "|0⟩")):
            x1, y1, _ = self._proj(vec)
            x0, y0, _ = self._proj((0, 0, 0))
            p.setPen(QPen(QColor("#3a4252"), 1.2, Qt.DashLine))
            p.drawLine(int(x0), int(y0), int(x1), int(y1))
            p.setPen(QPen(QColor("#8b97a8"), 1.0))
            p.drawText(int(x1) + 3, int(y1) - 3, lab)
        # 轨迹 (灰阶渐变按时间)
        if len(self.traj) > 1:
            n = len(self.traj)
            for i in range(1, n):
                a = 60 + int(140 * i / n)
                p.setPen(QPen(QColor(58, 110, 165, a), 1.6))
                x0, y0, _ = self._proj(self.traj[i - 1])
                x1, y1, _ = self._proj(self.traj[i])
                p.drawLine(int(x0), int(y0), int(x1), int(y1))
        # 各层当前点
        for k, v in self.points.items():
            if not v or len(v) != 3:
                continue
            x, y, z2 = self._proj(v)
            col = LAYER_COLORS.get(k, QColor("#e6edf3"))
            p.setPen(QPen(col, 1.4))
            p.setBrush(col)
            p.drawEllipse(int(x - 4), int(y - 4), 8, 8)
            p.setPen(QPen(QColor("#c9d4e0"), 1.0))
            p.drawText(int(x) + 6, int(y) - 5, k)
        # 场景态(大点)
        if self.scene and len(self.scene) == 3:
            x, y, _ = self._proj(self.scene)
            p.setPen(QPen(QColor("#3fb950"), 2.2))
            p.setBrush(QColor("#3fb950"))
            p.drawEllipse(int(x - 6), int(y - 6), 12, 12)
            p.setPen(QPen(QColor("#ffffff"), 1.0))
            p.drawText(int(x) + 9, int(y) + 14, "U_scene")
        p.setPen(QPen(QColor("#6b7686"), 1.0))
        p.drawText(10, self.height() - 8, "拖动旋转 · 滚轮缩放 · 轨迹=引擎逐帧 · ⬤ 各层当前态")
        p.end()


class SU2Panel(QDialog):
    """SU(2) 统一状态空间观测面板 (VEH.5.041)"""

    def __init__(self, parent=None, module=None, node=None):
        super().__init__(parent)
        self.module = module
        self.node = node or {}
        self.setWindowTitle("🧩 SU(2) 统一状态空间 · 二阶特殊酉群 — 观测面板")
        self.resize(1180, 760)
        self.setStyleSheet(DARK)
        self._proc = None
        self._build()
        self.reload()

    # ── UI ──
    def _build(self):
        v = QVBoxLayout(self)
        head = QLabel("🧩 SU(2) 统一状态空间 · 二阶特殊酉群  |  "
                      "SU(2) = {U ∈ C²ˣ² : U†U = I, det U = 1} = exp(−i·ω·σ/2)")
        head.setObjectName("head")
        v.addWidget(head)
        self.lbl_src = QLabel("数据源: —")
        v.addWidget(self.lbl_src)

        # 顶部按钮行
        row = QHBoxLayout()
        self.btn_recalc = QPushButton("🔄 重算 (跑真实引擎轨迹)")
        self.btn_recalc.clicked.connect(self.recalc)
        self.btn_report = QPushButton("📂 报告 JSON")
        self.btn_report.clicked.connect(self.open_report)
        self.btn_export = QPushButton("📄 导出当前帧")
        self.btn_export.clicked.connect(self.export_frame)
        self.cmb_viz = QComboBox()
        self.cmb_viz.addItems(["🔭 打开可视化工具…", "仿真波形", "3D 场景", "前馈激活直方图",
                               "归因·分工", "操作视频", "输入图像"])
        self.cmb_viz.currentIndexChanged.connect(self._open_viz)
        for w in (self.btn_recalc, self.btn_report, self.btn_export, self.cmb_viz):
            row.addWidget(w)
        row.addStretch(1)
        v.addLayout(row)

        self.tabs = QTabWidget()
        # ① Bloch
        t1 = QWidget(); l1 = QHBoxLayout(t1)
        self.bloch = BlochSphere()
        l1.addWidget(self.bloch, 3)
        self.txt_obs = QPlainTextEdit(); self.txt_obs.setReadOnly(True)
        l1.addWidget(self.txt_obs, 2)
        self.tabs.addTab(t1, "🌐 Bloch 球 / 状态方向")
        # ② 层贡献 + 反演
        t2 = QWidget(); l2 = QVBoxLayout(t2)
        self.tbl_layer = QTableWidget(0, 6)
        self.tbl_layer.setHorizontalHeaderLabels(["层", "层的 θ", "剥离后残余 θ", "该层贡献 Δθ",
                                                  "方向 n̂", "含义"])
        l2.addWidget(self.tbl_layer, 3)
        self.txt_peel = QPlainTextEdit(); self.txt_peel.setReadOnly(True)
        l2.addWidget(self.txt_peel, 2)
        self.tabs.addTab(t2, "🧮 层贡献 / 反演剥离")
        # ③ 几何关系 (不可交换 + FS 距离)
        t3 = QWidget(); l3 = QVBoxLayout(t3)
        self.tbl_comm = QTableWidget(0, 5); self.tbl_fs = QTableWidget(0, 5)
        self.tbl_comm.setHorizontalHeaderLabels(["‖[Ui,Uj]‖", "L2", "L3", "L4", "L5"])
        self.tbl_fs.setHorizontalHeaderLabels(["FS 距离", "L2", "L3", "L4", "L5"])
        l3.addWidget(QLabel("层间不可交换性 ‖[U_i,U_j]‖₂ — 值大 = 两层强耦合(顺序敏感)"))
        l3.addWidget(self.tbl_comm, 2)
        l3.addWidget(QLabel("Fubini–Study 测地距离 arccos|⟨U_i,U_j⟩| (层间几何关系)"))
        l3.addWidget(self.tbl_fs, 2)
        self.tabs.addTab(t3, "📐 几何关系")
        # ④ 节点映射
        t4 = QWidget(); l4 = QVBoxLayout(t4)
        self.tbl_node = QTableWidget(0, 5)
        self.tbl_node.setHorizontalHeaderLabels(["节点", "θ (rad)", "收敛度 |w|", "方向 n̂", "备注"])
        l4.addWidget(self.tbl_node)
        self.tabs.addTab(t4, "🧩 节点映射 (全面)")
        # ⑤ 阶段轨迹
        t5 = QWidget(); l5 = QVBoxLayout(t5)
        self.tbl_stage = QTableWidget(0, 5)
        self.tbl_stage.setHorizontalHeaderLabels(["阶段", "帧数", "θ_total", "收敛 |w|", "θ_L2"])
        l5.addWidget(self.tbl_stage, 3)
        self.txt_stage = QPlainTextEdit(); self.txt_stage.setReadOnly(True)
        l5.addWidget(self.txt_stage, 2)
        self.tabs.addTab(t5, "📈 阶段轨迹")
        v.addWidget(self.tabs, 1)
        self.lbl_status = QLabel("就绪")
        v.addWidget(self.lbl_status)

    # ── 数据装载 ──
    def _live(self):
        """画布刚执行的当前帧 (module._SS_STATE)"""
        st = getattr(self.module, "_SS_STATE", None) if self.module is not None else None
        if not isinstance(st, dict):
            try:
                import node_logic as _nl
                st = _nl._SS_STATE
            except Exception:
                st = {}
        return st or {}

    def reload(self):
        rep = _load_report()
        live = self._live()
        scene = live.get("su2_scene")
        layers = live.get("su2_layers") or {}
        readout = live.get("su2_readout") or {}
        nodes = live.get("su2_nodes") or {}

        # 轨迹 / 阶段 / 节点 优先用报告 (引擎全轨迹), 当前帧用画布实测量
        traj = None
        if rep:
            traj = rep.get("engine_trace", {}).get("bloch_series")
        self.lbl_src.setText(
            "数据源: %s | 报告: %s | 当前帧: %s"
            % ("reports/su2_state_report.json" if rep else "无报告 (点 🔄 重算)",
               os.path.basename(REPORT) if os.path.exists(REPORT) else "缺失",
               "画布实测量 ✓" if scene is not None else "未执行 (点节点单步/右键运行)"))

        # ① Bloch
        pts = {}
        for L, u in layers.items():
            if hasattr(u, "bloch"):
                pts[L] = list(u.bloch())
        scene_v = None
        if scene is not None and hasattr(scene, "bloch"):
            scene_v = list(scene.bloch())
        self.bloch.set_data(traj=traj, points=pts, scene=scene_v)
        txt = []
        if readout:
            txt.append("【当前帧 · 画布实测量】")
            txt.append(readout.get("readout", ""))
            st_d = readout.get("state", {})
            txt.append("四元数 (w,x,y,z) = %s" % [round(v, 5) for v in st_d.get("quat", [])])
            txt.append("Bloch 向量 r        = %s" % [round(v, 5) for v in st_d.get("bloch", [])])
            txt.append("偏离角 θ = %.4f rad (%.2f°)  |  收敛度 |w| = %.4f"
                       % (st_d.get("theta", 0.0), st_d.get("theta", 0.0) * 57.2958,
                          st_d.get("visibility", 0.0)))
            txt.append("主导层 = %s" % readout.get("dominant_layer"))
            txt.append("层剥离残余 θ = %.3e (≈0 ⇒ 群分解自洽)"
                       % readout.get("layer_peel", {}).get("_residual", {}).get("theta", 0.0))
        else:
            txt.append("当前帧未执行: 在画布上 ⏭单步 / 右键「运行节点」/ ▶运行 到该节点后重开本面板")
        self.txt_obs.setPlainText("\n".join(txt))

        # ② 层贡献
        peel = readout.get("layer_peel", {})
        ks = [k for k in ("L2", "L3", "L4", "L5") if k in peel]
        self.tbl_layer.setRowCount(len(ks))
        meaning = {"L2": "执行层: 43D 几何误差(光模块−孔位)", "L3": "规划层: 流形进度/法向偏离/剩余",
                   "L4": "自主层: 限幅动作/接触概率/未达η", "L5": "大模型层: 场景意图(未接入=单位元)"}
        for i, k in enumerate(ks):
            d = peel[k]
            vals = [k, "%.4f" % d["layer_theta"], "%.4f" % d["theta_after"],
                    "%+.4f" % d["delta_theta"],
                    "(%+.2f,%+.2f,%+.2f)" % tuple(d["layer_axis"])[:3], meaning.get(k, "")]
            for j, s in enumerate(vals):
                self.tbl_layer.setItem(i, j, QTableWidgetItem(str(s)))
        self.tbl_layer.resizeColumnsToContents()
        txt_peel = [
            "群反演(观察/理解): 从场景态 U_scene 逐层左乘逆元 —— U_L2⁻¹·U_scene 后读残余 θ,",
            "即「这一层贡献了多少」; 全部剥离后应回到单位元(θ≈0) = 群分解自洽。",
            "注: 群不可交换, 剥离顺序会影响中间量 —— 这正是「层序敏感」的体现, 不是误差。",
        ]
        if peel:
            txt_peel.append("残余 θ = %.3e" % peel.get("_residual", {}).get("theta", 0.0))
        self.txt_peel.setPlainText("\n".join(txt_peel))

        # ③ 几何关系 (优先当前帧实测量; 无则用报告末帧引擎实测量)
        if not readout.get("noncommutativity"):
            readout = rep.get("understand_last") or readout
        comm = readout.get("noncommutativity", {})
        fs = readout.get("layer_distance", {})
        for tbl, data in ((self.tbl_comm, comm), (self.tbl_fs, fs)):
            keys = [k for k in data if "|" in k]
            ks2 = sorted({k.split("|")[0] for k in keys})
            tbl.setRowCount(len(ks2))
            for i, a in enumerate(ks2):
                tbl.setItem(i, 0, QTableWidgetItem(a))
                for j, b in enumerate(ks2):
                    v = data.get("%s|%s" % (a, b), 0.0)
                    it = QTableWidgetItem("%.4f" % v if not isinstance(v, str) else str(v))
                    g = 255 - int(min(1.0, abs(float(v)) / 2.0) * 120) if isinstance(v, (int, float)) else 240
                    it.setBackground(QColor(g, g, g))
                    it.setForeground(QColor("#101418" if g > 150 else "#e8e8e8"))
                    tbl.setItem(i, j + 1, it)
            tbl.resizeColumnsToContents()
            for j, b in enumerate(ks2):
                tbl.setHorizontalHeaderItem(j + 1, QTableWidgetItem(b))

        # ④ 节点映射
        node_rows = []
        if nodes:
            for k, u in nodes.items():
                node_rows.append((k, u.theta() if hasattr(u, "theta") else 0.0,
                                  u.visibility() if hasattr(u, "visibility") else 1.0,
                                  u.axis() if hasattr(u, "axis") else [0, 0, 0], ""))
        else:
            nm = rep.get("node_mapping", {})
            for k, d in (nm.get("nodes") or {}).items():
                node_rows.append((k, d.get("theta", 0.0), d.get("visibility", 1.0),
                                  d.get("axis", [0, 0, 0]), ""))
            for k in (nm.get("no_numeric_output") or []):
                node_rows.append((k, 0.0, 1.0, [0, 0, 0], "本帧无数值输出 → 单位元(不编造)"))
        self.tbl_node.setRowCount(len(node_rows))
        for i, (k, th, vis, ax, note) in enumerate(node_rows):
            for j, s in enumerate([k, "%.4f" % th, "%.4f" % vis,
                                   "(%+.2f,%+.2f,%+.2f)" % (ax[0], ax[1], ax[2]), note]):
                self.tbl_node.setItem(i, j, QTableWidgetItem(str(s)))
        self.tbl_node.resizeColumnsToContents()

        # ⑤ 阶段轨迹
        st_tab = rep.get("stage_table", {})
        self.tbl_stage.setRowCount(len(st_tab))
        for i, (st, d) in enumerate(st_tab.items()):
            for j, s in enumerate([st, str(d.get("n", 0)), "%.4f" % d.get("theta", 0.0),
                                   "%.4f" % d.get("vis", 0.0), "%.4f" % d.get("theta_L2", 0.0)]):
                self.tbl_stage.setItem(i, j, QTableWidgetItem(s))
        self.tbl_stage.resizeColumnsToContents()
        et = rep.get("engine_trace", {})
        self.txt_stage.setPlainText(
            "引擎真实轨迹 (StateSpaceSim): %d 步 · 初始 θ=%.4f → 末 θ=%.4f · |w| %.4f → %.4f\n"
            "θ↓ 与 |w|↑ 同步 = 场景向参考态(群恒等元, 任务完成)收敛。\n"
            "阶段表为逐帧实测均值: 每个阶段的群元素都是那批真实帧算出来的。"
            % (et.get("n_steps", 0), et.get("theta_first", 0.0), et.get("theta_last", 0.0),
               et.get("visibility_first", 0.0), et.get("visibility_last", 0.0)))

    # ── 按钮 ──
    def recalc(self):
        """后台跑真实引擎轨迹生成报告 (不阻塞界面)"""
        script = os.path.join(REPO, "tools", "ss_su2_verify.py")
        py = PYBIN if os.path.exists(PYBIN) else sys.executable
        self.lbl_status.setText("🔄 正在跑真实引擎轨迹 (StateSpaceSim)… 约 20-60s")
        self.btn_recalc.setEnabled(False)
        self._proc = QProcess(self)
        self._proc.setWorkingDirectory(REPO)
        self._proc.finished.connect(self._on_recalc_done)
        self._proc.start(py, [script])

    def _on_recalc_done(self, code, st):
        self.btn_recalc.setEnabled(True)
        self.lbl_status.setText("🔄 重算结束 (exit=%d) — 已重载报告" % code if code == 0
                                else "⚠️ 重算失败 exit=%d" % code)
        self.reload()

    def open_report(self):
        try:
            if self.module is not None and hasattr(self.module, "_log"):
                self.module._log("📂 SU(2) 报告: %s" % REPORT)
            os.system("xdg-open '%s' 2>/dev/null &" % REPORT)
        except Exception as e:                                              # noqa: BLE001
            self.lbl_status.setText("⚠️ 打开报告失败: %s" % e)

    def export_frame(self):
        live = self._live()
        out = {"source": "SU2Panel 当前帧导出", "node": self.node.get("name", ""),
               "readout": {k: v for k, v in (live.get("su2_readout") or {}).items()}}
        p = os.path.join(REPO, "reports", "su2_frame_export.json")
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=1, default=str)
            self.lbl_status.setText("📄 已导出: %s" % p)
        except Exception as e:                                              # noqa: BLE001
            self.lbl_status.setText("⚠️ 导出失败: %s" % e)

    def _open_viz(self, idx):
        """可视化层工具统一入口 — 都从 SU(2) 节点进 (老倪: 所有可视化层的工具都映射到这个节点)"""
        if idx <= 0 or self.module is None:
            return
        kind = {1: "波形", 2: "3D", 3: "直方图", 4: "归因", 5: "视频", 6: "输入图像"}.get(idx, "波形")
        try:
            self.module._open_viz_node(kind)
            self.lbl_status.setText("🔭 已打开可视化工具: %s" % kind)
        except Exception as e:                                              # noqa: BLE001
            self.lbl_status.setText("⚠️ 打开 %s 失败: %s" % (kind, e))
        QTimer.singleShot(0, lambda: self.cmb_viz.setCurrentIndex(0))
