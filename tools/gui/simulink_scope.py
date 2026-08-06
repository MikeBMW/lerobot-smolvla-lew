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

# 示波器配色 (🎨 主题: light=浅色 Simulink/CANoe 风, dark=原深色; 由 simulink_module.switch_theme 同步)
CUR_THEME = "light"
_SCOPE_THEMES = {
    "light": {"bg_top": "#f6f8fa", "bg_bot": "#ffffff", "grid": "#e9edf2", "grid_major": "#b6bdc7",
              "panel": "#f6f8fa", "input": "#e9edf2", "border": "#d0d7de", "text": "#24292f",
              "text2": "#57606a", "btn": "#e9edf2", "hover": "#dbe9ff"},
    "dark": {"bg_top": "#161b22", "bg_bot": "#0d1117", "grid": "#1e2740", "grid_major": "#30363d",
             "panel": "#0d1117", "input": "#14181f", "border": "#1e2740", "text": "#c9d1d9",
             "text2": "#8b949e", "btn": "#21262d", "hover": "#1a2230"},
}


def _st():
    return _SCOPE_THEMES.get(CUR_THEME, _SCOPE_THEMES["light"])


def _qss(ss):
    """🎨 按当前主题映射 QSS 颜色 (dark 时把浅色值换成深色值, light 原样)"""
    if CUR_THEME == "dark":
        m = {"#f6f8fa": "#0d1117", "#ffffff": "#161b22", "#e9edf2": "#14181f",
             "#d0d7de": "#1e2740", "#b6bdc7": "#30363d", "#24292f": "#c9d1d9",
             "#1f2328": "#e6edf3", "#57606a": "#8b949e", "#484f58": "#8b949e",
             "#dbe9ff": "#1a2230"}
        for k, v in m.items():
            ss = ss.replace(k, v)
    return ss


BG_TOP = QColor(_st()["bg_top"])
BG_BOT = QColor(_st()["bg_bot"])
GRID = QColor(_st()["grid"])
GRID_MAJOR = QColor(_st()["grid_major"])
COLORS = {
    "base": QColor("#f85149"),      # 基础模型 (红)
    "ft": QColor("#00d4aa"),        # 微调模型 (青)
    "gt": QColor("#3fb950"),        # 专家真值 (绿)
    "act": QColor("#58a6ff"),       # ⚔️ ACT 对比 (蓝)
    "smolvla": QColor("#d29922"),   # ⚔️ SmolVLA 对比 (橙)
    "smolvla_lew": QColor("#a371f7"),  # 🔬 SmolVLA+LEW 对比 (紫)
    "grid": GRID,
    "text": QColor("#57606a"),
}


