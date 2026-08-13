#!/usr/bin/env python3
"""📚 数据字典 Model Tree — 画布数学化改造 (2026-08-12 老倪)
参考 MATLAB Workspace / 数据字典: 右侧面板树形展示画布节点参数,
可标定/调节; 数学分析: 节点→传递函数→状态空间→复数空间稳定性

视图切换 (下拉菜单):
  📚 数据字典 — 树形: 系统参数 + 节点(按行) + 参数(名=值, 双击编辑写回画布)
  ⚙️ 参数标定 — 同树形, 参数行可直接编辑 (标定)
  🧮 数学分析 — 系统传递函数/状态空间/零极点(复数平面) + 稳定性判定
"""
import os
import numpy as np

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QDockWidget, QWidget, QVBoxLayout, QComboBox,
                             QTreeWidget, QTreeWidgetItem, QLabel, QInputDialog,
                             QHBoxLayout, QPushButton)
from PyQt5.QtGui import QPainter, QColor, QPen, QFont


# ════════════════════════════════════════════════════════════════
# 数学内核 (numpy 手写, GUI 环境无 scipy)
# ════════════════════════════════════════════════════════════════
def node_transfer(node):
    """节点 → 传递函数 (num, den): 按类型+参数生成控制理论模型
    数据源=单位增益; 模型/控制器=K/(1+Ts); 执行器=K/(s+a); 判定/开关=1/(1+τs)"""
    t = node.get("type", "model")
    p = node.get("params", {})
    name = node.get("name", "")
    K = float(p.get("gain", 1.0))
    T = float(p.get("time_const", 0.1))
    a = float(p.get("pole", 2.0))
    if t == "hardware":
        return np.array([1.0]), np.array([1.0])           # 数据源: 单位增益
    if t == "action":
        return np.array([K]), np.array([1.0, a])          # 执行器: K/(s+a)
    if t in ("switch", "train_gate", "yolo_gate"):
        return np.array([1.0]), np.array([1.0])           # 路由/开关: 直通
    if t == "condition":
        return np.array([1.0]), np.array([T, 1.0])        # 判定: 1/(1+Ts)
    if t == "model":
        return np.array([K]), np.array([T, 1.0])          # 模型/控制器: K/(1+Ts)
    if t == "system":
        return np.array([K]), np.array([T, 1.0])          # 系统/调度: K/(1+Ts)
    return np.array([1.0]), np.array([1.0])               # 兜底


def series_chain(nodes):
    """主链路节点 → 串联传递函数 (逐个相乘, 化简)"""
    num = np.array([1.0])
    den = np.array([1.0])
    for n in nodes:
        n_, d_ = node_transfer(n)
        num = np.polymul(num, n_)
        den = np.polymul(den, d_)
    return num, den


def main_chain(module):
    """画布主链路: 从数据源(无入边)沿连线到输出(无出边)取最长路径
    返回节点列表 (拓扑顺序)"""
    nodes = module.nodes
    by_id = {n["id"]: n for n in nodes}
    links = getattr(module, "links", []) or []
    out_deg = {}
    in_deg = {}
    for l in links:
        out_deg[l["f"]] = out_deg.get(l["f"], 0) + 1
        in_deg[l["t"]] = in_deg.get(l["t"], 0) + 1
    sources = [n for n in nodes if n.get("type") != "row_bg" and n["id"] not in in_deg]
    # 从第一个数据源 BFS 最长路径
    if not sources:
        return [n for n in nodes if n.get("type") != "row_bg"][:6]
    start = sources[0]
    adj = {}
    for l in links:
        adj.setdefault(l["f"], []).append(l["t"])
    chain = []
    cur = start["id"]
    visited = set()
    while cur and cur not in visited:
        visited.add(cur)
        n = by_id.get(cur)
        if n is None:
            break
        if n.get("type") != "row_bg":
            chain.append(n)
        nxt = [t for t in adj.get(cur, []) if t in by_id and by_id[t].get("type") != "row_bg"]
        if not nxt:
            break
        cur = nxt[0]
    return chain


def tf_to_ss(num, den):
    """传递函数 → 可控标准型状态空间 (A,B,C,D)"""
    num = np.trim_zeros(np.asarray(num, dtype=float), "f")
    den = np.trim_zeros(np.asarray(den, dtype=float), "f")
    if len(den) < 2:
        n = 0
    else:
        n = len(den) - 1
    num = np.pad(num, (len(den) - len(num), 0))
    if n == 0:
        return np.zeros((1, 1)), np.zeros((1, 1)), np.array([[num[0] / den[0]]]), np.array([[0.0]])
    A = np.zeros((n, n))
    if n > 1:
        A[:-1, 1:] = np.eye(n - 1)
    A[-1, :] = -den[1:][::-1] / den[0]
    B = np.zeros((n, 1))
    B[-1, 0] = 1.0
    C = (num[1:] - num[0] * den[1:] / den[0])[::-1]
    D = np.array([[num[0] / den[0]]])
    return A, B, C.reshape(1, -1), D


