# -*- coding: utf-8 -*-
"""calibration_dialog.py — 🧮 标定层 UI (2026-09-02 老倪)

引力/斥力二分超参数 + 平衡点 (Drifting Models 反称场思想):
  引力 (Attraction) = 快速动作 — Kp + 各阶段速度上限/下限
  斥力 (Repulsion)  = 状态预测 — K_kalman + 残差EMA + 接触增益 + 否决阈值
  平衡偏差 = 引力势 − 斥力势 (|偏差|→0 = 无漂移平衡)

回路外元层: 参数可调但只导出建议值 (reports/calibration_*.json),
引擎仍用源码常量 — 不改变任何现有拓扑/流程/架构。
"""
import os

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout,
                             QDoubleSpinBox, QTableWidget, QTableWidgetItem, QLabel,
                             QPushButton, QProgressBar, QMessageBox, QHeaderView)

_DARK = ("QDialog { background:#0d1117; color:#e6edf3; } "
         "QLabel { color:#e6edf3; } QGroupBox { color:#00d4aa; border:1px solid #30363d; "
         "border-radius:6px; margin-top:10px; } QGroupBox::title { subcontrol-origin: margin; left:10px; padding:0 4px; } "
         "QDoubleSpinBox { background:#161b22; color:#e6edf3; border:1px solid #30363d; border-radius:4px; padding:2px 6px; } "
         "QTableWidget { background:#161b22; color:#e6edf3; border:1px solid #30363d; gridline-color:#30363d; } "
         "QHeaderView::section { background:#21262d; color:#e6edf3; border:none; padding:4px; } "
         "QPushButton { background:#1f6feb; color:#fff; border:none; border-radius:5px; padding:8px 16px; font-size:13px; } "
         "QPushButton:hover { background:#388bfd; } QProgressBar { background:#161b22; border:1px solid #30363d; "
         "border-radius:4px; text-align:center; color:#e6edf3; } QProgressBar::chunk { background:#00d4aa; }")


