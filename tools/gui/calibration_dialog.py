# -*- coding: utf-8 -*-
"""calibration_dialog.py — 🧮 标定层 UI (2026-09-02 老倪)

引力/斥力二分超参数 + 平衡点 (Drifting Models 反称场思想):
  引力 (Attraction) = 快速动作 — Kp + 各阶段速度上限/下限
  斥力 (Repulsion)  = 状态预测 — K_kalman + 残差EMA + 接触增益 + 否决阈值
  平衡偏差 = 引力势 − 斥力势 (|偏差|→0 = 无漂移平衡)

应用即生效 (v3.4.5 闭环): 💾保存 = layer.apply_to_engine() 把标定值精确写回引擎
源码字面量 (parallel.py/cognition.py/state_space_sim.py) — 引擎每次 ▶运行 importlib
重新加载六层源码 → 下一次运行即用新标定值, 无需重启 GUI。镜像写 calibration_layer.py。
"""
import os

_REPO_HINT = ("src", "lerobot")


def _root_of(path):
    """从 calibration_layer.py / calibration_dialog.py 上溯定位仓库根 (探测式)"""
    d = os.path.dirname(os.path.abspath(path))
    while d != os.path.dirname(d):
        if os.path.isdir(os.path.join(d, *_REPO_HINT)) and \
           os.path.isdir(os.path.join(d, "tools", "gui")):
            return d
        d = os.path.dirname(d)
    return d


from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout,
                             QDoubleSpinBox, QSpinBox, QCheckBox, QComboBox,
                             QTableWidget, QTableWidgetItem, QLabel,
                             QPushButton, QProgressBar, QMessageBox, QHeaderView)

_DARK = ("QDialog { background:#0d1117; color:#e6edf3; } "
         "QLabel { color:#e6edf3; } QGroupBox { color:#00d4aa; border:1px solid #30363d; "
         "border-radius:6px; margin-top:10px; } QGroupBox::title { subcontrol-origin: margin; left:10px; padding:0 4px; } "
         "QDoubleSpinBox, QSpinBox, QComboBox { background:#161b22; color:#e6edf3; border:1px solid #30363d; border-radius:4px; padding:2px 6px; } "
         "QTableWidget { background:#161b22; color:#e6edf3; border:1px solid #30363d; gridline-color:#30363d; } "
         "QHeaderView::section { background:#21262d; color:#e6edf3; border:none; padding:4px; } "
         "QPushButton { background:#1f6feb; color:#fff; border:none; border-radius:5px; padding:8px 16px; font-size:13px; } "
         "QPushButton:hover { background:#388bfd; } QProgressBar { background:#161b22; border:1px solid #30363d; "
         "border-radius:4px; text-align:center; color:#e6edf3; } QProgressBar::chunk { background:#00d4aa; }")