def analyze_system(module):
    """画布 → 系统分析结果 dict: {chain, num, den, poles, zeros, stable, A,B,C,D}"""
    chain = main_chain(module)
    num, den = series_chain(chain)
    poles = np.roots(den)
    zeros = np.roots(num)
    stable = bool(len(poles) == 0 or np.all(np.real(poles) < 0))
    A, B, C, D = tf_to_ss(num, den)
    return {"chain": chain, "num": num, "den": den,
            "poles": poles, "zeros": zeros, "stable": stable,
            "A": A, "B": B, "C": C, "D": D}


# ════════════════════════════════════════════════════════════════
# 复数平面图 (QPainter 手绘: 单位圆 + 极点× + 零点○)
# ════════════════════════════════════════════════════════════════
class PoleZeroPlot(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.poles = np.array([])
        self.zeros = np.array([])
        self.stable = True
        self.setMinimumHeight(180)

    def set_data(self, poles, zeros, stable):
        self.poles = np.asarray(poles, dtype=complex)
        self.zeros = np.asarray(zeros, dtype=complex)
        self.stable = bool(stable)
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        r = min(w, h) / 2 - 16
        # 坐标轴
        p.setPen(QPen(QColor("#57606a"), 1))
        p.drawLine(int(cx - r), int(cy), int(cx + r), int(cy))
        p.drawLine(int(cx), int(cy - r), int(cx), int(cy + r))
        # 单位圆 (稳定性边界)
        p.setPen(QPen(QColor("#d0d7de"), 1, Qt.DashLine))
        p.drawEllipse(int(cx - r), int(cy - r), int(2 * r), int(2 * r))
        # 标签
        p.setPen(QColor("#9aa4b2"))
        p.setFont(QFont("Arial", 8))
        p.drawText(int(cx + r) - 30, int(cy) + 14, "Re")
        p.drawText(int(cx) + 6, int(cy - r) + 10, "Im")
        # 极点 × (红=不稳定/绿=稳定)
        for z in self.poles:
            x = int(cx + z.real * r)
            y = int(cy - z.imag * r)
            col = QColor("#3fb950") if z.real < 0 else QColor("#ff4444")
            p.setPen(QPen(col, 2))
            p.drawLine(x - 5, y - 5, x + 5, y + 5)
            p.drawLine(x - 5, y + 5, x + 5, y - 5)
        # 零点 ○
        for z in self.zeros:
            x = int(cx + z.real * r)
            y = int(cy - z.imag * r)
            p.setPen(QPen(QColor("#58a6ff"), 2))
            p.drawEllipse(x - 5, y - 5, 10, 10)
        p.end()


# ════════════════════════════════════════════════════════════════
# 右侧数据字典面板
# ════════════════════════════════════════════════════════════════
class ModelTreeDock(QDockWidget):
    """📚 数据字典 (Model Tree) — 画布节点参数树 + 标定 + 数学分析"""

    def __init__(self, module, parent=None):
        super().__init__("📚 数据字典 (Model Tree)", parent)
        self.module = module
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)

        root = QWidget()
        lay = QVBoxLayout(root)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)

        # 下拉菜单: 视图切换 (参考 MATLAB Workspace 数据字典)
        self.cmb_view = QComboBox()
        self.cmb_view.addItems(["📚 数据字典", "⚙️ 参数标定", "🧮 数学分析"])
        self.cmb_view.currentIndexChanged.connect(self._switch_view)
        lay.addWidget(self.cmb_view)

        self.lbl_hint = QLabel("")
        self.lbl_hint.setStyleSheet("color:#9aa4b2; font-size:10px; background:transparent; border:none;")
        self.lbl_hint.setWordWrap(True)
        lay.addWidget(self.lbl_hint)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemDoubleClicked.connect(self._on_item_dbl)
        lay.addWidget(self.tree, 1)

        # 数学分析视图控件 (默认隐藏)
        self.lbl_math = QLabel("")
        self.lbl_math.setStyleSheet("color:#c9d1d9; font-size:11px; font-family:Consolas; background:transparent;")
        self.lbl_math.setWordWrap(True)
        self.lbl_math.setVisible(False)
        lay.addWidget(self.lbl_math)
        self.plot = PoleZeroPlot()
        self.plot.setVisible(False)
        lay.addWidget(self.plot)

        self.setWidget(root)
        self.refresh()

    # ── 视图切换 ──
    def _switch_view(self, idx):
        math = idx == 2
        self.tree.setVisible(not math)
        self.lbl_math.setVisible(math)
        self.plot.setVisible(math)
        if math:
            self._show_math()
        else:
            self.refresh()

    # ── 数据字典树 (系统参数 + 节点 + 参数) ──
    def refresh(self):
        self.tree.clear()
        self.lbl_hint.setText("画布节点参数一览 · 双击参数值可标定/调节 (写回画布)")
        # 系统参数
        sys_root = QTreeWidgetItem(["⚙ 系统参数"])
        self.tree.addTopLevelItem(sys_root)
        dt = getattr(self.module, "_sim_dt", 0.01)
        QTreeWidgetItem(sys_root, ["采样周期 dt", f"{dt:.4f} s"])
        n_sys = sum(1 for n in self.module.nodes if n.get("type") != "row_bg")
        QTreeWidgetItem(sys_root, ["功能节点数", str(n_sys)])
        # 节点 (按行分组: y 坐标)
        rows = {}
        for n in self.module.nodes:
            if n.get("type") == "row_bg":
                continue
            rows.setdefault(round(n.get("y", 0) / 10), []).append(n)
        for y in sorted(rows):
            grp = QTreeWidgetItem([f"行 y={y * 10}"])
            self.tree.addTopLevelItem(grp)
            for n in sorted(rows[y], key=lambda x: x.get("x", 0)):
                nitem = QTreeWidgetItem([f"{n.get('name', '?')}"])
                nitem.setData(0, Qt.UserRole, n)
                grp.addChild(nitem)
                params = n.get("params", {})
                for k, v in params.items():
                    if isinstance(v, (dict, list)):
                        continue
                    pit = QTreeWidgetItem([f"  {k}", str(v)])
                    pit.setData(0, Qt.UserRole, (n, k))
                    nitem.addChild(pit)
        self.tree.expandAll()

    # ── 双击参数 → 标定 (写回画布节点) ──
    def _on_item_dbl(self, item, col):
        data = item.data(0, Qt.UserRole)
        if not data or not isinstance(data, tuple) or len(data) != 2:
            return
        node, key = data
        cur = node.get("params", {}).get(key, "")
        val, ok = QInputDialog.getText(self, f"标定参数: {node.get('name')}",
                                       f"{key} =", text=str(cur))
        if not ok:
            return
        try:
            old = node["params"][key]
            if isinstance(old, bool):
                node["params"][key] = val.lower() in ("true", "1", "yes", "是")
            elif isinstance(old, (int, float)):
                node["params"][key] = type(old)(float(val))
            else:
                node["params"][key] = val
        except Exception:
            node["params"][key] = val
        self.module._refresh_node(node)
        self.module._log(f"⚙️ 标定 [{node.get('name')}] {key} = {node['params'][key]}")
        self.refresh()

    # ── 数学分析 ──
    def _show_math(self):
        try:
            res = analyze_system(self.module)
        except Exception as ex:
            self.lbl_math.setText(f"⚠️ 数学分析失败: {ex}")
            return
        chain = res["chain"]
        names = " → ".join(n.get("name", "?") for n in chain[:6])
        if len(chain) > 6:
            names += " …"
        num, den = res["num"], res["den"]
        def _poly(p):
            return "".join(f"{c:+.3g}s^{len(p) - 1 - i} " for i, c in enumerate(p))
        poles = ", ".join(f"{z.real:.3f}{z.imag:+.3f}i" for z in res["poles"]) or "无"
        zeros = ", ".join(f"{z.real:.3f}{z.imag:+.3f}i" for z in res["zeros"]) or "无"
        A, B, C, D = res["A"], res["B"], res["C"], res["D"]
        txt = (f"🧮 系统数学化 (主链路 {len(chain)} 节点)\n"
               f"链路: {names}\n\n"
               f"G(s) = N(s)/D(s)\n  N = {_poly(num)}\n  D = {_poly(den)}\n\n"
               f"状态空间 (可控标准型, 阶数 n={A.shape[0]})\n"
               f"  ẋ = Ax + Bu\n  y = Cx + Du\n"
               f"  A = {A.tolist()}\n  B = {B.tolist()}\n  C = {C.tolist()}\n  D = {D.tolist()}\n\n"
               f"极点 (复数空间): {poles}\n"
               f"零点: {zeros}\n"
               f"稳定性: {'✅ 稳定 (全部极点 Re<0)' if res['stable'] else '❌ 不稳定 (存在 Re≥0 极点)'}")
        self.lbl_math.setText(txt)
        self.plot.set_data(res["poles"], res["zeros"], res["stable"])