class CalibrationDialog(QDialog):
    """🧮 标定层 — 引力/斥力标定面板 + 平衡点指示"""

    def __init__(self, layer, stage="接近", gap=0.0, parent=None):
        super().__init__(parent)
        self.layer = layer
        self.setWindowTitle("🧮 标定层 · 引力/斥力平衡 (Drifting Models)")
        self.setStyleSheet(_DARK)
        self.setMinimumWidth(760)
        lay = QVBoxLayout(self)

        # ── 顶部说明 ──
        tip = QLabel("引力 = 快速动作 (目标吸引 + 阶段速度标定) · 斥力 = 状态预测 (卡尔曼校正/滤波/接触判定) · "
                     "平衡偏差 |引力势−斥力势| → 0 = 无漂移 (V≈0)")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#8b949e; font-size:11px;")
        lay.addWidget(tip)

        row = QHBoxLayout()
        # ── 左: 引力标定 (快速动作) ──
        g_attr = QGroupBox("引力 Attraction — 快速动作")
        fa = QFormLayout(g_attr)
        self.sp_kp = self._mk_spin(layer.attr["Kp"], 0.1, 5.0, 0.05)
        fa.addRow("比例增益 Kp", self.sp_kp)
        self.sp_clip = self._mk_spin(layer.attr["u_clip"], 0.1, 1.0, 0.05)
        fa.addRow("前馈限幅 u_clip", self.sp_clip)
        fa.addRow("", QLabel("各阶段速度上限 (明确标定量)", styleSheet="color:#8b949e; font-size:10px;"))
        self.tbl = QTableWidget(len(layer.attr["stage_v_cap"]), 2)
        self.tbl.setHorizontalHeaderLabels(["阶段", "速度上限 m/s"])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        for i, (st, cap) in enumerate(layer.attr["stage_v_cap"].items()):
            it0 = QTableWidgetItem(st)
            it1 = QTableWidgetItem(f"{cap:.2f}")
            it1.setTextAlignment(Qt.AlignCenter)
            if st == stage:  # 当前阶段高亮
                it0.setBackground(QColor("#1f6feb")); it1.setBackground(QColor("#1f6feb"))
            self.tbl.setItem(i, 0, it0); self.tbl.setItem(i, 1, it1)
        self.tbl.setFixedHeight(200)
        fa.addRow(self.tbl)
        row.addWidget(g_attr, 3)

        # ── 中: 斥力标定 (状态预测) ──
        g_rep = QGroupBox("斥力 Repulsion — 状态预测")
        fr = QFormLayout(g_rep)
        self.sp_k = self._mk_spin(layer.rep["K_kalman"], 0.0, 1.0, 0.01)
        fr.addRow("卡尔曼增益 K", self.sp_k)
        self.sp_ema = self._mk_spin(layer.rep["res_ema"], 0.0, 1.0, 0.01)
        fr.addRow("残差 EMA α", self.sp_ema)
        self.sp_cg = self._mk_spin(layer.rep["contact_gain"], 0.5, 20.0, 0.5)
        fr.addRow("接触概率增益", self.sp_cg)
        self.sp_veto = self._mk_spin(layer.rep["veto_th"], 0.1, 10.0, 0.1)
        fr.addRow("否决阈值 veto_th", self.sp_veto)
        self.sp_kfb = self._mk_spin(layer.rep["k_fb"], 0.0, 3.0, 0.05)
        fr.addRow("反馈增益 k_fb", self.sp_kfb)
        lbl_stage = QLabel("当前阶段: " + stage,
                           styleSheet="color:#00d4aa; font-size:12px; font-weight:bold;")
        fr.addRow("", lbl_stage)
        row.addWidget(g_rep, 2)

        lay.addLayout(row)

        # ── 平衡点指示 ──
        g_eq = QGroupBox("⚖ 平衡点 (无漂移 V≈0)")
        fe = QVBoxLayout(g_eq)
        a = self.layer.attraction_potential(stage, 0.0)
        self.lbl_gap = QLabel("平衡偏差: —")
        self.lbl_gap.setStyleSheet("font-size:14px; font-weight:bold;")
        fe.addWidget(self.lbl_gap)
        self.bar = QProgressBar()
        self.bar.setRange(-100, 100)
        self.bar.setValue(0)
        self.bar.setFormat("")
        fe.addWidget(self.bar)
        hh = QHBoxLayout()
        hh.addWidget(QLabel("← 斥力↑ (状态修正强)", styleSheet="color:#8b949e; font-size:10px;"))
        hh.addStretch(1)
        hh.addWidget(QLabel("引力↑ (动作快) →", styleSheet="color:#8b949e; font-size:10px;"))
        fe.addLayout(hh)
        lay.addWidget(g_eq)

        # ── 底部按钮 ──
        btns = QHBoxLayout()
        self.btn_export = QPushButton("💾 导出标定建议 (reports/calibration_*.json)")
        self.btn_export.clicked.connect(self._export)
        self.btn_close = QPushButton("关闭")
        self.btn_close.clicked.connect(self.accept)
        btns.addWidget(self.btn_export)
        btns.addStretch(1)
        btns.addWidget(self.btn_close)
        lay.addLayout(btns)

        self._update_balance(stage, 0.0, 0.0, 0.0)

    def _mk_spin(self, val, lo, hi, step):
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setSingleStep(step)
        s.setDecimals(2)
        s.setValue(float(val))
        return s

    def _update_balance(self, stage, speed, residual, contact_p):
        """实时平衡指示: 引力势 vs 斥力势, 偏差映射到 [-1,1] → 进度条中心=平衡"""
        a = self.layer.attraction_potential(stage, speed)
        r = self.layer.repulsion_potential(residual, contact_p)
        g = a - r
        state = self.layer.equilibrium_state(g)
        self.lbl_gap.setText(f"引力势 {a:.2f} vs 斥力势 {r:.2f} · 偏差 {g:+.2f} → {state}")
        self.bar.setValue(int(max(-100, min(100, g * 100))))

    def _export(self):
        """导出标定建议 (回路外: 不改引擎)"""
        self.layer.attr["Kp"] = self.sp_kp.value()
        self.layer.attr["u_clip"] = self.sp_clip.value()
        self.layer.rep["K_kalman"] = self.sp_k.value()
        self.layer.rep["res_ema"] = self.sp_ema.value()
        self.layer.rep["contact_gain"] = self.sp_cg.value()
        self.layer.rep["veto_th"] = self.sp_veto.value()
        self.layer.rep["k_fb"] = self.sp_kfb.value()
        path = self.layer.export()
        QMessageBox.information(self, "🧮 标定层", f"标定建议已导出: {path}\n\n"
                                 "(回路外元层 — 引擎仍用源码常量, 需应用请改 calibration_layer.py 后重启)")