class CalibrationDialog(QDialog):
    """🧮 标定层 — 引力/斥力/潜空间 三域标定面板 + 平衡点指示

    地图导航视角 (2026-09-03): 潜空间=世界模型预测流形 (地图), 引力/斥力/潜空间
    是该地图上的三类标定旋钮。"""

    def __init__(self, layer, stage="接近", gap=0.0, parent=None, calib_path=None):
        super().__init__(parent)
        self.layer = layer
        self.calib_path = calib_path
        self.setWindowTitle("🧮 标定层 · 引力/斥力/潜空间 (地图校准)")
        self.setStyleSheet(_DARK)
        self.setMinimumWidth(980)
        lay = QVBoxLayout(self)

        # ── 顶部说明 ──
        tip = QLabel("引力 = 快速动作 (目标吸引 + 阶段速度标定) · 斥力 = 状态预测 (卡尔曼校正/滤波/接触判定) · "
                     "潜空间 = 世界模型预测流形 (维度/类别/速度场 prior_A) · "
                     "平衡偏差 |引力势−斥力势| → 0 = 无漂移 (V≈0); 潜空间=流形地图, 世界模型=地图导航仪")
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

        # ── 右: 潜空间标定 (世界模型预测流形 — 地图几何) ──
        g_lat = QGroupBox("潜空间 Latent — 世界模型预测流形 (地图)")
        fl = QFormLayout(g_lat)
        self.sp_ldim = QSpinBox()
        self.sp_ldim.setRange(1, 16)
        self.sp_ldim.setValue(int(layer.lat.get("latent_dim", 4)))
        fl.addRow("潜空间维度 latent_dim", self.sp_ldim)
        self.cb_force = QCheckBox("力/接触通道进潜状态 (第4维=预测力)")
        self.cb_force.setChecked(bool(layer.lat.get("force_ch", 1)))
        fl.addRow("通道", self.cb_force)
        self.sp_pa = QDoubleSpinBox()
        self.sp_pa.setRange(0.5, 1.0)
        self.sp_pa.setSingleStep(0.05)
        self.sp_pa.setDecimals(2)
        self.sp_pa.setValue(float(layer.lat.get("prior_A", 1.0)))
        fl.addRow("速度场系数 prior_A", self.sp_pa)
        lbl_kind = QLabel(f"类别: {layer.lat.get('manifold_kind', '?')} / "
                          f"{layer.lat.get('flow_kind', '?')} (结构常数, 只读)")
        lbl_kind.setWordWrap(True)
        lbl_kind.setStyleSheet("color:#8b949e; font-size:10px;")
        fl.addRow("", lbl_kind)
        lbl_note = QLabel("观测流形 39D → 有效维由「🧮 潜空间」节点 PCA 实测校验")
        lbl_note.setWordWrap(True)
        lbl_note.setStyleSheet("color:#8b949e; font-size:10px;")
        fl.addRow("", lbl_note)
        row.addWidget(g_lat, 2)

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
        self.btn_export = QPushButton("💾 应用标定 (写回引擎源码, 下次运行生效)")
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
        """应用标定: 收集界面值 (含阶段上限表) → 写回引擎源码三文件 + 镜像 + 导出 json"""
        try:
            self.layer.attr["Kp"] = self.sp_kp.value()
            self.layer.attr["u_clip"] = self.sp_clip.value()
            self.layer.rep["K_kalman"] = self.sp_k.value()
            self.layer.rep["res_ema"] = self.sp_ema.value()
            self.layer.rep["contact_gain"] = self.sp_cg.value()
            self.layer.rep["veto_th"] = self.sp_veto.value()
            self.layer.rep["k_fb"] = self.sp_kfb.value()
            # 潜空间 (地图几何标定)
            self.layer.lat["latent_dim"] = int(self.sp_ldim.value())
            self.layer.lat["force_ch"] = 1 if self.cb_force.isChecked() else 0
            self.layer.lat["prior_A"] = float(self.sp_pa.value())
            # 阶段速度上限表 (双击单元格可编辑 → 一起应用)
            for i in range(self.tbl.rowCount()):
                st = self.tbl.item(i, 0).text()
                self.layer.attr["stage_v_cap"][st] = float(self.tbl.item(i, 1).text())
            files = self.layer.apply_to_engine(_root_of(self.calib_path or __file__))
            if self.calib_path:
                self.layer.apply_to_file(self.calib_path)
            path = self.layer.export()
            detail = "\n".join(f"  {f}: {','.join(ps)}" for f, ps in files.items())
            mb = QMessageBox(self)
            mb.setStyleSheet(_DARK)
            mb.setWindowTitle("🧮 标定层")
            mb.setText(f"✅ 标定已写入引擎源码\n{detail}\n\n"
                       f"引擎每次 ▶运行 重新加载六层源码 → 下一次运行即用新标定值 (无需重启 GUI)。\n"
                       f"镜像: {self.calib_path}\n导出: {path}")
            mb.exec_()
        except Exception as e:
            mb = QMessageBox(self)
            mb.setStyleSheet(_DARK)
            mb.setWindowTitle("🧮 标定层")
            mb.setText(f"应用标定失败: {e}")
            mb.exec_()


