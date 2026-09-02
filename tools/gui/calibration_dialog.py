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
        mb = QMessageBox(self)
        mb.setStyleSheet(_DARK)
        mb.setWindowTitle("🧮 标定层")
        mb.setText(f"标定建议已导出: {path}\n\n"
                   "(回路外元层 — 引擎仍用源码常量, 需应用请改 calibration_layer.py 后重启)")
        mb.exec_()


# ────────────────────────────────────────────────────────────
# 📋 标定表格 (2026-09-02 老倪: 标定层节点右键 → 可编辑表格, 交互编辑这些参数)
# ────────────────────────────────────────────────────────────
class CalibrationTableDialog(QDialog):
    """🧮 标定表格 — 全部标定参数一表编辑 (引力/斥力分组, 双击单元格改值)

    保存: 写回 src/lerobot/calibration/calibration_layer.py 常量 + 导出 json。
    引擎应用: 标定层是这些参数的标定来源, 保存后提示同步 (引擎常量在
    cognition.py STAGE_V_CAP — 如需立刻生效可同步修改, 不改变架构只改标定值)。
    """

    def __init__(self, layer, calib_path, parent=None):
        super().__init__(parent)
        self.layer = layer
        self.calib_path = calib_path
        self.setWindowTitle("🧮 标定表格 · 引力/斥力参数编辑")
        self.setStyleSheet(_DARK)
        self.resize(680, 560)
        lay = QVBoxLayout(self)

        tip = QLabel("双击单元格编辑数值 → 💾 保存 (写回 calibration_layer.py + 导出 reports/calibration_*.json)")
        tip.setStyleSheet("color:#8b949e; font-size:11px;")
        lay.addWidget(tip)

        self.tbl = QTableWidget(0, 3)
        self.tbl.setHorizontalHeaderLabels(["参数", "值", "说明"])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tbl.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.tbl.setEditTriggers(QTableWidget.DoubleClicked | QTableWidget.EditKeyPressed)
        lay.addWidget(self.tbl)

        btns = QHBoxLayout()
        self.btn_save = QPushButton("💾 保存 (写回标定层源码 + 导出)")
        self.btn_save.clicked.connect(self._save)
        self.btn_close = QPushButton("关闭")
        self.btn_close.clicked.connect(self.accept)
        btns.addWidget(self.btn_save)
        btns.addStretch(1)
        btns.addWidget(self.btn_close)
        lay.addLayout(btns)

        self._populate()

    def _add_row(self, key, value, desc, group):
        r = self.tbl.rowCount()
        self.tbl.insertRow(r)
        it_key = QTableWidgetItem(f"{group} · {key}")
        it_key.setFlags(it_key.flags() & ~Qt.ItemIsEditable)
        it_val = QTableWidgetItem(f"{value:.3f}" if isinstance(value, float) else str(value))
        it_val.setTextAlignment(Qt.AlignCenter)
        it_desc = QTableWidgetItem(desc)
        it_desc.setFlags(it_desc.flags() & ~Qt.ItemIsEditable)
        if group == "引力":
            it_key.setBackground(QColor("#1f6feb"))
        else:
            it_key.setBackground(QColor("#a371f7"))
        self.tbl.setItem(r, 0, it_key)
        self.tbl.setItem(r, 1, it_val)
        self.tbl.setItem(r, 2, it_desc)
        # 存 key 供保存回写
        it_val.setData(Qt.UserRole, (group, key))

    def _populate(self):
        a, r = self.layer.attr, self.layer.rep
        self._add_row("Kp", a["Kp"], "比例引导增益 (前馈加速器 Kp·(target−pos))", "引力")
        self._add_row("u_clip", a["u_clip"], "前馈限幅", "引力")
        self._add_row("safety_limit", a["safety_limit"], "安全执行边界限幅", "引力")
        for st, cap in a["stage_v_cap"].items():
            self._add_row(f"速度上限·{st}", cap, f"阶段「{st}」速度标定 (STAGE_V_CAP)", "引力")
        for st, vmin in a.get("stage_v_min", {}).items():
            self._add_row(f"最小速度·{st}", vmin, f"阶段「{st}」最小趋近速度 (STAGE_V_MIN)", "引力")
        self._add_row("K_kalman", r["K_kalman"], "状态校正增益 (卡尔曼)", "斥力")
        self._add_row("res_ema", r["res_ema"], "残差 EMA 滤波系数", "斥力")
        self._add_row("contact_gain", r["contact_gain"], "接触概率增益", "斥力")
        self._add_row("veto_th", r["veto_th"], "否决阈值 (残差超此值否决)", "斥力")
        self._add_row("k_fb", r["k_fb"], "反馈增益 (前馈+反馈相加)", "斥力")
        self._add_row("prior_A", r["prior_A"], "先验动力学状态转移", "斥力")

    def _save(self):
        """校验 → 更新 layer → 写回 calibration_layer.py 源码 → 导出 json"""
        import re
        try:
            for i in range(self.tbl.rowCount()):
                it = self.tbl.item(i, 1)
                grp, key = it.data(Qt.UserRole)
                val = float(it.text().strip())
                if grp == "引力":
                    if key.startswith("速度上限·"):
                        self.layer.attr["stage_v_cap"][key.replace("速度上限·", "")] = val
                    elif key.startswith("最小速度·"):
                        self.layer.attr["stage_v_min"][key.replace("最小速度·", "")] = val
                    else:
                        self.layer.attr[key] = val
                else:
                    self.layer.rep[key] = val
            # 写回 calibration_layer.py (标定层是这些参数的标定来源)
            src = open(self.calib_path, encoding="utf-8").read()
            for key, val in self.layer.attr["stage_v_cap"].items():
                src = re.sub(rf'("{key}": )[\d.]+', rf'\g<1>{val:.2f}', src)
            for key, val in self.layer.attr["stage_v_min"].items():
                src = re.sub(rf'("{key}": )[\d.]+', rf'\g<1>{val:.2f}', src)
            src = re.sub(r'("Kp": )[\d.]+', rf'\g<1>{self.layer.attr["Kp"]:.2f}', src)
            src = re.sub(r'("u_clip": )[\d.]+', rf'\g<1>{self.layer.attr["u_clip"]:.2f}', src)
            src = re.sub(r'("safety_limit": )[\d.]+', rf'\g<1>{self.layer.attr["safety_limit"]:.2f}', src)
            for key in ("K_kalman", "res_ema", "contact_gain", "veto_th", "k_fb", "prior_A"):
                src = re.sub(rf'("{key}": )[\d.]+', rf'\g<1>{self.layer.rep[key]:.2f}', src)
            open(self.calib_path, "w", encoding="utf-8").write(src)
            path = self.layer.export()
            mb = QMessageBox(self)
            mb.setStyleSheet(_DARK)
            mb.setWindowTitle("🧮 标定表格")
            mb.setText(f"✅ 已保存 {self.tbl.rowCount()} 个标定参数\n\n"
                       f"写回: {self.calib_path}\n导出: {path}\n\n"
                       f"引擎当前仍用 cognition.py 的 STAGE_V_CAP 常量 — 如需让新标定值在"
                       f"仿真中生效, 同步修改 cognition.py 对应值 (不改变架构, 只改标定值)。")
            mb.exec_()
        except Exception as e:
            mb = QMessageBox(self)
            mb.setStyleSheet(_DARK)
            mb.setWindowTitle("🧮 标定表格")
            mb.setText(f"保存失败: {e}\n(检查数值格式, 必须为数字)")
            mb.exec_()
