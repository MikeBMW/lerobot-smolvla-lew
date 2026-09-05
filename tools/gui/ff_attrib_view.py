#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ff_attrib_view.py — 🎯 前馈加速器 归因·分工 视图 (2026-09-04 老倪)

上半: 归因堆叠图 — 每帧 512 隐单元对 4 个输出维 (dx/dy/dz/gripper) 的驱动能量
      contrib_d(t) = Σ_j |W3[d,j]·x3[j]|  → 谁在指挥动作, 随任务阶段切换
下半: 512 单元功能散点 — 每单元 = 时间激活 profile (150帧), PCA(即时) 或 t-SNE
      (纯 numpy exact, ~几秒) 投影 2D; 颜色 = 静态分工 argmax|W3[:,j]| (它听谁的)
      → 看单元是否聚成功能群 (同色成簇 = 明确分工)
"""
import os
import sys

import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPainter, QColor, QPen, QFont
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel)

_BG_TOP = QColor("#0d1117")
_BG_BOT = QColor("#161b22")
_GRID = QColor("#1e2740")
_TEXT = QColor("#c9d1d9")
_TEXT2 = QColor("#8b949e")
# 4 输出维通道色 (分析图需区分通道: 朱红=主维dx + 灰阶; 同 Scope 先例)
DIM_COLORS = [QColor("#b70032"), QColor("#2a2a2a"), QColor("#666666"), QColor("#9d9d9d")]
DIM_NAMES = ["dx(朱红)", "dy(黑)", "dz(中灰)", "gripper(浅灰)"]
N_FRAMES = 120      # 堆叠时间窗
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/gui → tools → 根
_NPZ = os.path.join(_ROOT, "models", "ss_left_brain.npz")


class FFAttribView(QDialog):
    """归因堆叠 + 单元功能散点 (PCA / t-SNE)"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🎯 前馈加速器 · 归因与单元分工")
        self.resize(920, 760)
        self.setMinimumSize(720, 600)
        # 🔧 2026-09-05 老倪: 最小化/最大化按钮无效 — 显式顶级窗口类型 + 按钮
        self.setWindowFlags(Qt.Window | Qt.WindowTitleHint | Qt.WindowSystemMenuHint
                            | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        self.x3_buf = []          # 每帧层3激活 (512,)
        self.contrib = []         # 每帧 4 维驱动能量
        self.pts2d = None         # PCA 投影 (512,2)
        self.pts_tsne = None
        self.use_tsne = False
        self._load_static()
        # UI
        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        self._lab = QLabel("归因堆叠: 每帧 4 输出维驱动能量 (谁在指挥) · 散点: 512 单元, 颜色=它听谁的")
        self._lab.setStyleSheet("color:#8b949e; padding:4px;")
        bar.addWidget(self._lab)
        btn_pca = QPushButton("PCA 投影")
        btn_pca.setStyleSheet("color:#c9d1d9; background:#21262d; padding:3px 10px;")
        btn_pca.clicked.connect(lambda: self._project("pca"))
        btn_tsne = QPushButton("t-SNE (纯numpy, 约几秒)")
        btn_tsne.setStyleSheet("color:#c9d1d9; background:#21262d; padding:3px 10px;")
        btn_tsne.clicked.connect(lambda: self._project("tsne"))
        bar.addWidget(btn_pca)
        bar.addWidget(btn_tsne)
        lay.addLayout(bar)

    def _load_static(self):
        """静态分工: 每单元听哪个输出维 = argmax|W3[:,j]| (4 行含 gripper 意图行)"""
        try:
            import importlib.util as _ilu
            _p = os.path.join(_ROOT, "src", "lerobot", "policies",
                              "left_right", "state_space", "parallel.py")
            _spec = _ilu.spec_from_file_location("ss_parallel_w", _p)
            _m = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_m)
            _W, _b, _sm, _ss, _am, _astd = _m.load_npz_weights(_NPZ)
            self.W3 = np.asarray(_W[3], dtype=np.float32)      # (4, 512)
        except Exception as _e:
            print(f"⚠️ FFAttribView 权重加载失败: {_e}")
            self.W3 = np.zeros((4, 512), dtype=np.float32)
        aw = np.abs(self.W3)
        self.cls = np.argmax(aw, axis=0)                       # 每单元归属输出维
        self.cls_strong = aw.max(axis=0) > 0.02 * aw.max()     # 弱单元标记

    # ── 数据 ──
    def push(self, probe):
        raw = probe.get("act_raw")
        if not raw or len(raw) < 3:
            return
        x3 = np.asarray(raw[2], dtype=np.float32).ravel()
        if x3.shape[0] != 512:
            return
        self.x3_buf.append(x3)
        if len(self.x3_buf) > N_FRAMES:
            self.x3_buf.pop(0)
        # 驱动能量: 每输出维 = Σ_j |W3[d,j]·x3[j]|
        self.contrib.append([float(np.abs(self.W3[d] * x3).sum()) for d in range(4)])
        if len(self.contrib) > N_FRAMES:
            self.contrib.pop(0)
        # 🔭 2026-09-05: 满 10 帧自动 PCA (散点不用等手动按钮; 数据不足时下方提示)
        if len(self.x3_buf) == 10 and self.pts2d is None and self.pts_tsne is None:
            try:
                self._project("pca")
            except Exception:
                pass
        # 状态行随帧更新 (自解释 + 可见在动)
        try:
            mode = "t-SNE" if self.use_tsne else ("PCA ✓" if self.pts2d is not None else "未投影")
            dom = int(np.argmax(self.contrib[-1]))
            self._lab.setText(
                f"累积 {len(self.x3_buf)} 帧 · 当前主导输出维: {DIM_NAMES[dom]} · "
                f"散点 {mode} · 色块: {DIM_NAMES[0]}/{DIM_NAMES[1]}/{DIM_NAMES[2]}/{DIM_NAMES[3]} "
                f"= 该单元在指挥哪个输出维 (同类成簇=功能分群)")
        except Exception:
            pass
        self.update()

    # ── 投影 ──
    def _project(self, kind):
        if len(self.x3_buf) < 10:
            return
        M = np.stack(self.x3_buf, axis=1).astype(np.float32)   # (512, 帧)
        # 每帧中心化 (去掉全局同步成分 → 凸显单元间差异模式)
        Mc = M - M.mean(0, keepdims=True)
        s = M.std(0)
        Mc = Mc / (s + 1e-6)
        if kind == "pca":
            u, sv, _ = np.linalg.svd(Mc, full_matrices=False)
            self.pts2d = (u[:, :2] * sv[:2][None, :]).astype(np.float32)
            self.use_tsne = False
        else:
            self.pts_tsne = self._tsne(Mc)                      # (512单元, 帧特征)
            self.use_tsne = True
        self.update()

    def _tsne(self, X, perp=30.0, iters=400, lr=200.0, seed=7):
        """exact t-SNE (纯 numpy, 512点~秒级; X: (512, D) 已中心化)"""
        rng = np.random.default_rng(seed)
        N = X.shape[0]
        D2 = ((X[:, None, :] - X[None, :, :]) ** 2).sum(-1)
        np.fill_diagonal(D2, 0.0)
        P = np.zeros((N, N))
        logP = np.log(perp + 1e-8)
        for i in range(N):
            d = D2[i]
            d = d[d > 0]
            if d.size == 0:
                continue
            # 二分找 sigma (perp 目标)
            lo, hi = 1e-8, 1e3
            for _ in range(40):
                sig = 0.5 * (lo + hi)
                p = np.exp(-d / (2 * sig * sig))
                H = np.log(np.sum(p) + 1e-12) - (p / (np.sum(p) + 1e-12) * np.log(p + 1e-12)).sum()
                if H < logP:
                    lo = sig
                else:
                    hi = sig
            p = np.exp(-d / (2 * sig * sig))
            p = p / (p.sum() + 1e-12)
            P[i, D2[i] > 0] = p
        P = 0.5 * (P + P.T)
        P = np.maximum(P, 1e-12)
        Y = rng.normal(0, 1e-4, (N, 2))
        Ym = np.zeros_like(Y)
        for it in range(iters):
            Dq = ((Y[:, None, :] - Y[None, :, :]) ** 2).sum(-1) + 1e-12
            Q = 1.0 / (1.0 + Dq)
            np.fill_diagonal(Q, 0.0)
            Q = Q / (Q.sum() + 1e-12)
            # 梯度: dC/dY_i = 4·Σ_j (P−Q)_ij·(y_i−y_j)·(1+‖y_i−y_j‖²)^{-1}
            # 向量化 = 4·(Y·rowsum(A) − A·Y),  A_ij = (P−Q)_ij/(1+Dq_ij)
            A = (P - Q) / (1.0 + Dq)
            grad = 4.0 * (Y * A.sum(1, keepdims=True) - A @ Y)
            Ym = 0.8 * Ym - lr * grad
            Y = Y + Ym
            Y = Y - Y.mean(0)
        return Y.astype(np.float32)

    # ── 绘制 ──
    def paintEvent(self, ev):
        p = QPainter(self)
        r = self.rect()
        p.fillRect(r, QColor("#0f1419"))
        W, H = r.width(), r.height()
        if not self.contrib:
            p.setPen(_TEXT2)
            p.setFont(QFont("Sans", 12))
            p.drawText(r, Qt.AlignCenter, "🎯 运行 ⚡前馈加速器后自动累积… (堆叠=驱动能量, 散点=单元分工)")
            p.end()
            return
        self._draw_stack(p, W, H)
        self._draw_scatter(p, W, H)
        p.end()

    def _draw_stack(self, p, W, H):
        """上半: 归因堆叠 (时间 × 4 维驱动能量)"""
        x0, x1 = 70, W - 16
        y0, y1 = 36, int(H * 0.46)
        c = np.asarray(self.contrib, dtype=np.float64)          # (T,4)
        csum = c.sum(1)
        vmax = max(float(np.percentile(csum, 98)), 1e-6)
        # 网格
        p.setPen(QPen(_GRID, 1))
        for gy in range(5):
            yy = y0 + (y1 - y0) * gy / 4
            p.drawLine(x0, int(yy), x1, int(yy))
        p.setFont(QFont("Sans", 8))
        p.setPen(_TEXT2)
        p.drawText(x0 - 4, y1 + 14, "0")
        p.drawText(x0 - 30, y0 + 4, f"{vmax:.0f}")
        # 堆叠柱 (每帧一柱)
        bw = (x1 - x0) / max(len(c), 1)
        for t in range(len(c)):
            acc = 0.0
            for d in range(4):
                hh = (y1 - y0) * c[t, d] / vmax
                p.fillRect(int(x0 + bw * t) + 1, int(y1 - acc - hh), max(int(bw) - 2, 1), int(hh),
                           DIM_COLORS[d])
                acc += hh
        # 标题 + 图例
        p.setPen(_TEXT)
        p.setFont(QFont("Sans", 10, QFont.Bold))
        p.drawText(14, 22, "归因堆叠 · 谁在指挥 (每帧 4 维驱动能量 Σ|W3·x3|)")
        p.setFont(QFont("Sans", 8))
        lx = x0
        for d in range(4):
            p.fillRect(lx, 4, 12, 10, DIM_COLORS[d])
            p.setPen(_TEXT2)
            p.drawText(lx + 16, 13, DIM_NAMES[d])
            lx += 70 + len(DIM_NAMES[d]) * 5
        # 主导维文本 (最近帧)
        if len(c):
            dom = int(np.argmax(c[-1]))
            p.setPen(_TEXT)
            p.setFont(QFont("Sans", 9, QFont.Bold))
            p.drawText(x1 - 150, 22, f"当前主导: {DIM_NAMES[dom]}")

    def _draw_scatter(self, p, W, H):
        """下半: 512 单元功能散点 (PCA/t-SNE)"""
        y0 = int(H * 0.52)
        x0, x1 = 70, W - 16
        y1 = H - 30
        p.setPen(_TEXT)
        p.setFont(QFont("Sans", 10, QFont.Bold))
        mode = "t-SNE" if self.use_tsne else "PCA"
        p.drawText(14, y0 - 10, f"512 单元功能散点 ({mode}, 150帧激活profile) · 颜色=它听哪个输出维")
        # 空状态
        pts = self.pts_tsne if self.use_tsne else self.pts2d
        if pts is None:
            p.setPen(_TEXT2)
            p.setFont(QFont("Sans", 9))
            p.drawText(x0, y0 + 16, "点击右上「PCA 投影」或「t-SNE」生成 (同色成簇 = 单元功能分群)")
            return
        # 网格 + 边框
        p.setPen(QPen(_GRID, 1))
        for gy in range(5):
            yy = y0 + (y1 - y0) * gy / 4
            p.drawLine(x0, int(yy), x1, int(yy))
        for gx in range(5):
            xx = x0 + (x1 - x0) * gx / 4
            p.drawLine(int(xx), y0, int(xx), y1)
        # 归一化到绘图区
        P = pts
        lo, hi = np.percentile(P, 1, axis=0), np.percentile(P, 99, axis=0)
        rng = hi - lo
        rng = np.where(rng < 1e-6, 1.0, rng)
        xs = x0 + (P[:, 0] - lo[0]) / rng[0] * (x1 - x0)
        ys = y1 - (P[:, 1] - lo[1]) / rng[1] * (y1 - y0)
        # 活跃度 → 点大小 (平均激活)
        act = np.stack(self.x3_buf, axis=1).mean(1)
        amin, amax = act.min(), max(act.max(), 1e-6)
        for j in range(512):
            if not self.cls_strong[j]:
                continue
            rad = 1.5 + 2.5 * (act[j] - amin) / (amax - amin)
            p.setBrush(DIM_COLORS[self.cls[j]])
            p.setPen(Qt.NoPen)
            p.drawEllipse(int(xs[j] - rad), int(ys[j] - rad), int(rad * 2), int(rad * 2))
        # 类统计
        p.setPen(_TEXT2)
        p.setFont(QFont("Sans", 9))
        n_per = [int((self.cls == d).sum()) for d in range(4)]
        p.drawText(14, y1 + 6, f"单元归属: " + "  ".join(
            f"{DIM_NAMES[d]} {n_per[d]}" for d in range(4)))