class ScopeWidget(QWidget):
    """自绘示波器: 多通道波形叠加 + 网格 + 图例"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.series = {}   # name -> (xs, y, QColor, dashed?) — xs=None 时用索引 (兼容旧格式)
        self.setMinimumSize(560, 300)
        self.setStyleSheet(_qss("background:#f6f8fa;"))
        # 🔍 缩放/平移 (2026-08-05 老倪: "scope的波形, 大小要能够缩放, 现在动不了, UI不好")
        self._y_lo_manual = None   # 手动缩放后的 y 范围 (None=自动)
        self._y_hi_manual = None
        self._drag_last = None     # 拖拽平移起点 (y 值)

    def set_series(self, series):
        """series: {name: (xs, y, color_name, dashed)} — xs=None 时 x 轴用索引 (旧格式兼容)"""
        self.series = series
        self.update()

    def clear(self):
        self.series = {}
        self.update()

    # ── 🔍 交互: 滚轮缩放 / 拖拽平移 / 双击复位 (Simulink Scope 风格) ──
    def _y_range(self):
        ys = [v[1] if len(v) >= 2 else v[0] for v in self.series.values() if len(v[0]) > 0]
        if not ys:
            return -1.0, 1.0
        all_v = np.concatenate(ys)
        lo, hi = float(np.min(all_v)), float(np.max(all_v))
        span = max(hi - lo, 0.5)
        auto_lo, auto_hi = lo - span * 0.1, hi + span * 0.1
        if self._y_lo_manual is None:
            return auto_lo, auto_hi
        return self._y_lo_manual, self._y_hi_manual

    def wheelEvent(self, ev):
        """滚轮: 以鼠标位置为中心缩放 y 轴 (up=放大 1.25x, down=缩小 0.8x)"""
        lo, hi = self._y_range()
        span = hi - lo
        if span <= 0:
            return
        # 鼠标 y → 数据值 (缩放中心)
        h = self.height()
        frac = 1.0 - (ev.pos().y() / h) if h > 0 else 0.5
        center = lo + frac * span
        factor = 1.25 if ev.angleDelta().y() > 0 else 0.8
        new_span = span / factor
        # 限制缩放范围: 0.01x ~ 100x 原始
        self._y_lo_manual = center - new_span / 2
        self._y_hi_manual = center + new_span / 2
        self.update()
        ev.accept()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MiddleButton:
            # 🖱 中键拖动平移 (2026-08-05 老倪: "scope 无法用鼠标中键拖动, 改" —
            #   Simulink Scope 惯例: 滚轮缩放 + 中键平移; 未缩放过也直接可拖
            if self._y_lo_manual is None:
                lo, hi = self._y_range()
                self._y_lo_manual, self._y_hi_manual = lo, hi
            self._drag_last = ev.pos()
            self.setCursor(Qt.ClosedHandCursor)
        elif ev.button() == Qt.LeftButton:
            self._drag_last = ev.pos()
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._drag_last is not None and self._y_lo_manual is not None:
            lo, hi = self._y_range()
            span = hi - lo
            h = self.height()
            if h > 0:
                dy = ev.pos().y() - self._drag_last.y()
                dval = dy * span / h
                self._y_lo_manual += dval
                self._y_hi_manual += dval
                self._drag_last = ev.pos()
                self.update()
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        self._drag_last = None
        self.setCursor(Qt.ArrowCursor)
        super().mouseReleaseEvent(ev)

    def mouseDoubleClickEvent(self, ev):
        """双击: 复位自动范围"""
        self.fit_all()
        super().mouseDoubleClickEvent(ev)

    def fit_all(self):
        """🌐 全局适配: 清除手动缩放/平移 → 自动范围显示全部曲线
        (2026-08-05 老倪: 鼠标缩放后曲线找不到, 需要全局适配看全图)"""
        self._y_lo_manual = None
        self._y_hi_manual = None
        self._drag_last = None
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        # 背景
        grad = QLinearGradient(0, 0, 0, h)
        t = _st()  # 🎨 主题动态取色
        grad.setColorAt(0, QColor(t["bg_top"]))
        grad.setColorAt(1, QColor(t["bg_bot"]))
        p.fillRect(0, 0, w, h, grad)

        # 网格 (12x8)
        p.setPen(QPen(QColor(t["grid"]), 1))
        for i in range(1, 12):
            x = i * w / 12
            p.drawLine(int(x), 0, int(x), h)
        for j in range(1, 8):
            y = j * h / 8
            p.drawLine(0, int(y), w, int(y))
        # 中线
        p.setPen(QPen(QColor(t["grid_major"]), 1))
        p.drawLine(0, h // 2, w, h // 2)

        # 📐 坐标轴 (2026-08-05 老倪: "loss曲线为什么没有横纵坐标" — Simulink Scope 风格:
        #   x 轴底部 step 刻度, y 轴左侧 loss 值刻度)
        y_lo, y_hi = self._y_range()
        if y_hi <= y_lo:
            y_hi = y_lo + 1
        ax_font = QFont("Consolas", 8)
        p.setFont(ax_font)
        fm = p.fontMetrics()
        # x 轴: step 刻度 (底部, 5 等分; 真实 step 范围)
        x_min, x_max = None, None
        for name, val in self.series.items():
            xs = val[0] if len(val) >= 2 else None
            if xs is not None and len(xs) >= 2:
                x_min = float(xs[0]) if x_min is None else min(x_min, float(xs[0]))
                x_max = float(xs[-1]) if x_max is None else max(x_max, float(xs[-1]))
        if x_max is not None and x_max > x_min:
            for k in range(5):
                xi = int(k * w / 4)
                step_val = int(round(x_min + k * (x_max - x_min) / 4))
                p.setPen(QColor(t["text2"]))
                p.drawText(xi + 3, h - 4, str(step_val))
                p.setPen(QPen(QColor(t["grid_major"]), 1))
                p.drawLine(xi, h - 14, xi, h - 10)
        # x 轴标签 (含含义)
        p.setPen(QColor(t["text2"]))
        p.drawText(w - 78, h - 4, "step (训练步数)")
        # y 轴: loss 值刻度 (左侧, 5 等分)
        for k in range(5):
            yi = int(k * h / 4)
            val = y_hi - k * (y_hi - y_lo) / 4
            p.setPen(QColor(t["text2"]))
            p.drawText(4, yi - 3, f"{val:.2f}")
            p.setPen(QPen(QColor(t["grid_major"]), 1))
            p.drawLine(0, yi, 6, yi)
        # y 轴标签 (2026-08-05: 左下角, 含单位+含义: loss = 动作预测均方误差 MSE;
        #   归一化后: 相对 loss, 起点=1.0, 三模型统一量纲对比)
        p.setPen(QColor(t["text2"]))
        p.drawText(4, h - 18, "loss (归一化 · 起点=1)")

        # 绘制各通道 (2026-08-05: series 值 = (xs, y, color, dashed), xs=None 用索引)
        y_lo, y_hi = self._y_range()
        if y_hi <= y_lo:
            y_hi = y_lo + 1
        for name, val in self.series.items():
            xs, data = (val[0], val[1]) if len(val) >= 2 else (None, val[0])
            cname = val[2] if len(val) >= 3 else "base"
            dashed = val[3] if len(val) >= 4 else False
            if len(data) < 1:
                continue
            color = COLORS.get(cname, COLORS["base"])
            pen = QPen(color, 2)
            if dashed:
                pen.setStyle(Qt.DashLine)
            n = len(data)
            if n < 2:
                # 2026-08-05 老倪: "刚开始, 不要显示任何曲线, 会引起歧义. 训练完了再显示"
                # 1 点(训练中)不画任何标记 (调用方 FlowScopeDialog 已过滤, 这里兜底)
                continue
            p.setPen(pen)
            x_lo, x_hi = (float(xs[0]), float(xs[-1])) if xs is not None else (0.0, float(n - 1))
            if x_hi <= x_lo:
                x_hi = x_lo + 1
            prev = None
            for i in range(n):
                xi = float(xs[i]) if xs is not None else float(i)
                x = (xi - x_lo) / (x_hi - x_lo) * w
                y = h - (float(data[i]) - y_lo) / (y_hi - y_lo) * (h - 20) - 10
                pt = QPointF(x, y)
                if prev is not None:
                    p.drawLine(prev, pt)
                prev = pt
        # 图例 (2026-08-05 修复: 原在循环内且 1点曲线 continue 跳过 → 训练中曲线无名字;
        #   移到循环外统一绘制, 1 点曲线也有图例; 2026-08-05 修复2: 色块必须显式 setBrush —
        #   否则残留圆点画的 brush → 所有图例色块变同一颜色)
        legend_x = 10
        for name, val in self.series.items():
            data = val[1] if len(val) >= 2 else val[0]
            cname = val[2] if len(val) >= 3 else "base"
            if len(data) < 1:
                continue
            color = COLORS.get(cname, COLORS["base"])
            p.setPen(QPen(color, 2))
            p.setBrush(color)  # 实心色块 = 各自曲线颜色
            p.drawRect(legend_x, 8, 14, 10)
            p.setBrush(Qt.NoBrush)
            p.setPen(QColor(t["text2"]))
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
        self.setStyleSheet(_qss("QDialog { background:#f6f8fa; }"))
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
        self.cmb_base.setStyleSheet(_qss("background:#ffffff;color:#24292f;border:1px solid #b6bdc7;border-radius:4px;padding:4px 8px;"))
        self.cmb_base.addItem("基础模型 (act_metaworld)", "outputs/train/act_metaworld/checkpoints/000300/pretrained_model")
        ctrl.addWidget(QLabel("基础:"))
        ctrl.addWidget(self.cmb_base, 1)

        self.cmb_ft = QComboBox()
        self.cmb_ft.setStyleSheet(_qss("background:#ffffff;color:#24292f;border:1px solid #b6bdc7;border-radius:4px;padding:4px 8px;"))
        self._scan_models()
        ctrl.addWidget(QLabel("微调:"))
        ctrl.addWidget(self.cmb_ft, 1)

        btn_load = QPushButton("▶ 加载并对比")
        btn_load.setStyleSheet(_qss("background:#00d4aa;color:#f6f8fa;font-weight:700;border:none;border-radius:4px;padding:6px 16px;"))
        btn_load.clicked.connect(self._run_compare)
        ctrl.addWidget(btn_load)

        btn_export = QPushButton("💾 导出PNG")
        btn_export.setStyleSheet(_qss("background:#ffffff;color:#58a6ff;border:1px solid #b6bdc7;border-radius:4px;padding:6px 12px;"))
        btn_export.clicked.connect(self._export_png)
        ctrl.addWidget(btn_export)

        outer.addLayout(ctrl)

        # ═══ 示波器 ═══
        self.scope = ScopeWidget()
        outer.addWidget(self.scope, 1)

        # ═══ 指标栏 ═══
        self.metrics = QLabel("⏳ 等待加载模型...")
        self.metrics.setStyleSheet(_qss("color:#57606a;font-size:12px;padding:6px;background:#ffffff;border-radius:4px;font-family:Consolas;"))
        outer.addWidget(self.metrics)

        # ═══ 底部说明 ═══
        note = QLabel("🔴 基础模型动作  🟢 微调模型动作  ┄┄ 专家真值(参考)   |  X=帧序列  Y=动作值(各维度叠加)")
        note.setStyleSheet(_qss("color:#484f58;font-size:10px;"))
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

    _SS_DARK = ("QDialog { background:#f6f8fa; }"
                "QLabel { color:#1f2328; }"
                "QPushButton { background:#e9edf2; color:#1f2328; border:1px solid #b6bdc7;"
                " border-radius:6px; padding:6px 16px; font-size:12px; }"
                "QPushButton:hover { border-color:#00d4aa; }")

    def __init__(self, module, parent=None):
        super().__init__(parent)
        self.module = module
        self.setWindowTitle("📊 Scope 示波器 — 训练效果 (loss)")
        self.setMinimumSize(780, 540)
        self.setStyleSheet(_qss(self._SS_DARK))
        self._build()
        self._load_data()
        # 训练中实时刷新 (2026-08-05): 2s 轮询最新曲线文件, 波形实时动
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._load_data)
        self._refresh_timer.start(2000)

    def closeEvent(self, e):
        try:
            self._refresh_timer.stop()
        except Exception:
            pass
        super().closeEvent(e)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)
        title = QLabel("📊 Scope 示波器 · 训练 loss 曲线 (Simulink Scope 对标)")
        title.setStyleSheet(_qss("font-size:14px; font-weight:700; color:#1f2328;"))
        root.addWidget(title)
        self.lbl_metrics = QLabel("加载中…")
        self.lbl_metrics.setStyleSheet(_qss("color:#57606a; font-size:11px;"))
        root.addWidget(self.lbl_metrics)
        self.scope = ScopeWidget()
        root.addWidget(self.scope, 1)
        btns = QHBoxLayout()
        self.btn_export = QPushButton("💾 导出 PNG")
        self.btn_fit = QPushButton("🌐 全局适配")
        self.btn_close = QPushButton("❌ 关闭")
        self.btn_export.clicked.connect(self._export_png)
        self.btn_fit.clicked.connect(self._fit_clicked)  # 一键回自动范围 (2026-08-05 老倪)
        self.btn_close.clicked.connect(self.accept)
        btns.addStretch(1)
        btns.addWidget(self.btn_export)
        btns.addWidget(self.btn_fit)
        btns.addWidget(self.btn_close)
        root.addLayout(btns)
        hint = QLabel("🖱 滚轮=缩放Y轴 · 中键拖动=平移 · 双击/🌐全局适配=复位看全图")
        hint.setStyleSheet(_qss("color:#8b949e; font-size:10px;"))
        root.addWidget(hint)

    def _fit_clicked(self):
        """🌐 全局适配 + 点击反馈 (2026-08-05 老倪: 第二次点为什么就没用了 —
        功能正常但无视觉变化, 加按钮文字反馈 1.5s)"""
        self.scope.fit_all()
        self.btn_fit.setText("✓ 已全局适配")
        QTimer.singleShot(1500, lambda: self.btn_fit.setText("🌐 全局适配"))

    def _load_data(self):
        # 2026-08-05 老倪: "怎么就一条曲线, 不应该是3个曲线对比么" — 读全部 train_curve_*.json,
        #   每个模型一条 loss 曲线叠加对比 (act蓝/smolvla橙/smolvla_lew紫); 训练中实时刷新
        curve = None
        try:
            root = self.module._repo_root()
            files = sorted(glob.glob(os.path.join(root, "reports", "train_curve_*.json")),
                           key=os.path.getmtime, reverse=True)
            if files:
                d = json.load(open(files[0], encoding="utf-8"))
                if d.get("curve"):
                    curve = d["curve"]
        except Exception:
            curve = None
        if not curve:
            curve = getattr(self.module, "_train_curve", None) or []
        if not curve:
            self.scope.set_series({})
            self.lbl_metrics.setText("⚠️ 暂无训练曲线 — 点「▶ 运行」, 训练中即可见实时波形")
            self.btn_export.setEnabled(False)
            return
        # 🔬 全部模型曲线叠加 (2026-08-05: 3条对比) — key 用 policy 防同名覆盖
        #   (曾出现 smolvla/smolvla_lew 两文件 name 都是 "SmolVLA", dict 同名覆盖 → 显示1条)
        #   len(cv)>=1: 训练中 1 点也显示 (老倪: 训练刚开始 Scope 就要有波形)
        series = {}
        present_policies = set()
        training = set()  # 训练中模型 (1点曲线, 不显示但提示)
        try:
            root = self.module._repo_root()
            all_files = sorted(glob.glob(os.path.join(root, "reports", "train_curve_*.json")),
                               key=os.path.getmtime)
            now = time.time()
            for f in all_files:
                # 2026-08-05: 保留所有已训练完成的曲线 (训练启动只重置当前policy,
                # 不再按 mtime 过滤 — 三模型对比需要同时看已完成模型波形)
                d = json.load(open(f, encoding="utf-8"))
                cv = d.get("curve") or []
                policy = d.get("policy", "?")
                # 🏷 显示名映射 (2026-08-05 老倪: "SmolVLA(smolvla_lew)分开写, 这是两个模型" —
                #   policy 标识不显示, 用模型显示名: act→ACT / smolvla→SmolVLA / smolvla_lew→SmolVLA+LEW)
                _DISPLAY = {"act": "ACT", "smolvla": "SmolVLA", "smolvla_lew": "SmolVLA+LEW"}
                disp = _DISPLAY.get(policy, policy)
                color = "act" if policy == "act" else ("smolvla" if policy == "smolvla" else "smolvla_lew")
                if len(cv) < 2:
                    # 2026-08-05 老倪: "刚开始, 不要显示任何曲线, 会引起歧义. 训练完了再显示"
                    # 1 点(训练中)不进 series → 不画; 但记录训练中状态供指标行提示
                    training.add(disp)
                    continue
                ys = np.array([l for _, l in cv])
                # 📐 x 轴用真实 step (2026-08-05 老倪: "只显示1 2 4 step" — 之前丢弃 step 用索引)
                xs = np.array([float(s) for s, _ in cv])
                # ⚖️ 统一量纲 (2026-08-05 老倪: "三个模型改成统一量纲" — ACT 是动作空间 MSE
                #   (rad/s)², SmolVLA 系是扩散噪声空间 MSE, 绝对值差量级不可比;
                #   归一化: 除以前3点平均 (2026-08-05 修复: 单点基准不稳 — SmolVLA 首点
                #   0.4357 异常小, 次点 1.049/0.4357=2.4 暴涨; 前3点平均抗波动))
                base = float(np.mean(ys[:3])) if len(ys) >= 3 else float(ys[0])
                if base != 0:
                    ys = ys / base
                series[f"{disp}"] = (xs, ys, color, False)
                present_policies.add(policy)
        except Exception:
            pass
        if not series:
            # 2026-08-05 老倪: "刚开始, 不要显示任何曲线, 会引起歧义. 训练完了再显示"
            # 去掉原兜底单条显示 (曾用旧 _train_curve 数据画默认 loss 曲线 → 歧义)
            self.scope.set_series({})
            if training:
                self.lbl_metrics.setText(f"⏳ 训练中: {'/'.join(sorted(training))} — 训练完成后显示曲线")
            else:
                self.lbl_metrics.setText("📈 暂无完整训练曲线 — 训练完成后自动显示")
            self.scope.update()
            return
        self.scope.set_series(series)
        # 指标行: 各模型首尾 loss + 训练中/缺模型提示 (2026-08-05: 训练中显示⏳不显示曲线)
        parts = []
        for name, val in series.items():
            ys = val[1] if len(val) >= 2 else val[0]
            first, last = float(ys[0]), float(ys[-1])
            drop = first - last
            pct = (drop / first * 100) if first else 0.0
            parts.append(f"{name}: {first:.3f}→{last:.3f} (↓{drop:.3f}, {pct:+.1f}%)")
        missing = [n for p, n in (("act", "ACT"), ("smolvla", "SmolVLA"), ("smolvla_lew", "SmolVLA+LEW"))
                   if p not in present_policies and n not in training]
        train_tip = f" · ⏳ 训练中: {'/'.join(sorted(training))}" if training else ""
        tip = f" · ⚠️ 缺: {'/'.join(missing)} (训练后自动出现)" if missing else ""
        self.lbl_metrics.setText("📈 " + " · ".join(parts) + train_tip + tip)

    def _export_png(self):
        root = self.module._repo_root()
        out_dir = os.path.join(root, "reports")
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"scope_loss_{time.strftime('%Y%m%d_%H%M%S')}.png")
        self.scope.grab().save(path)
        mb = QMessageBox(self)
        mb.setWindowTitle("导出")
        mb.setText(f"已保存: {path}")
        mb.setStyleSheet(_qss("QMessageBox{background:#f6f8fa} QLabel{color:#1f2328;}"
                               "QPushButton{background:#e9edf2;color:#1f2328;border:1px solid #b6bdc7;"
                               "border-radius:6px;padding:6px 18px;}"))
        mb.addButton("好的", QMessageBox.AcceptRole)
        mb.exec_()


class BarCompareWidget(QWidget):
    """🔬 指标对比条形图: 每指标 N 模型横向条 (ACT 蓝 / SmolVLA 橙 / SmolVLA+LEW 金)"""

    COLORS = [QColor("#58a6ff"), QColor("#d29922"), QColor("#a371f7")]  # 蓝/橙/紫

    def __init__(self, parent=None):
        super().__init__(parent)
        self.data = []   # [(指标名, [n模型值...], lower_better)]
        self.names = []  # [模型标签...]
        self.setMinimumSize(560, 190)

    def set_data(self, rows, names=None):
        self.data = rows
        if names:
            self.names = names
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        t = _st()
        p.fillRect(0, 0, w, h, QColor(t["panel"]))
        if not self.data:
            p.setPen(QColor(t["text2"]))
            p.drawText(10, h // 2, "⚠️ 无对比数据 — 先 ▶ 运行训练模型")
            p.end()
            return
        n_mod = max((len(vals) for _, vals, _ in self.data), default=1)
        names = self.names or [f"M{i+1}" for i in range(n_mod)]
        row_h = h / max(len(self.data), 1)
        bar_h = min(12, (row_h - 8) / max(n_mod, 1))
        for i, (name, vals, lower) in enumerate(self.data):
            y0 = int(i * row_h)  # ⚠️ PyQt5 drawText/fillRect 严格 int (float 崩, 2026-08-05 渲染暴露)
            p.setPen(QColor(t["text"]))
            p.setFont(QFont("Consolas", 9))
            p.drawText(8, y0 + 14, f"{name}")
            # 条区: x 从 150 到 w-90
            bx, bw = 150, w - 260
            vmax = max((abs(v) for v in vals if v == v), default=1e-9) or 1e-9
            for j, v in enumerate(vals):
                if v != v:  # nan
                    continue
                yy = y0 + 6 + int(j * (bar_h + 2))
                ln = abs(v) / vmax * bw
                p.fillRect(bx, yy, int(ln), int(bar_h), self.COLORS[j % len(self.COLORS)])
                p.setPen(QColor(t["text2"]))
                p.drawText(bx + int(ln) + 6, yy + int(bar_h) - 1, f"{v:.3g}")
            # 胜出标记 (好值绿)
            good = [v for v in vals if v == v]
            if good:
                if lower:
                    best = min(good)
                else:
                    best = max(good)
                wins = [j for j, v in enumerate(vals) if v == v and v == best]
                if len(wins) < len(vals):
                    p.setPen(QColor("#2ea043"))
                    p.drawText(w - 66, y0 + 20, f"✓ {names[wins[0]]}")
        p.setPen(QColor(t["text2"]))
        p.setFont(QFont("Consolas", 8))
        legend = "   ".join(f"■ {names[j]} ({self.COLORS[j].name()})" for j in range(n_mod))
        p.drawText(8, h - 4, legend + "   · 好值标绿 ✓")
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
        self.setStyleSheet(_qss("QDialog{background:#f6f8fa;}"))
        root = QVBoxLayout(self)

        self.lbl_head = QLabel("⚔️ ACT vs SmolVLA 模型对比")
        self.lbl_head.setStyleSheet(_qss("color:#a371f7;font-size:15px;font-weight:700;"))
        root.addWidget(self.lbl_head)

        self.lbl_note = QLabel("")
        self.lbl_note.setStyleSheet(_qss("color:#57606a;font-size:11px;"))
        root.addWidget(self.lbl_note)

        self.scope = ScopeWidget(self)
        self.scope.setMinimumHeight(200)
        root.addWidget(self.scope)

        self.bars = BarCompareWidget(self)
        root.addWidget(self.bars)

        # 🔬 性能扩展 (2026-08-05 老倪): 逐帧误差曲线 + 误差分布 (P50/P90) + 动作平滑度
        self.lbl_err_head = QLabel("📉 逐帧误差 MSE (归一化空间) — 误差集中区间对比")
        self.lbl_err_head.setStyleSheet(_qss("color:#57606a;font-size:11px;font-weight:700;"))
        root.addWidget(self.lbl_err_head)
        self.err_scope = ScopeWidget(self)
        self.err_scope.setMinimumHeight(140)
        root.addWidget(self.err_scope)

        # 🎯 典型场景轨迹对比 (2026-08-05 老倪: "一个典型场景, 用3个模型分别跑, 对比效果")
        # 同一帧序列 (同一典型场景) 下, 各模型预测动作轨迹 vs 专家真值轨迹叠加 — 直观看出谁跟得紧
        self.lbl_traj_head = QLabel("🎯 典型场景动作轨迹 — 同一场景 3 模型预测 vs 专家真值 (归一化空间)")
        self.lbl_traj_head.setStyleSheet(_qss("color:#57606a;font-size:11px;font-weight:700;"))
        root.addWidget(self.lbl_traj_head)
        self.traj_scope = ScopeWidget(self)
        self.traj_scope.setMinimumHeight(160)
        root.addWidget(self.traj_scope)

        self.table = QTextEdit()
        self.table.setReadOnly(True)
        self.table.setMinimumHeight(110)
        self.table.setStyleSheet(_qss("background:#f6f8fa; color:#24292f; border:1px solid #d0d7de;"
                                        "font-family:Consolas; font-size:12px;"))
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
            self.err_scope.set_series({})
            self.table.setPlainText("无对比数据\n\n运行方式: 画布点「▶ 运行」→ 训练两模型 → 本窗口自动有图表")
            self.btn_export.setEnabled(False)
            return
        m = d.get("models", {})
        # 🔬 通用多模型 (2或3): act=ACT / smolvla=SmolVLA(纯动作) / smolvla_lew=SmolVLA+LEW
        MODELS = [("act", "ACT", "act"), ("smolvla", "SmolVLA", "smolvla"), ("smolvla_lew", "SmolVLA+LEW", "smolvla_lew")]
        present = [(k, tag, c) for k, tag, c in MODELS if k in m and m[k]]
        self.lbl_note.setText(
            f"数据集: {d.get('dataset', 'metaworld_act')} · 测试 {d.get('frames', 0)} 帧 · "
            f"时间 {d.get('ts', '')} · ♻ 同数据/同机评估 (4060) · {len(present)} 模型")
        # ① loss 折线 (每个已训练模型一条)
        series = {}
        for k, tag, c in present:
            curve = m[k].get("curve", [])
            if curve:
                series[f"{tag} loss"] = (np.array([l for _, l in curve], dtype=float), c, False)
        self.scope.set_series(series)
        # ② 指标条形 (N 模型) — 🔬 8 指标: 速度/MSE/成功率/鲁棒性/延迟/P50/P90/平滑度
        rows = []
        for name, key, lower in [("训练速度 step/s", "step_s", False),
                                 ("动作 MSE", "action_mse", True),
                                 ("成功率 %", "success_rate", False),
                                 ("鲁棒性 std", "robustness_std", True),
                                 ("推理延迟 ms", "latency_ms", True),
                                 ("误差 P50", "mse_p50", True),
                                 ("误差 P90", "mse_p90", True),
                                 ("平滑度", "smoothness", True)]:
            vals = []
            for k, tag, c in present:
                v = m[k].get(key, 0.0) or 0.0
                if key == "success_rate":
                    v = v * 100
                vals.append(v)
            rows.append((name, vals, lower))
        self.bars.set_data(rows, names=[tag for _, tag, _ in present])
        # 🔬 逐帧误差曲线 (每个模型一条, 归一化空间 MSE over frames)
        err_series = {}
        for k, tag, c in present:
            fe = m[k].get("frame_err", [])
            if fe:
                err_series[f"{tag} MSE"] = (np.array(fe, dtype=float), c, False)
        self.err_scope.set_series(err_series)
        # 🎯 典型场景轨迹对比: 同一帧序列 (典型场景) 下各模型预测 vs 专家真值
        # 取各模型 traj_pred 最小公共长度; 通道数 = 4D (metaworld); 用第一个动作通道代表主趋势,
        # 其余通道折叠到图例说明 — 保持 1 张图 N+1 条线 (N模型 + 真值)
        traj_series = {}
        gt_ref = None
        n_frames_min = None
        for k, tag, c in present:
            tp = m[k].get("traj_pred", [])
            if tp:
                n_frames_min = len(tp) if n_frames_min is None else min(n_frames_min, len(tp))
        for k, tag, c in present:
            tp = m[k].get("traj_pred", [])
            tg = m[k].get("traj_gt", [])
            if not tp:
                continue
            tp = tp[:n_frames_min] if n_frames_min else tp
            arr = np.array(tp, dtype=float)
            # 多通道 → 取各通道均值曲线 (代表整体跟踪趋势), 图例注明
            if arr.ndim == 2 and arr.shape[1] > 1:
                y = arr.mean(axis=1)
                traj_series[f"{tag} 预测"] = (y, c, False)
            else:
                traj_series[f"{tag} 预测"] = (arr.ravel(), c, False)
            if tg and gt_ref is None:
                tg = tg[:n_frames_min] if n_frames_min else tg
                gt_arr = np.array(tg, dtype=float)
                if gt_arr.ndim == 2 and gt_arr.shape[1] > 1:
                    gt_ref = gt_arr.mean(axis=1)
                else:
                    gt_ref = gt_arr.ravel()
        if gt_ref is not None:
            traj_series["专家真值"] = (gt_ref, "grid", True)  # 虚线参考
        self.traj_scope.set_series(traj_series)
        # ③ 表格 (N 模型列)
        hdr = f"{'维度':<14}" + "".join(f"{tag:>14}" for _, tag, _ in present) + f"{'胜出':>10}"
        lines = [hdr]
        for name, key, lower, fmt in [("训练速度 step/s", "step_s", False, "{:.2f}"),
                                      ("动作 MSE", "action_mse", True, "{:.4f}"),
                                      ("成功率 %", "success_rate", False, "{:.1f}"),
                                      ("鲁棒性 std", "robustness_std", True, "{:.4f}"),
                                      ("推理延迟 ms", "latency_ms", True, "{:.1f}"),
                                      ("误差P50", "mse_p50", True, "{:.4f}"),
                                      ("误差P90(长尾)", "mse_p90", True, "{:.4f}"),
                                      ("动作平滑度", "smoothness", True, "{:.4f}")]:
            vals = []
            for k, tag, c in present:
                v = m[k].get(key, float("nan"))
                if key == "success_rate" and v == v:
                    v = v * 100
                vals.append(v)
            if lower:
                best = min(v for v in vals if v == v) if any(v == v for v in vals) else float("nan")
            else:
                best = max(v for v in vals if v == v) if any(v == v for v in vals) else float("nan")
            line = f"{name:<14}"
            win_i = None
            for i, v in enumerate(vals):
                txt = fmt.format(v) if v == v else "-"
                line += f"{txt:>14}"
                if v == v and v == best:
                    win_i = i
            line += f"{present[win_i][1] if win_i is not None else '=':>10}"
            lines.append(line)
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
        mb.setStyleSheet(_qss("QMessageBox{background:#f6f8fa} QLabel{color:#1f2328;}"
                               "QPushButton{background:#e9edf2;color:#1f2328;border:1px solid #b6bdc7;"
                               "border-radius:6px;padding:6px 18px;}"))
        mb.addButton("好的", QMessageBox.AcceptRole)
        mb.exec_()


class InferenceVideoDialog(QDialog):
    """🎥 推理效果对比 (2026-08-05 老倪: 训练完继续推理, 多模型视频 display 窗口)
    POLICIES 可传: 默认 3 模型 (act/smolvla/smolvla_lew) 兼容旧调用;
    五模型对比传 5 模型 (含 vla_touch/awe_zflow)"""

    POLICIES = [("act", "ACT", "#58a6ff"), ("smolvla", "SmolVLA", "#d29922"),
                ("smolvla_lew", "SmolVLA+LEW", "#a371f7")]
    # 五模型版 (2026-08-05): 含 VLA-Touch/AWE, 与五模型对比模板同序
    POLICIES_5 = [("act", "ACT", "#58a6ff"), ("smolvla", "SmolVLA", "#d29922"),
                  ("smolvla_lew", "SmolVLA+LEW", "#a371f7"),
                  ("vla_touch", "VLA-Touch", "#6a2d8f"),
                  ("awe_zflow", "AWE", "#8f2d4d")]

    def __init__(self, module, policies=None, parent=None):
        super().__init__(parent)
        self.module = module
        self.POLICIES = list(policies or self.POLICIES)
        n = len(self.POLICIES)
        # 🖥 置顶 (2026-08-06 老倪: 5 窗口保持最前不被遮挡, 看着做对比)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.setWindowTitle(f"🎥 {n} 模型推理效果对比 — metaworld push 场景")
        self.setMinimumSize(min(1280, 240 + n * 220), 640)
        self.setStyleSheet(_qss("QDialog{background:#f6f8fa;}"))
        root = QVBoxLayout(self)
        head = QLabel(f"🎥 推理效果对比 · 同一场景 (metaworld push-v3) · {n} 模型 rollout 同步播放")
        head.setStyleSheet(_qss("color:#a371f7;font-size:14px;font-weight:700;"))
        root.addWidget(head)
        self.lbl_note = QLabel("")
        self.lbl_note.setStyleSheet(_qss("color:#57606a;font-size:11px;"))
        root.addWidget(self.lbl_note)
        vid_row = QHBoxLayout()
        self.video_labels = {}
        self.frame_dirs = {}
        self.cur_idx = 0
        for policy, name, color in self.POLICIES:
            box = QVBoxLayout()
            cap = QLabel(f"■ {name}")
            cap.setStyleSheet(_qss(f"color:{color};font-size:12px;font-weight:700;"))
            box.addWidget(cap)
            lab = QLabel("—")
            lab.setFixedSize(400, 300)
            lab.setAlignment(Qt.AlignCenter)
            lab.setStyleSheet(_qss("background:#24292f;color:#8b949e;border:1px solid #d0d7de;border-radius:6px;font-size:11px;"))
            box.addWidget(lab)
            box.addStretch()
            self.video_labels[policy] = lab
            vid_row.addLayout(box)
        root.addLayout(vid_row)
        ctrl = QHBoxLayout()
        self.btn_play = QPushButton("▶ 播放")
        self.btn_pause = QPushButton("⏸ 暂停")
        self.btn_reload = QPushButton("🔄 重新生成推理 (rollout)")
        self.btn_export = QPushButton("💾 导出 PNG")
        self.btn_close = QPushButton("❌ 关闭")
        for b in (self.btn_play, self.btn_pause, self.btn_reload, self.btn_export, self.btn_close):
            b.setStyleSheet(_qss("background:#e9edf2;color:#1f2328;border:1px solid #b6bdc7;border-radius:4px;padding:6px 14px;font-size:11px;"))
        self.btn_play.clicked.connect(self._play)
        self.btn_pause.clicked.connect(self._pause)
        self.btn_reload.clicked.connect(self._run_rollouts)
        self.btn_export.clicked.connect(self._export_png)
        self.btn_close.clicked.connect(self.accept)
        ctrl.addStretch(1)
        for b in (self.btn_play, self.btn_pause, self.btn_reload, self.btn_export, self.btn_close):
            ctrl.addWidget(b)
        root.addLayout(ctrl)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.setInterval(100)
        self._load_frames()
        if self.frame_dirs:
            self._play()
        else:
            # 无帧 → 自动生成 3 模型 rollout (2026-08-05 老倪: 训练完自动接推理对比)
            QTimer.singleShot(300, self._run_rollouts)

    def _load_frames(self):
        root = self.module._repo_root() if hasattr(self.module, "_repo_root") else "."
        min_len = None
        dirs = {}
        # 候选目录优先级: rollout_final_<p> (昨晚 peg 最终版) > rollout_peg_<p> > rollout_<p>
        # (2026-08-06 老倪: 视频打开不动 — 昨晚生成在 rollout_peg_*, 旧逻辑只找 rollout_*)
        for policy, name, color in self.POLICIES:
            found = []
            for cand in (f"rollout_final_{policy}", f"rollout_peg_{policy}", f"rollout_{policy}"):
                d = os.path.join(root, "reports", cand)
                frames = sorted(glob.glob(os.path.join(d, "frame_*.png")))
                if frames:
                    found = frames
                    break
            if found:
                dirs[policy] = found
                min_len = len(found) if min_len is None else min(min_len, len(found))
        self.frame_dirs = dirs
        if not dirs:
            self.lbl_note.setText("⚠️ 无推理视频 — 点「🔄 重新生成推理」跑多模型 rollout (各 60 帧, 约 1-2 分钟)")
            for lab in self.video_labels.values():
                lab.setText("无数据")
            return
        for p in dirs:
            dirs[p] = dirs[p][:min_len]
        self.cur_idx = 0
        self.lbl_note.setText(f"🎞 {len(dirs)} 模型 × {min_len} 帧 · 同一场景同步播放")

    def _tick(self):
        if not self.frame_dirs:
            self._timer.stop()
            return
        n = len(next(iter(self.frame_dirs.values())))
        if self.cur_idx >= n:
            self.cur_idx = 0  # 🔁 循环播放 (2026-08-06 老倪: 看着做对比, 播完自动重头)
            return
        from PyQt5.QtGui import QPixmap
        for policy, frames in self.frame_dirs.items():
            f = frames[self.cur_idx]
            pm = QPixmap(f)
            lab = self.video_labels[policy]
            if not pm.isNull():
                lab.setPixmap(pm.scaled(lab.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.cur_idx += 1

    def _play(self):
        if self.frame_dirs:
            self._timer.start()

    def _pause(self):
        self._timer.stop()

    def _run_rollouts(self):
        root = self.module._repo_root() if hasattr(self.module, "_repo_root") else "."
        n = len(self.POLICIES)
        self.lbl_note.setText(f"⏳ 正在生成 {n} 模型推理视频 (peg-insert, corner2↺90°, 各 60 帧)…")
        self.btn_reload.setEnabled(False)
        import subprocess
        import threading

        def _work():
            out = {}
            for policy, name, _c in self.POLICIES:
                try:
                    # 昨晚验证的方向正确配置 (2026-08-06): peg-insert 插销场景 + corner2 视角
                    # + 逆时针旋转90° → 插孔可见方向正立; 输出 rollout_final_<p>
                    r = subprocess.run([os.path.join(root, ".venv", "bin", "python"),
                                        os.path.join(root, "tools", "rollout_video.py"),
                                        "--policy", policy, "--steps", "60",
                                        "--task", "peg-insert-side-v3",
                                        "--camera", "corner2", "--rotate-ccw",
                                        "--out", os.path.join(root, "reports", f"rollout_final_{policy}")],
                                       capture_output=True, text=True, timeout=300, cwd=root)
                    out[policy] = (r.returncode == 0, r.stdout.strip().splitlines()[-1] if r.stdout else "")
                except Exception as ex:
                    out[policy] = (False, str(ex))
            return out

        def _done(res):
            self.btn_reload.setEnabled(True)
            self._load_frames()
            if self.frame_dirs:
                self._play()
                self.lbl_note.setText(f"✅ 推理视频已生成, {len(self.POLICIES)} 窗口同步播放")
            else:
                self.lbl_note.setText("⚠️ 生成失败 — 检查日志")

        t = threading.Thread(target=_work, daemon=True)
        t.start()
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(lambda: self._check_done(t, _done))
        self._poll_timer.start(500)

    def _check_done(self, t, done):
        if t.is_alive():
            return
        self._poll_timer.stop()
        done(t)

    def _export_png(self):
        out_dir = os.path.join(self.module._repo_root() if hasattr(self.module, "_repo_root") else ".", "reports")
        path = os.path.join(out_dir, f"infer_video_{time.strftime('%Y%m%d_%H%M%S')}.png")
        self.grab().save(path)
        mb = QMessageBox(self)
        mb.setWindowTitle("导出")
        mb.setText(f"已保存: {path}")
        mb.setStyleSheet(_qss("QMessageBox{background:#f6f8fa} QLabel{color:#1f2328;}"
                              "QPushButton{background:#e9edf2;color:#1f2328;border:1px solid #b6bdc7;"
                              "border-radius:6px;padding:6px 18px;}"))
        mb.addButton("好的", QMessageBox.AcceptRole)
        mb.exec_()

    def closeEvent(self, ev):
        """🛡 关闭时停全部定时器 (2026-08-05 崩溃修复#7: InferenceVideoDialog 原本无 closeEvent →
        _timer(播放)/_poll_timer(rollout轮询) 关闭时未停 → QThread destroyed exit 134)"""
        for attr in ("_timer", "_poll_timer"):
            t = getattr(self, attr, None)
            if t is not None:
                try:
                    t.stop()
                except Exception:
                    pass
        super().closeEvent(ev)
