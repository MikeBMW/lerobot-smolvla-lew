#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Z-MAX Simulink Scope 示波器模块
对标 Simulink Scope: 深色网格 + 多通道波形 + 图例
核心功能: 直接对比 基础模型 vs 微调模型 的动作输出曲线

用法:
  - 从 SimulinkModule 工具栏打开 (📊 Scope 对比)
  - 加载基础模型 + 微调模型 → 同一测试输入 → 双曲线叠加
  - 绿色虚线 = 专家动作真值 (参考)
  - 右上角实时显示 MSE / 成功率 / 提升%
"""
import json, math, os, time, glob
from pathlib import Path
import numpy as np

from PyQt5.QtCore import Qt, QTimer, QPointF
from PyQt5.QtGui import (QPainter, QColor, QPen, QFont, QLinearGradient)
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QDialog, QLabel,
                             QPushButton, QComboBox, QFileDialog, QMessageBox,
                             QDialogButtonBox, QTextEdit, QFrame)

# 示波器配色 (深色主题)
BG_TOP = QColor("#0d1117")
BG_BOT = QColor("#161b22")
GRID = QColor("#21262d")
GRID_MAJOR = QColor("#30363d")
COLORS = {
    "base": QColor("#f85149"),      # 基础模型 (红)
    "ft": QColor("#00d4aa"),        # 微调模型 (青)
    "gt": QColor("#3fb950"),        # 专家真值 (绿)
    "act": QColor("#58a6ff"),       # ⚔️ ACT 对比 (蓝)
    "smolvla": QColor("#d29922"),   # ⚔️ SmolVLA 对比 (橙)
    "grid": GRID,
    "text": QColor("#8b949e"),
}


class ScopeWidget(QWidget):
    """自绘示波器: 多通道波形叠加 + 网格 + 图例"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.series = {}   # name -> (np.array y, QColor, dashed?)
        self.setMinimumSize(560, 300)
        self.setStyleSheet("background:#0d1117;")

    def set_series(self, series):
        """series: {name: (y_values, color_name, dashed)}"""
        self.series = series
        self.update()

    def clear(self):
        self.series = {}
        self.update()

    def _y_range(self):
        ys = [v[0] for v in self.series.values() if len(v[0]) > 0]
        if not ys:
            return -1.0, 1.0
        all_v = np.concatenate(ys)
        lo, hi = float(np.min(all_v)), float(np.max(all_v))
        span = max(hi - lo, 0.5)
        return lo - span * 0.1, hi + span * 0.1

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        # 背景
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0, BG_TOP)
        grad.setColorAt(1, BG_BOT)
        p.fillRect(0, 0, w, h, grad)

        # 网格 (12x8)
        p.setPen(QPen(GRID, 1))
        for i in range(1, 12):
            x = i * w / 12
            p.drawLine(int(x), 0, int(x), h)
        for j in range(1, 8):
            y = j * h / 8
            p.drawLine(0, int(y), w, int(y))
        # 中线
        p.setPen(QPen(GRID_MAJOR, 1))
        p.drawLine(0, h // 2, w, h // 2)

        # 绘制各通道
        y_lo, y_hi = self._y_range()
        if y_hi <= y_lo:
            y_hi = y_lo + 1
        legend_x = 10
        for name, (data, cname, dashed) in self.series.items():
            if len(data) < 2:
                continue
            color = COLORS.get(cname, COLORS["base"])
            pen = QPen(color, 2)
            if dashed:
                pen.setStyle(Qt.DashLine)
            p.setPen(pen)
            n = len(data)
            path = None
            prev = None
            for i in range(n):
                x = i * w / (n - 1)
                y = h - (float(data[i]) - y_lo) / (y_hi - y_lo) * (h - 20) - 10
                pt = QPointF(x, y)
                if prev is not None:
                    p.drawLine(prev, pt)
                prev = pt
            # 图例
            p.setPen(color)
            p.drawRect(legend_x, 8, 14, 10)
            p.setPen(COLORS["text"])
            p.setFont(QFont("Consolas", 9))
            p.drawText(legend_x + 18, 17, name)
            legend_x += 18 + p.fontMetrics().horizontalAdvance(name) + 16

        p.end()


class ScopeCompareDialog(QDialog):
    """Scope 对比: 基础 vs 微调 模型动作输出"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📊 Scope 示波器 — 新老模型对比")
        self.setMinimumSize(820, 620)
        self.setStyleSheet("QDialog { background:#0d1117; }")
        self._base_policy = None
        self._ft_policy = None
        self._base_pp = None
        self._ft_pp = None
        self._states = None
        self._gt = None
        self._imgs = None
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)

        # ═══ 控制栏 ═══
        ctrl = QHBoxLayout()
        ctrl.setSpacing(8)

        self.cmb_base = QComboBox()
        self.cmb_base.setStyleSheet("background:#161b22;color:#c9d1d9;border:1px solid #30363d;border-radius:4px;padding:4px 8px;")
        self.cmb_base.addItem("基础模型 (act_metaworld)", "outputs/train/act_metaworld/checkpoints/000300/pretrained_model")
        ctrl.addWidget(QLabel("基础:"))
        ctrl.addWidget(self.cmb_base, 1)

        self.cmb_ft = QComboBox()
        self.cmb_ft.setStyleSheet("background:#161b22;color:#c9d1d9;border:1px solid #30363d;border-radius:4px;padding:4px 8px;")
        self._scan_models()
        ctrl.addWidget(QLabel("微调:"))
        ctrl.addWidget(self.cmb_ft, 1)

        btn_load = QPushButton("▶ 加载并对比")
        btn_load.setStyleSheet("background:#00d4aa;color:#0d1117;font-weight:700;border:none;border-radius:4px;padding:6px 16px;")
        btn_load.clicked.connect(self._run_compare)
        ctrl.addWidget(btn_load)

        btn_export = QPushButton("💾 导出PNG")
        btn_export.setStyleSheet("background:#161b22;color:#58a6ff;border:1px solid #30363d;border-radius:4px;padding:6px 12px;")
        btn_export.clicked.connect(self._export_png)
        ctrl.addWidget(btn_export)

        outer.addLayout(ctrl)

        # ═══ 示波器 ═══
        self.scope = ScopeWidget()
        outer.addWidget(self.scope, 1)

        # ═══ 指标栏 ═══
        self.metrics = QLabel("⏳ 等待加载模型...")
        self.metrics.setStyleSheet("color:#8b949e;font-size:12px;padding:6px;background:#161b22;border-radius:4px;font-family:Consolas;")
        outer.addWidget(self.metrics)

        # ═══ 底部说明 ═══
        note = QLabel("🔴 基础模型动作  🟢 微调模型动作  ┄┄ 专家真值(参考)   |  X=帧序列  Y=动作值(各维度叠加)")
        note.setStyleSheet("color:#484f58;font-size:10px;")
        outer.addWidget(note)

    def _scan_models(self):
        """扫描本地所有训练产物 (微调候选)"""
        proj = Path(__file__).parent.parent.parent
        out = proj / "outputs" / "train"
        if not out.exists():
            return
        for d in sorted(out.iterdir()):
            ckpts = sorted([c for c in (d / "checkpoints").iterdir() if c.name != "last"]) if (d / "checkpoints").exists() else []
            if ckpts:
                latest = ckpts[-1]
                self.cmb_ft.addItem(f"{d.name} ({latest.name})", str(latest / "pretrained_model"))

    def _load_test_data(self):
        """加载测试数据 (同 act_compare)"""
        proj = Path(__file__).parent.parent.parent
        from lerobot.datasets.lerobot_dataset import LeRobotDataset
        ds = LeRobotDataset("lerobot/pusht", root=str(proj / "data" / "metaworld_act"))
        n = len(ds)
        step = max(1, n // 60)
        idxs = list(range(0, n, step))[:60]
        states, actions, imgs = [], [], []
        for i in idxs:
            item = ds[i]
            states.append(item["observation.state"].numpy().astype(np.float32))
            actions.append(item["action"].numpy().astype(np.float32))
            imgs.append(item["observation.image"].numpy().astype(np.float32))
        self._states = np.stack(states)
        self._gt = np.stack(actions)
        self._imgs = np.stack(imgs)

    def _load_policy(self, ckpt_path):
        from lerobot.policies.act.modeling_act import ACTPolicy
        from lerobot.policies import make_pre_post_processors
        import torch
        policy = ACTPolicy.from_pretrained(ckpt_path).cuda().eval()
        _, post = make_pre_post_processors(policy_cfg=policy.config, pretrained_path=str(ckpt_path))
        return policy, post

    def _run_compare(self):
        import torch
        base_path = self.cmb_base.currentData()
        ft_path = self.cmb_ft.currentData()
        if not base_path or not ft_path:
            QMessageBox.warning(self, "Scope", "请选择模型")
            return
        self.metrics.setText("⏳ 加载模型...")
        self.metrics.repaint()
        try:
            if self._states is None:
                self._load_test_data()
            self._base_policy, self._base_pp = self._load_policy(base_path)
            self.metrics.setText("⏳ 基础模型已加载, 加载微调...")
            self.metrics.repaint()
            self._ft_policy, self._ft_pp = self._load_policy(ft_path)
            self.metrics.setText("⏳ 推理对比中...")
            self.metrics.repaint()

            base_preds, ft_preds, base_mse, ft_mse, hits_b, hits_f = [], [], [], [], 0, 0
            for i in range(len(self._states)):
                batch = {
                    "observation.state": torch.from_numpy(self._states[i]).float().cuda().unsqueeze(0),
                    "observation.image": torch.from_numpy(self._imgs[i]).float().cuda().unsqueeze(0),
                }
                gt = self._gt[i]
                out_b = self._base_pp(self._base_policy.select_action(batch))
                out_f = self._ft_pp(self._ft_policy.select_action(batch))
                pb = np.asarray(out_b[0].cpu().numpy()).flatten()
                pf = np.asarray(out_f[0].cpu().numpy()).flatten()
                base_preds.append(pb[: len(gt)])
                ft_preds.append(pf[: len(gt)])
                mb = float(np.mean((pb[: len(gt)] - gt) ** 2))
                mf = float(np.mean((pf[: len(gt)] - gt) ** 2))
                base_mse.append(mb)
                ft_mse.append(mf)
                if mb < 0.05:
                    hits_b += 1
                if mf < 0.05:
                    hits_f += 1

            # 绘制: 取动作第1维 (或均值) 展示
            base_curve = np.array([p[0] if len(p) > 0 else 0 for p in base_preds])
            ft_curve = np.array([p[0] if len(p) > 0 else 0 for p in ft_preds])
            gt_curve = np.array([g[0] for g in self._gt])
            self.scope.set_series({
                "基础模型": (base_curve, "base", False),
                "微调模型": (ft_curve, "ft", False),
                "专家真值": (gt_curve, "gt", True),
            })

            mse_b = float(np.mean(base_mse))
            mse_f = float(np.mean(ft_mse))
            imp = (mse_b - mse_f) / max(mse_b, 1e-9) * 100
            sr_b = hits_b / len(base_mse) * 100
            sr_f = hits_f / len(ft_mse) * 100
            verdict = "✅ 提升" if imp > 0 else "❌ 未提升"
            color = "#2ea043" if imp > 0 else "#f85149"
            self.metrics.setText(
                f"<span style='color:{color};font-weight:700'>{verdict}</span> "
                f"MSE: 基础 {mse_b:.2f} → 微调 {mse_f:.2f} ({imp:+.1f}%) | "
                f"成功率: {sr_b:.0f}% → {sr_f:.0f}% | "
                f"测试帧: {len(self._states)}")
        except Exception as ex:
            self.metrics.setText(f"❌ 对比失败: {ex}")
            import traceback
            traceback.print_exc()

    def _export_png(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出示波器图", "scope_compare.png", "PNG (*.png)")
        if not path:
            return
        pm = self.scope.grab()
        pm.save(path)
        self.metrics.setText(f"💾 已导出: {path}")


# ════════════════════════════════════════════════════════════════
# 📊 FlowScopeDialog — 全流程 Scope 示波器 (Simulink Scope 对标)
# 老倪 2026-08-04: "需要最后出一个结果报告, 类似simulink的scope示波器, 能看到效果"
# 用法: 画布流程末尾接「📊 Scope 示波器」节点 → 训练完成后双击它 → 看 loss 波形
# ════════════════════════════════════════════════════════════════
class FlowScopeDialog(QDialog):
    """📊 Scope 示波器 — 训练效果 (loss 曲线 + 指标)"""

    _SS_DARK = ("QDialog { background:#0d1117; }"
                "QLabel { color:#e6edf3; }"
                "QPushButton { background:#21262d; color:#e6edf3; border:1px solid #30363d;"
                " border-radius:6px; padding:6px 16px; font-size:12px; }"
                "QPushButton:hover { border-color:#00d4aa; }")

    def __init__(self, module, parent=None):
        super().__init__(parent)
        self.module = module
        self.setWindowTitle("📊 Scope 示波器 — 训练效果 (loss)")
        self.setMinimumSize(780, 540)
        self.setStyleSheet(self._SS_DARK)
        self._build()
        self._load_data()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)
        title = QLabel("📊 Scope 示波器 · 训练 loss 曲线 (Simulink Scope 对标)")
        title.setStyleSheet("font-size:14px; font-weight:700; color:#e6edf3;")
        root.addWidget(title)
        self.lbl_metrics = QLabel("加载中…")
        self.lbl_metrics.setStyleSheet("color:#8b949e; font-size:11px;")
        root.addWidget(self.lbl_metrics)
        self.scope = ScopeWidget()
        root.addWidget(self.scope, 1)
        btns = QHBoxLayout()
        self.btn_export = QPushButton("💾 导出 PNG")
        self.btn_close = QPushButton("❌ 关闭")
        self.btn_export.clicked.connect(self._export_png)
        self.btn_close.clicked.connect(self.accept)
        btns.addStretch(1)
        btns.addWidget(self.btn_export)
        btns.addWidget(self.btn_close)
        root.addLayout(btns)

    def _load_data(self):
        curve = getattr(self.module, "_train_curve", None) or []
        if not curve:
            self.scope.set_series({})
            self.lbl_metrics.setText("⚠️ 暂无训练曲线 — 点「▶ 运行」训练完成后自动出波形")
            self.btn_export.setEnabled(False)
            return
        ys = np.array([l for _, l in curve])
        first, last = float(ys[0]), float(ys[-1])
        drop = first - last
        pct = (drop / first * 100) if first else 0.0
        self.scope.set_series({"loss": (ys, "ft", False)})
        step_w = (curve[1][0] - curve[0][0]) if len(curve) > 1 else 1
        self.lbl_metrics.setText(
            f"📈 loss: {first:.3f} → {last:.3f} (↓{drop:.3f}, {pct:+.1f}%) · "
            f"采样 {len(curve)} 点 · 每 {step_w} 步一点")

    def _export_png(self):
        root = self.module._repo_root()
        out_dir = os.path.join(root, "reports")
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"scope_loss_{time.strftime('%Y%m%d_%H%M%S')}.png")
        self.scope.grab().save(path)
        mb = QMessageBox(self)
        mb.setWindowTitle("导出")
        mb.setText(f"已保存: {path}")
        mb.setStyleSheet("QMessageBox{background:#0d1117} QLabel{color:#e6edf3;}"
                         "QPushButton{background:#21262d;color:#e6edf3;border:1px solid #30363d;"
                         "border-radius:6px;padding:6px 18px;}")
        mb.addButton("好的", QMessageBox.AcceptRole)
        mb.exec_()


class BarCompareWidget(QWidget):
    """⚔️ 指标对比条形图: 每指标两模型横向条 (ACT 蓝 vs SmolVLA 橙)"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.data = []   # [(指标名, act值, smol值, lower_better)]
        self.setMinimumSize(560, 190)

    def set_data(self, rows):
        self.data = rows
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor("#0d1117"))
        if not self.data:
            p.setPen(QColor("#8b949e"))
            p.drawText(10, h // 2, "⚠️ 无对比数据 — 先 ▶ 运行训练两模型")
            p.end()
            return
        row_h = h / max(len(self.data), 1)
        ACT_C, SML_C = QColor("#58a6ff"), QColor("#d29922")
        for i, (name, av, sv, lower) in enumerate(self.data):
            y0 = i * row_h
            p.setPen(QColor("#c9d1d9"))
            p.setFont(QFont("Consolas", 9))
            p.drawText(8, y0 + 14, f"{name}")
            # 条区: x 从 150 到 w-90, 两模型各一条
            bx, bw = 150, w - 250
            vmax = max(abs(av), abs(sv), 1e-9)
            a_len = abs(av) / vmax * bw
            s_len = abs(sv) / vmax * bw
            p.fillRect(bx, y0 + 4, int(a_len), 10, ACT_C)
            p.fillRect(bx, y0 + 18, int(s_len), 10, SML_C)
            p.setPen(QColor("#8b949e"))
            p.drawText(bx + int(a_len) + 6, y0 + 13, f"{av:.3g}")
            p.drawText(bx + int(s_len) + 6, y0 + 27, f"{sv:.3g}")
            # 胜出标记 (好值绿)
            if lower:
                winner = "ACT" if av < sv else "SmolVLA"
            else:
                winner = "ACT" if av > sv else "SmolVLA"
            p.setPen(QColor("#2ea043") if (av != sv) else QColor("#8b949e"))
            p.drawText(w - 66, y0 + 20, f"✓ {winner}" if av != sv else "=")
        p.setPen(QColor("#8b949e"))
        p.setFont(QFont("Consolas", 8))
        p.drawText(8, h - 4, "■ ACT (#58a6ff)   ■ SmolVLA (#d29922)   · 好值标绿 ✓")
        p.end()


class ModelCompareDialog(QDialog):
    """⚔️ ACT vs SmolVLA 对比 Scope (2026-08-04 老倪需求)
    图表: ① 训练 loss 双折线 (速度/收敛对比) ② 五指标条形图
          (训练速度/精确度MSE/成功率/鲁棒性/延迟) ③ 对比表
    数据源: reports/model_compare_<ts>.json (tools/compare_models.py 生成)
    """

    def __init__(self, module, parent=None):
        super().__init__(parent)
        self.module = module
        self.setWindowTitle("⚔️ ACT vs SmolVLA 对比 · 统一 metaworld 数据集")
        self.setMinimumSize(720, 620)
        self.setStyleSheet("QDialog{background:#0d1117;}")
        root = QVBoxLayout(self)

        self.lbl_head = QLabel("⚔️ ACT vs SmolVLA 模型对比")
        self.lbl_head.setStyleSheet("color:#a371f7;font-size:15px;font-weight:700;")
        root.addWidget(self.lbl_head)

        self.lbl_note = QLabel("")
        self.lbl_note.setStyleSheet("color:#8b949e;font-size:11px;")
        root.addWidget(self.lbl_note)

        self.scope = ScopeWidget(self)
        self.scope.setMinimumHeight(200)
        root.addWidget(self.scope)

        self.bars = BarCompareWidget(self)
        root.addWidget(self.bars)

        self.table = QTextEdit()
        self.table.setReadOnly(True)
        self.table.setMinimumHeight(110)
        self.table.setStyleSheet("background:#0d1117; color:#c9d1d9; border:1px solid #1e2740;"
                                 "font-family:Consolas; font-size:12px;")
        root.addWidget(self.table)

        btns = QHBoxLayout()
        self.btn_export = QPushButton("💾 导出 PNG")
        self.btn_close = QPushButton("❌ 关闭")
        self.btn_export.clicked.connect(self._export_png)
        self.btn_close.clicked.connect(self.accept)
        btns.addStretch(1)
        btns.addWidget(self.btn_export)
        btns.addWidget(self.btn_close)
        root.addLayout(btns)

        self._load_data()

    def _latest(self):
        import glob
        root = self.module._repo_root() if hasattr(self.module, "_repo_root") else "."
        files = sorted(glob.glob(os.path.join(root, "reports", "model_compare_*.json")))
        return json.load(open(files[-1])) if files else None

    def _load_data(self):
        d = self._latest()
        if not d:
            self.lbl_note.setText("⚠️ 无对比结果 — 点「▶ 运行」依次训练 ACT + SmolVLA, 完成后自动生成对比报告")
            self.scope.set_series({})
            self.bars.set_data([])
            self.table.setPlainText("无对比数据\n\n运行方式: 画布点「▶ 运行」→ 训练两模型 → 本窗口自动有图表")
            self.btn_export.setEnabled(False)
            return
        m = d.get("models", {})
        act = m.get("act", {})
        sml = m.get("smolvla_lew", {})
        self.lbl_note.setText(
            f"数据集: {d.get('dataset', 'metaworld_act')} · 测试 {d.get('frames', 0)} 帧 · "
            f"时间 {d.get('ts', '')} · ♻ 同数据/同机评估 (4060)")
        # ① loss 双折线
        series = {}
        c_act, c_sml = act.get("curve", []), sml.get("curve", [])
        if c_act:
            series["ACT loss"] = (np.array([l for _, l in c_act], dtype=float), "act", False)
        if c_sml:
            series["SmolVLA loss"] = (np.array([l for _, l in c_sml], dtype=float), "smolvla", False)
        self.scope.set_series(series)
        # ② 五指标条形
        rows = []
        for name, key, lower in [("训练速度 step/s", "step_s", False),
                                 ("动作 MSE", "action_mse", True),
                                 ("成功率 %", "success_rate", False),
                                 ("鲁棒性 std", "robustness_std", True),
                                 ("推理延迟 ms", "latency_ms", True)]:
            av = act.get(key, 0.0) if act else 0.0
            sv = sml.get(key, 0.0) if sml else 0.0
            if key == "success_rate":
                av, sv = av * 100, sv * 100
            rows.append((name, av, sv, lower))
        self.bars.set_data(rows)
        # ③ 表格
        lines = [f"{'维度':<14}{'ACT':>14}{'SmolVLA':>14}{'胜出':>10}"]
        for name, key, lower, fmt in [("训练速度 step/s", "step_s", False, "{:.2f}"),
                                      ("动作 MSE", "action_mse", True, "{:.4f}"),
                                      ("成功率 %", "success_rate", False, "{:.1f}"),
                                      ("鲁棒性 std", "robustness_std", True, "{:.4f}"),
                                      ("推理延迟 ms", "latency_ms", True, "{:.1f}")]:
            av = act.get(key, float("nan")) if act else float("nan")
            sv = sml.get(key, float("nan")) if sml else float("nan")
            if key == "success_rate":
                av, sv = av * 100, sv * 100
            if lower:
                win = "ACT" if av < sv else ("SmolVLA" if sv < av else "=")
            else:
                win = "ACT" if av > sv else ("SmolVLA" if sv > av else "=")
            a_txt = fmt.format(av) if av == av else "-"
            s_txt = fmt.format(sv) if sv == sv else "-"
            lines.append(f"{name:<14}{a_txt:>14}{s_txt:>14}{win:>10}")
        self.table.setPlainText("\n".join(lines))

    def _export_png(self):
        root = self.module._repo_root() if hasattr(self.module, "_repo_root") else "."
        out_dir = os.path.join(root, "reports")
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"compare_scope_{time.strftime('%Y%m%d_%H%M%S')}.png")
        self.grab().save(path)
        mb = QMessageBox(self)
        mb.setWindowTitle("导出")
        mb.setText(f"已保存: {path}")
        mb.setStyleSheet("QMessageBox{background:#0d1117} QLabel{color:#e6edf3;}"
                         "QPushButton{background:#21262d;color:#e6edf3;border:1px solid #30363d;"
                         "border-radius:6px;padding:6px 18px;}")
        mb.addButton("好的", QMessageBox.AcceptRole)
        mb.exec_()