# ────────────────────────────────────────────────────────────
# 📋 标定表格 (2026-09-02 老倪: 标定层节点右键 → 可编辑表格, 交互编辑这些参数)
# ────────────────────────────────────────────────────────────
class CalibrationTableDialog(QDialog):
    """🧮 标定表格 — 全部标定参数一表编辑 (引力/斥力分组, 双击单元格改值)

    保存 (v3.4.5 闭环): layer.apply_to_engine() 把 21 个标定值精确写回引擎源码
    字面量 (parallel.py Kp/u_clip、cognition.py STAGE_V_CAP/MIN+veto/k_fb、
    state_space_sim.py 校正K/EMA/接触增益/安全限幅/先验A) + 镜像写
    calibration_layer.py + 导出 json。引擎每次 ▶运行 importlib 重新加载六层源码 →
    下一次运行即用新标定值, 无需重启 GUI。
    """

    def __init__(self, layer, calib_path, parent=None):
        super().__init__(parent)
        self.layer = layer
        self.calib_path = calib_path
        self.setWindowTitle("🧮 标定表格 · 引力/斥力参数编辑")
        self.setStyleSheet(_DARK)
        self.resize(680, 560)
        lay = QVBoxLayout(self)

        tip = QLabel("双击单元格编辑数值 → 💾 保存 (写回引擎源码 → 下次 ▶运行 生效 + 导出 json)")
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
        self.btn_save = QPushButton("💾 应用标定 (写回引擎源码, 下次 ▶运行 生效)")
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
        elif group == "潜空间":
            it_key.setBackground(QColor("#00a36c"))
        else:
            it_key.setBackground(QColor("#a371f7"))
        self.tbl.setItem(r, 0, it_key)
        self.tbl.setItem(r, 1, it_val)
        self.tbl.setItem(r, 2, it_desc)
        # 存 key 供保存回写
        it_val.setData(Qt.UserRole, (group, key))

    def _populate(self):
        a, r, l = self.layer.attr, self.layer.rep, self.layer.lat
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
        # 潜空间 (2026-09-03 地图几何标定: 维度/通道/速度场; 类别 flat-linear·const-vel 只读见面板)
        self._add_row("latent_dim", l["latent_dim"], "潜空间维度 (引擎 latent 4D=位置3+预测力1; 改潜维=重构卡尔曼, 谨慎)", "潜空间")
        self._add_row("state_dim", l["state_dim"], "观测流形维 (39D 视觉结构, 数据流形源空间)", "潜空间")
        self._add_row("force_ch", l["force_ch"], "力/接触通道进潜状态 (1=进)", "潜空间")
        self._add_row("prior_A", l["prior_A"], "潜流形速度场系数 (ODE 离散化; 写回 state_space_sim PriorDynamicsPredictor A=)", "潜空间")
        self._add_row("latent_scale", l["latent_scale"], "潜坐标尺度归一 (位置 m 与力 N 混维参考)", "潜空间")

    def _save(self):
        """校验 → 更新 layer → 写回引擎源码三文件 + calibration_layer.py 镜像 → 导出 json"""
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
                elif grp == "潜空间":
                    self.layer.lat[key] = int(val) if key in ("latent_dim", "state_dim", "force_ch") else val
                else:
                    self.layer.rep[key] = val
            # 🎯 引擎写回 (真生效) + 镜像 + 导出 — 锚点未命中会抛 ValueError (不静默)
            files = self.layer.apply_to_engine(_root_of(self.calib_path))
            self.layer.apply_to_file(self.calib_path)
            path = self.layer.export()
            detail = "\n".join(f"  {f}: {','.join(ps)}" for f, ps in files.items())
            mb = QMessageBox(self)
            mb.setStyleSheet(_DARK)
            mb.setWindowTitle("🧮 标定表格")
            mb.setText(f"✅ 已应用 {self.tbl.rowCount()} 个标定参数到引擎\n\n{detail}\n\n"
                       f"引擎每次 ▶运行 重新加载六层源码 → 下一次运行即用新标定值 (无需重启 GUI)。\n"
                       f"当前若在仿真中, 停止后重跑。\n镜像: {self.calib_path}\n导出: {path}")
            mb.exec_()
        except Exception as e:
            mb = QMessageBox(self)
            mb.setStyleSheet(_DARK)
            mb.setWindowTitle("🧮 标定表格")
            mb.setText(f"应用标定失败: {e}\n(检查数值格式, 必须为数字; 锚点未命中=引擎源码已改动)")
            mb.exec_()
