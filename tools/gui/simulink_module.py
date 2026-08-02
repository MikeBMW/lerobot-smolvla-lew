#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Z-MAX Simulink 模式 · GUI 控制台引擎
对标 Simulink 交互: 0帧起手 → 模块库拖拽 → 连线 → 双击参数 → 运行/单步/停止
与 Web comfyui.html 共用 simulink-spec.md v1.0 节点规范 (JSON 完全一致)
"""
import json, math, random, time, os, sys
from PyQt5.QtCore import Qt, QRectF, QPointF, QTimer, pyqtSignal, QLineF
from PyQt5.QtGui import (QPainter, QPainterPath, QPainterPathStroker, QColor, QPen, QBrush, QFont,
                         QPolygonF, QLinearGradient, QRadialGradient)
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGraphicsView,
                             QGraphicsScene, QGraphicsItem, QGraphicsObject,
                             QLabel, QPushButton, QToolButton, QFrame, QSpinBox,
                             QDoubleSpinBox, QComboBox, QLineEdit, QDialog,
                             QFormLayout, QTextEdit, QScrollArea, QMenu,
                             QMessageBox, QSplitter, QDialogButtonBox)

# ════════════════════════════════════════════════════════════════
# 规范常量 (与 simulink-spec.md / web comfyui.html 完全一致)
# ════════════════════════════════════════════════════════════════
NODE_TYPES = {
    "condition": {"cn": "条件", "color": "#a371f7"},
    "model":     {"cn": "模型", "color": "#58a6ff"},
    "action":    {"cn": "动作", "color": "#00d4aa"},
    "system":    {"cn": "系统", "color": "#d4a800"},
    "hardware":  {"cn": "硬件", "color": "#ff4444"},
}
COLORS = {t: v["color"] for t, v in NODE_TYPES.items()}
DH = 50  # 节点高度 (与 web 一致)

# 工作流分区 (对标 MathWorks 解决方案页 6 大功能) → 节点类型映射
WORKFLOW_TYPES = {
    "data":     "hardware",   # ① 访问·标注数据: Orin/MAC/相机/数据集
    "scene":    "system",     # ② 仿真场景: 调度/工作流/场景
    "plan":     "model",      # ③ 规划·控制: VLA/ACT/SmolVLA 策略
    "percept":  "condition",  # ④ 感知算法: 条件/触发/AOI/力控
    "deploy":   "model",      # ⑤ 部署: 远程推理/4090/代码生成
    "test":     "action",     # ⑥ 集成·测试: 原子动作/工位测试
}
# 参考应用模板 (对标 MathWorks 参考应用列表)
REFERENCE_APPS = [
    ("📦 取料·100G 闭环", [
        ("hardware", "Orin Nano", {"ip": "192.168.23.10", "fps": 30}),
        ("model", "ACT", {"chunk_size": 7, "dim_model": 256}),
        ("action", "A01 取料·100G", {"pos": [0.1, 0.2, 0.3]}),
        ("condition", "C03 力控达标", {"max_force": 5.0}),
    ], [(0, 1), (1, 2), (2, 3)]),
    ("🎛 力控插入·Z700", [
        ("hardware", "机械臂", {"model": "Z700", "dof": 6}),
        ("condition", "C01 到位判断", {"tolerance": 0.01}),
        ("model", "VLA-T", {"remote": "4090:50054"}),
        ("action", "A04 力控插入", {"force": 3.0}),
    ], [(0, 1), (1, 2), (2, 3)]),
    ("📡 数据闭环·Orin→4090", [
        ("hardware", "Orin Nano", {"ip": "192.168.23.10", "fps": 30}),
        ("hardware", "MAC", {"ip": "192.168.23.1", "port": 8769}),
        ("hardware", "4090训练", {"host": "39.102.211.79", "port": 50054}),
        ("model", "H-JEPA", {"remote": "4090"}),
    ], [(0, 1), (1, 2), (2, 3)]),
    ("🏭 AOI检测·分拣", [
        ("hardware", "相机", {"res": "480x640", "fps": 30}),
        ("condition", "C04 AOI通过", {}),
        ("model", "SmolVLA", {"checkpoint": "smolvla-500m"}),
        ("action", "A09 AOI检测", {}),
        ("action", "A10 分拣", {"bin": 3}),
    ], [(0, 1), (1, 2), (2, 3), (3, 4)]),
]

# 模块库 (左侧拖拽面板) — 与 web comfyui.html 的模块组一致
LIBRARY = [
    ("condition", "条件 (11)", [
        {"name": "C00 信号触发", "params": {"threshold": 0.5}},
        {"name": "C01 到位判断", "params": {"tolerance": 0.01}},
        {"name": "C02 扫码OK",   "params": {}},
        {"name": "C03 力控达标", "params": {"max_force": 5.0}},
        {"name": "C04 AOI通过",  "params": {}},
        {"name": "C05 温控阈值", "params": {"limit": 45.0}},
    ]),
    ("model", "模型 (9)", [
        {"name": "M00 SmolVLA", "params": {"checkpoint": "smolvla-500m", "fps": 100}},
        {"name": "M01 ACT",     "params": {"chunk_size": 7, "dim_model": 256}},
        {"name": "M02 VLA-T",   "params": {"remote": "4090:50054"}},
        {"name": "M03 GR00T",   "params": {"remote": "4090:50056"}},
        {"name": "M04 LEW",     "params": {"horizon": 16}},
        {"name": "M05 H-JEPA",  "params": {"remote": "4090"}},
    ]),
    ("action", "动作 (11)", [
        {"name": "A00 Action输出", "params": {}},
        {"name": "A01 取料·100G",  "params": {"pos": [0.1, 0.2, 0.3]}},
        {"name": "A02 扫码·100G",  "params": {}},
        {"name": "A03 放置·100G",  "params": {"pos": [0.5, 0.6, 0.7]}},
        {"name": "A04 力控插入",   "params": {"force": 3.0}},
        {"name": "A05 推入",       "params": {"depth": 0.02}},
        {"name": "A06 取出",       "params": {}},
        {"name": "A07 翻转",       "params": {"angle": 180}},
        {"name": "A08 定位",       "params": {"precision": "0.02mm"}},
        {"name": "A09 AOI检测",    "params": {}},
        {"name": "A10 分拣",       "params": {"bin": 3}},
    ]),
    ("system", "系统 (6)", [
        {"name": "S00 任务调度", "params": {"policy": "fifo"}},
        {"name": "S01 工作流",   "params": {"file": "flow.json"}},
        {"name": "S02 数据闭环", "params": {"mode": "auto"}},
        {"name": "S03 日志",     "params": {"level": "info"}},
        {"name": "S04 W&B监控",  "params": {}},
        {"name": "S05 心跳",     "params": {"interval": 5}},
    ]),
    ("hardware", "硬件 (8)", [
        {"name": "H00 Orin Nano",  "params": {"ip": "192.168.23.10", "port": 8765, "fps": 30}},
        {"name": "H01 MAC",        "params": {"ip": "192.168.23.1", "port": 8769}},
        {"name": "H02 4090训练",   "params": {"host": "39.102.211.79", "port": 50054}},
        {"name": "H03 机械臂",     "params": {"model": "Z700", "dof": 6}},
        {"name": "H04 EtherCAT",   "params": {"rate": 1000}},
        {"name": "H05 相机",       "params": {"res": "480x640", "fps": 30}},
        {"name": "H06 力传感器",   "params": {"range": 50}},
        {"name": "H07 扫码枪",     "params": {}},
    ]),
]


def gen_id():
    """节点 id: n + 时间戳 + 3位随机 (与 web 同规则)"""
    return "n%d%s" % (int(time.time() * 1000), ''.join(
        random.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(3)))


def link_id():
    return "l%d%s" % (int(time.time() * 1000), ''.join(
        random.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(2)))


# ════════════════════════════════════════════════════════════════
# 参数面板 (Block Parameters — 对标 Simulink 双击弹窗)
# ════════════════════════════════════════════════════════════════
class BlockParamsDialog(QDialog):
    def __init__(self, node, parent=None):
        super().__init__(parent)
        self.node = node
        self.setWindowTitle(f"Block Parameters: {node['name']}")
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)

        head = QLabel(f"{NODE_TYPES.get(node['type'], {}).get('cn', node['type'])} · {node['name']}")
        head.setStyleSheet("font-size:14px; font-weight:700; color:#fff; padding:4px;")
        lay.addWidget(head)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        self._edits = {}

        # 名称 (行内编辑)
        self._edits["name"] = QLineEdit(node["name"])
        form.addRow("名称", self._edits["name"])

        # 参数
        params = node.get("params", {})
        if not params:
            lab = QLabel("(无参数)")
            lab.setStyleSheet("color:#888; font-size:11px;")
            form.addRow("参数", lab)
        for k, v in params.items():
            if isinstance(v, bool):
                cb = QComboBox(); cb.addItems(["true", "false"])
                cb.setCurrentText("true" if v else "false")
                self._edits[k] = cb
            elif isinstance(v, (int, float)):
                if isinstance(v, float):
                    sb = QDoubleSpinBox()
                    sb.setRange(-1e9, 1e9)
                    sb.setValue(v)
                else:
                    sb = QSpinBox()
                    sb.setRange(-10**9, 10**9)
                    sb.setValue(int(v))
                self._edits[k] = sb
            else:
                le = QLineEdit(str(v))
                self._edits[k] = le
            form.addRow(k, self._edits[k])

        lay.addLayout(form)

        # 端口说明
        info = QLabel(f"输入: {len(node.get('inputs', []))} · 输出: {len(node.get('outputs', []))}")
        info.setStyleSheet("color:#666; font-size:10px;")
        lay.addWidget(info)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._apply)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _apply(self):
        n = self.node
        n["name"] = self._edits["name"].text().strip() or n["name"]
        for k, w in self._edits.items():
            if k == "name":
                continue
            if k not in n.get("params", {}):
                continue
            cur = n["params"][k]
            if isinstance(cur, bool):
                n["params"][k] = w.currentText() == "true"
            elif isinstance(cur, int):
                n["params"][k] = int(w.value())
            elif isinstance(cur, float):
                n["params"][k] = float(w.value())
            else:
                n["params"][k] = w.text()
        self.accept()


# ════════════════════════════════════════════════════════════════
# 画布节点 (QGraphicsItem)
# ════════════════════════════════════════════════════════════════
class SimNodeItem(QGraphicsObject):
    def __init__(self, node, scene_ref):
        super().__init__()
        self.node = node
        self.scene_ref = scene_ref
        self.w = node.get("w", 150)
        self.h = DH
        self.setPos(node["x"], node["y"])
        # 不用 ItemIsMovable: 拖动由 SimCanvas 手动 setPos 接管,
        # 避免 QGraphicsScene 默认"移动所有选中项"导致联动
        self.setFlags(QGraphicsItem.ItemIsSelectable |
                      QGraphicsItem.ItemSendsGeometryChanges)
        self.setZValue(10)

    def boundingRect(self):
        return QRectF(0, 0, self.w, self.h).adjusted(-12, -12, 12, 12)

    def paint(self, painter, opt, widget=None):
        t = self.node["type"]
        color = QColor(COLORS.get(t, "#58a6ff"))
        painter.setRenderHint(QPainter.Antialiasing)
        # 主体
        grad = QLinearGradient(0, 0, 0, self.h)
        grad.setColorAt(0, QColor("#1a1f2b"))
        grad.setColorAt(1, QColor("#111318"))
        painter.setBrush(grad)
        pen = QPen(color, 1.6)
        if self.isSelected():
            pen.setWidthF(2.4)
            pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.drawRoundedRect(QRectF(0, 0, self.w, self.h), 6, 6)
        # 标题
        painter.setPen(QColor("#ddd"))
        f = QFont("Arial", 9, QFont.Bold)
        painter.setFont(f)
        name = self.node["name"]
        if len(name) > 16:
            name = name[:15] + "…"
        painter.drawText(QRectF(12, 4, self.w - 16, 20), Qt.AlignVCenter | Qt.AlignLeft, name)
        # 类型标签
        painter.setPen(color)
        painter.setFont(QFont("Arial", 7))
        painter.drawText(QRectF(12, 22, self.w - 16, 14), Qt.AlignVCenter | Qt.AlignLeft,
                         NODE_TYPES.get(t, {}).get("cn", t))
        # 输入端口 (左)
        painter.setBrush(color)
        painter.setPen(QPen(QColor("#0a0a0f"), 1))
        painter.drawEllipse(QPointF(0, self.h / 2), 5, 5)
        # 输出端口 (右)
        painter.drawEllipse(QPointF(self.w, self.h / 2), 5, 5)
        # 参数摘要
        params = self.node.get("params", {})
        if params:
            first = list(params.items())[0]
            painter.setPen(QColor("#8b949e"))
            painter.setFont(QFont("Consolas", 7))
            painter.drawText(QRectF(12, 36, self.w - 16, 12), Qt.AlignVCenter | Qt.AlignLeft,
                             f"{first[0]}={first[1]}")

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange:
            self.node["x"] = round(value.x())
            self.node["y"] = round(value.y())
            self.scene_ref.on_node_moved(self)
        return super().itemChange(change, value)

    def mouseDoubleClickEvent(self, e):
        dlg = BlockParamsDialog(self.node, None)
        if dlg.exec_() == QDialog.Accepted:
            self.update()
        e.accept()


# ════════════════════════════════════════════════════════════════
# 连线 (贝塞尔, 与 web 同款)
# ════════════════════════════════════════════════════════════════
class SimLinkItem(QGraphicsObject):
    def __init__(self, link, src, dst, scene_ref):
        super().__init__()
        self.link = link
        self.src = src
        self.dst = dst
        self.scene_ref = scene_ref
        self.setZValue(5)
        self.setFlags(QGraphicsItem.ItemIsSelectable)
        self.setAcceptHoverEvents(True)
        self._hover = False

    def boundingRect(self):
        """动态覆盖实际路径区域 (Simulink 连线命中区), 避免固定矩形"""
        path = self._path()
        r = path.boundingRect()
        return r.adjusted(-12, -12, 12, 12)

    def shape(self):
        """连线命中区域 = 路径本身 (细长), 避免巨大矩形误吞点击"""
        stroker = QPainterPathStroker()
        stroker.setWidth(14)
        return stroker.createStroke(self._path())

    def _path(self):
        a = self.src.scenePos()
        b = self.dst.scenePos()
        ax, ay = a.x() + self.src.w, a.y() + self.src.h / 2
        bx, by = b.x(), b.y() + self.dst.h / 2
        c1x, c2x = ax + (bx - ax) * .5, bx - (bx - ax) * .5
        path = QPainterPath(QPointF(ax, ay))
        path.cubicTo(c1x, ay, c2x, by, bx, by)
        return path

    def paint(self, painter, opt, widget=None):
        t = self.src.node["type"]
        color = QColor(COLORS.get(t, "#58a6ff"))
        painter.setRenderHint(QPainter.Antialiasing)
        path = self._path()
        pen = QPen(color, 2.5 if self._hover or self.isSelected() else 1.8)
        pen.setStyle(Qt.DashLine if self.isSelected() else Qt.SolidLine)
        painter.setPen(pen)
        painter.drawPath(path)
        # 箭头 (指向输入)
        b = self.dst.scenePos()
        bx, by = b.x(), b.y() + self.dst.h / 2
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        tri = QPolygonF([QPointF(bx - 3, by - 4), QPointF(bx - 3, by + 4), QPointF(bx + 4, by)])
        painter.drawPolygon(tri)

    def hoverEnterEvent(self, e):
        self._hover = True; self.update(); e.accept()

    def hoverLeaveEvent(self, e):
        self._hover = False; self.update(); e.accept()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            # 点击连线删除 (对标 web: 点击连线中点删除)
            self.scene_ref.delete_link(self.link)
            e.accept()
        else:
            super().mousePressEvent(e)


# ════════════════════════════════════════════════════════════════
# 画布视图
# ════════════════════════════════════════════════════════════════
class SimCanvas(QGraphicsView):
    flow_changed = pyqtSignal()
    log = pyqtSignal(str)

    def __init__(self, module):
        super().__init__()
        self.module = module
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setBackgroundBrush(QColor("#0a0a0f"))
        # NoDrag: 让 ItemIsMovable 的节点可自由拖动 (RubberBandDrag 会拦截节点移动)
        self.setDragMode(QGraphicsView.NoDrag)
        # 空格键临时平移 (Simulink 习惯: 按住空格拖动画布)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self._drag_from = None       # 连线起点 (SimNodeItem)
        self._tmp_line = None        # 临时连线
        self._drag_node = None       # 手动拖动的节点 (只移动它, 绕开scene多选)
        self._drag_offset = QPointF()  # 按下点与节点原点的偏移
        self._panning = False
        self._pan_start = None
        self._scale = 1.0

    def drawBackground(self, painter, rect):
        # 网格点 (Simulink 画布风格)
        painter.fillRect(rect, QColor("#0a0a0f"))
        grid = 40
        left = int(rect.left()) - (int(rect.left()) % grid)
        top = int(rect.top()) - (int(rect.top()) % grid)
        painter.setPen(QPen(QColor("#14161c"), 1))
        for x in range(left, int(rect.right()), grid):
            for y in range(top, int(rect.bottom()), grid):
                painter.drawPoint(x, y)

    def wheelEvent(self, e):
        # Ctrl+滚轮 = 缩放 (对标 web)
        if e.modifiers() & Qt.ControlModifier:
            factor = 1.1 if e.angleDelta().y() > 0 else 0.9
            self._scale = max(0.2, min(3.0, self._scale * factor))
            self.scale(factor, factor)
            self.module.on_zoom(self._scale)
        else:
            super().wheelEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MiddleButton:
            self._panning = True
            self._pan_start = e.pos()
            self.setCursor(Qt.ClosedHandCursor)
            return
        if e.button() == Qt.LeftButton:
            item = self.itemAt(e.pos())
            # 点击节点
            if isinstance(item, SimNodeItem):
                p = self.mapToScene(e.pos())
                n = item
                rp = n.scenePos()
                out_x = rp.x() + n.w
                mid_y = rp.y() + n.h / 2
                # 输出端口 → 连线模式
                if abs(p.x() - out_x) < 12 and abs(p.y() - mid_y) < 12:
                    self._drag_from = n
                    self._tmp_line = self._scene.addLine(0, 0, 0, 0,
                        QPen(QColor(COLORS.get(n.node["type"], "#58a6ff")), 2, Qt.DashLine))
                    return
                # 节点主体 → 手动拖动 (只移动它, 绕开 scene 多选联动)
                if not (e.modifiers() & Qt.ControlModifier):
                    for it in self._scene.selectedItems():
                        if it is not item:
                            it.setSelected(False)
                    item.setSelected(True)
                self._drag_node = item
                self._drag_offset = p - rp
                return
        super().mousePressEvent(e)
        # 点击空白处 (非Ctrl): 清除所有选中
        if e.button() == Qt.LeftButton and not (e.modifiers() & Qt.ControlModifier):
            item = self.itemAt(e.pos())
            if not isinstance(item, (SimNodeItem, SimLinkItem)):
                self._scene.clearSelection()

    def mouseMoveEvent(self, e):
        if self._panning:
            delta = e.pos() - self._pan_start
            self._pan_start = e.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            return
        if self._drag_from and self._tmp_line:
            p = self.mapToScene(e.pos())
            s = self._drag_from.scenePos()
            self._tmp_line.setLine(s.x() + self._drag_from.w, s.y() + self._drag_from.h / 2, p.x(), p.y())
            return
        if self._drag_node:
            # 手动拖动: 只移动按下的节点
            p = self.mapToScene(e.pos())
            self._drag_node.setPos(p - self._drag_offset)
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._panning:
            self._panning = False
            self.setCursor(Qt.ArrowCursor)
            return
        if self._drag_from and self._tmp_line:
            self._scene.removeItem(self._tmp_line)
            self._tmp_line = None
            item = self.itemAt(e.pos())
            if isinstance(item, SimNodeItem) and item is not self._drag_from:
                self.module.add_link(self._drag_from, item)
            self._drag_from = None
            return
        if self._drag_node:
            self._drag_node = None
            return
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Delete:
            self.module.delete_selected()
            return
        if e.modifiers() & Qt.ControlModifier and e.key() == Qt.Key_D:
            self.module.duplicate_selected()
            return
        super().keyPressEvent(e)


# ════════════════════════════════════════════════════════════════
# 模块库面板 (左侧, 对标 Simulink Library Browser)
# ════════════════════════════════════════════════════════════════
class LibraryPanel(QFrame):
    def __init__(self, module):
        super().__init__()
        self.module = module
        self.setFixedWidth(220)
        self.setStyleSheet("background:#0d1117; border-right:1px solid #1e2740;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(4)

        title = QLabel("📚 模块库")
        title.setStyleSheet("color:#fff; font-size:13px; font-weight:700; padding:4px;")
        lay.addWidget(title)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.inner = QWidget()
        self.v = QVBoxLayout(self.inner)
        self.v.setContentsMargins(0, 0, 0, 0)
        self.v.setSpacing(2)

        # 工作流标签页 → 显示全部
        self._current_wf = None
        self._rebuild()

        self.scroll.setWidget(self.inner)
        lay.addWidget(self.scroll)

        hint = QLabel("点击添加 · 双击改参 · 输出→输入连线\n点线删除 · Ctrl+滚轮缩放 · 顶部工作流过滤")
        hint.setStyleSheet("color:#666; font-size:9px; padding:4px;")
        lay.addWidget(hint)

    def _rebuild(self):
        """重建模块库列表 (按工作流过滤)"""
        # 清空
        while self.v.count():
            item = self.v.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        for ntype, gname, items in LIBRARY:
            # 工作流过滤: 按节点类型匹配
            wf_of = {t: wf for wf, t in WORKFLOW_TYPES.items()}
            if self._current_wf and wf_of.get(ntype) != self._current_wf:
                continue
            lab = QLabel(f"{gname}")
            lab.setStyleSheet(f"color:{COLORS[ntype]}; font-size:11px; font-weight:700; padding:6px 2px 2px;")
            self.v.addWidget(lab)
            for it in items:
                btn = QToolButton()
                btn.setText(f"⬡  {it['name']}")
                btn.setStyleSheet(f"""
                    QToolButton {{ background:#14181f; color:#c9d1d9; border:1px solid #1e2740;
                    border-radius:4px; padding:4px 8px; font-size:11px; text-align:left; }}
                    QToolButton:hover {{ border-color:{COLORS[ntype]}; color:#fff; }}
                """)
                btn.clicked.connect(lambda _, t=ntype, nm=it["name"], ps=it["params"]:
                                    self.module.add_node_at_center(t, nm, ps))
                self.v.addWidget(btn)
        self.v.addStretch()

    def set_filter(self, wf_key):
        """按工作流过滤模块库 (None=全部)"""
        self._current_wf = wf_key
        self._rebuild()


# ════════════════════════════════════════════════════════════════
# Simulink 模式主模块
# ════════════════════════════════════════════════════════════════
class SimulinkModule(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.nodes = []    # [{id,type,name,x,y,w,params,inputs,outputs,actions}]
        self.links = []    # [{id,f,t,f_port,t_port}]
        self._items = {}   # node_id -> SimNodeItem
        self._link_items = []
        self._sim_running = False
        self._sim_t = 0.0
        self._sim_dt = 0.01
        self._sim_t_end = 10.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        # 教程状态
        self._tutorial_active = False
        self._tutorial_step = -1
        self._tutorial_hl = None      # 当前高亮 widget
        self._tutorial_orig_ss = {}   # 原样式表备份
        self._tutorial_timer = QTimer(self)
        self._tutorial_timer.timeout.connect(self._tutorial_pulse)
        self._tutorial_pulse_on = False
        self._build()
        self._seed_default_flow()

    # ── UI ──
    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Hero 标题条 (对标 MathWorks 解决方案页 Hero) ──
        hero = QFrame()
        hero.setStyleSheet("background:qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #0d1117, stop:0.6 #0f1a24, stop:1 #0d1117); border-bottom:1px solid #1e2740;")
        hero.setFixedHeight(64)
        hl = QHBoxLayout(hero)
        hl.setContentsMargins(16, 8, 16, 8)
        hl.setSpacing(14)
        hero_title = QLabel("Z-MAX 具身智能 · Simulink 模式")
        hero_title.setStyleSheet("color:#fff; font-size:19px; font-weight:800; background:transparent; border:none;")
        hl.addWidget(hero_title)
        hero_sub = QLabel("使用 XSpace Studio 实现产线机器人的感知、规划与控制 · 模块库拖拽 · 连线仿真 · 数据闭环")
        hero_sub.setStyleSheet("color:#8b949e; font-size:11px; background:transparent; border:none;")
        hl.addWidget(hero_sub)
        hl.addStretch()
        ver = QLabel("v1.0 · zmax-simulink")
        ver.setStyleSheet("color:#00d4aa; font-size:10px; font-family:Consolas; background:transparent; border:none;")
        hl.addWidget(ver)
        outer.addWidget(hero)

        # ── 工作流导航条 (对标 MathWorks 6 大功能分区) ──
        wf = QFrame()
        wf.setStyleSheet("background:#0a0e14; border-bottom:1px solid #1e2740;")
        wf.setFixedHeight(40)
        wfl = QHBoxLayout(wf)
        wfl.setContentsMargins(10, 4, 10, 4)
        wfl.setSpacing(4)
        self._wf_btns = {}
        for key, label in [("data", "① 访问·标注数据"), ("scene", "② 仿真场景"),
                           ("plan", "③ 规划·控制"), ("percept", "④ 感知算法"),
                           ("deploy", "⑤ 部署"), ("test", "⑥ 集成·测试")]:
            b = QPushButton(label)
            b.setCheckable(True)
            b.setStyleSheet("""
                QPushButton { background:transparent; color:#8b949e; border:1px solid transparent;
                border-radius:5px; padding:4px 12px; font-size:11px; font-weight:600; }
                QPushButton:hover { color:#fff; background:#14181f; }
                QPushButton:checked { color:#00d4aa; background:#00d4aa1a; border-color:#00d4aa44; }
            """)
            b.clicked.connect(lambda _, k=key: self._filter_library(k))
            self._wf_btns[key] = b
            wfl.addWidget(b)
        wfl.addStretch()
        outer.addWidget(wf)

        # 工具栏 (对标 Simulink 工具条)
        tb = QFrame()
        tb.setStyleSheet("background:#0d1117; border-bottom:1px solid #1e2740;")
        tb.setFixedHeight(44)
        tl = QHBoxLayout(tb)
        tl.setContentsMargins(10, 4, 10, 4)
        tl.setSpacing(8)

        def mk_btn(text, tip, fn, color="#58a6ff"):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setStyleSheet(f"""
                QPushButton {{ background:#14181f; color:{color}; border:1px solid #1e2740;
                border-radius:5px; padding:5px 14px; font-size:12px; font-weight:600; }}
                QPushButton:hover {{ border-color:{color}; background:#1a2230; }}
                QPushButton:disabled {{ color:#555; border-color:#222; }}
            """)
            b.clicked.connect(fn)
            return b

        self.btn_run = mk_btn("▶ 运行", "按拓扑执行仿真 (Simulink Run)", self.start_sim, "#00d4aa")
        self.btn_step = mk_btn("⏭ 单步", "执行一个时间步", self.step_sim)
        self.btn_stop = mk_btn("⏹ 停止", "停止仿真", self.stop_sim, "#ff4444")
        self.btn_stop.setEnabled(False)
        self.btn_tutorial = mk_btn("📖 教程", "交互式引导: 高亮+文字提示, 全程鼠标", self.start_tutorial, "#d4a800")
        tl.addWidget(self.btn_run)
        tl.addWidget(self.btn_step)
        tl.addWidget(self.btn_stop)
        tl.addSpacing(8)
        tl.addWidget(self.btn_tutorial)

        tl.addSpacing(16)
        tl.addWidget(QLabel("仿真时间"))
        self.sp_t_end = QDoubleSpinBox(); self.sp_t_end.setRange(0.1, 3600)
        self.sp_t_end.setValue(self._sim_t_end); self.sp_t_end.setSuffix(" s")
        self.sp_t_end.setStyleSheet("background:#14181f; color:#fff; border:1px solid #1e2740; border-radius:4px; padding:2px 6px;")
        tl.addWidget(self.sp_t_end)
        tl.addWidget(QLabel("步长"))
        self.sp_dt = QDoubleSpinBox(); self.sp_dt.setRange(0.001, 1.0)
        self.sp_dt.setValue(self._sim_dt); self.sp_dt.setDecimals(3)
        self.sp_dt.setStyleSheet("background:#14181f; color:#fff; border:1px solid #1e2740; border-radius:4px; padding:2px 6px;")
        tl.addWidget(self.sp_dt)

        tl.addStretch()
        self.lbl_clock = QLabel("t = 0.00s")
        self.lbl_clock.setStyleSheet("color:#00d4aa; font-size:13px; font-weight:700; font-family:Consolas;")
        tl.addWidget(self.lbl_clock)

        btn_save = mk_btn("💾 导出", "导出工作流 JSON (与 web 同格式)", self.export_flow)
        btn_load = mk_btn("📂 导入", "导入工作流 JSON", self.import_flow)
        self.btn_save = btn_save
        self.btn_load = btn_load
        tl.addWidget(btn_save)
        tl.addWidget(btn_load)

        outer.addWidget(tb)

        # 参考应用条 (对标 MathWorks 参考应用列表)
        ra = QFrame()
        ra.setStyleSheet("background:#0a0e14; border-bottom:1px solid #1e2740;")
        ra.setFixedHeight(38)
        ral = QHBoxLayout(ra)
        ral.setContentsMargins(10, 4, 10, 4)
        ral.setSpacing(6)
        ra_lab = QLabel("🗂 参考应用:")
        ra_lab.setStyleSheet("color:#8b949e; font-size:11px; font-weight:600; background:transparent; border:none;")
        ral.addWidget(ra_lab)
        self._ref_btns = {}
        for name, nodes, links in REFERENCE_APPS:
            b = QPushButton(name)
            b.setStyleSheet("""
                QPushButton { background:#14181f; color:#c9d1d9; border:1px solid #1e2740;
                border-radius:4px; padding:3px 10px; font-size:10px; }
                QPushButton:hover { border-color:#00d4aa; color:#00d4aa; }
            """)
            b.clicked.connect(lambda _, nm=name, nd=nodes, lk=links: self.load_reference_app(nm, nd, lk))
            self._ref_btns[name] = b
            ral.addWidget(b)
        ral.addStretch()
        outer.addWidget(ra)

        # 主体: 库 + 画布
        split = QSplitter(Qt.Horizontal)
        self.canvas = SimCanvas(self)
        self.canvas.flow_changed.connect(lambda: self._sync())
        self.canvas.log.connect(self._log)
        self.library = LibraryPanel(self)
        split.addWidget(self.library)
        split.addWidget(self.canvas)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        outer.addWidget(split, 1)

        # 底部日志 (对标 Simulink 诊断)
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(110)
        self.log_box.setStyleSheet("background:#0d1117; color:#8b949e; border:none; border-top:1px solid #1e2740; font-size:11px; font-family:Consolas;")
        outer.addWidget(self.log_box)
        self._log("Simulink 模式就绪 · 0帧起手, 从左侧模块库开始搭建")

    # ── 初始工作流: 空画布 (0帧起手) ──
    def _seed_default_flow(self):
        pass  # 空画布, 用户从零搭建

    # ════════════════════════════════════════════════════════════
    # 交互式教程 (高亮 + 文字提示, 全程鼠标)
    # ════════════════════════════════════════════════════════════
    TUTORIAL_STEPS = [
        ("ref",  "📦 取料·100G 闭环",
         "① 点击下方参考应用「📦 取料·100G 闭环」,\n自动生成 4 节点 + 3 连线的工作流 (共6步)"),
        ("node", None,
         "② 鼠标左键按住节点拖动, 试试移动它\n(注意: 只移动按下的节点, 其他节点不动)"),
        ("btn_run", None,
         "③ 点击工具栏「▶ 运行」, 按拓扑顺序执行仿真\n(Orin→ACT→取料→力控达标)"),
        ("btn_step", None,
         "④ 点击「⏭ 单步」, 每次执行一个时间步,\n观察底部日志中的节点执行记录"),
        ("btn_stop", None,
         "⑤ 点击「⏹ 停止」结束仿真,\n时钟归位, 运行按钮恢复"),
        ("btn_save", None,
         "⑥ 点击「💾 导出」, 把工作流保存为 JSON,\n该文件可直接被 CI/CD 验证器校验"),
        ("done", None,
         "🎉 教程完成! 你已经掌握 Simulink 模式:\n参考应用 → 拖拽 → 仿真 → 导出 → CI校验\n点击任意处退出教程"),
    ]

    def start_tutorial(self):
        """开始交互式教程"""
        if self._tutorial_active:
            self._tutorial_cleanup()
            return
        self._tutorial_active = True
        self._tutorial_step = -1
        self._log("📖 教程开始 · 跟着高亮提示操作, 全程鼠标")
        self._tutorial_next()

    def _tutorial_next(self):
        """推进到下一步: 高亮目标 + 气泡提示"""
        self._tutorial_step += 1
        if self._tutorial_step >= len(self.TUTORIAL_STEPS):
            self._tutorial_cleanup()
            self._log("📖 教程完成!")
            return
        kind, target, msg = self.TUTORIAL_STEPS[self._tutorial_step]

        if kind == "ref":
            widget = self._ref_btns.get(target)
        elif kind == "node":
            widget = self.canvas  # 高亮画布
        elif kind in ("btn_run", "btn_step", "btn_stop", "btn_save"):
            widget = getattr(self, {"btn_run": "btn_run", "btn_step": "btn_step",
                                    "btn_stop": "btn_stop", "btn_save": "btn_save"}[kind])
        else:  # done
            self._tutorial_show_bubble("🎉 完成!", msg)
            return

        if widget is None:
            widget = self.canvas
        self._tutorial_highlight(widget)
        self._tutorial_show_bubble(f"📖 第{self._tutorial_step + 1}/{len(self.TUTORIAL_STEPS)}步", msg)

    def _tutorial_highlight(self, widget):
        """高亮目标控件: 记录原样式, 应用青色发光边框"""
        self._tutorial_cleanup_highlight()
        self._tutorial_hl = widget
        self._tutorial_orig_ss[id(widget)] = widget.styleSheet()
        widget.setStyleSheet(widget.styleSheet() +
            " QPushButton { border:3px solid #ffd700; border-radius:6px; }" if isinstance(widget, QPushButton)
            else " border:3px solid #ffd700;")
        self._tutorial_pulse_on = True
        self._tutorial_timer.start(400)

    def _tutorial_pulse(self):
        """高亮脉冲闪烁 (金色 ↔ 青色)"""
        if self._tutorial_hl is None:
            return
        self._tutorial_pulse_on = not self._tutorial_pulse_on
        color = "#ffd700" if self._tutorial_pulse_on else "#00d4aa"
        w = self._tutorial_hl
        if isinstance(w, QPushButton):
            w.setStyleSheet(w.styleSheet().rsplit(" QPushButton {", 1)[0] +
                f" QPushButton {{ border:3px solid {color}; border-radius:6px; }}")
        else:
            w.setStyleSheet(w.styleSheet().rsplit(" border:", 1)[0] + f" border:3px solid {color};")

    def _tutorial_cleanup_highlight(self):
        """清除高亮, 恢复原样式"""
        if self._tutorial_timer.isActive():
            self._tutorial_timer.stop()
        if self._tutorial_hl is not None:
            orig = self._tutorial_orig_ss.get(id(self._tutorial_hl), "")
            self._tutorial_hl.setStyleSheet(orig)
            self._tutorial_hl = None

    def _tutorial_show_bubble(self, title, msg):
        """气泡提示: 用日志 + 状态栏显示 (轻量实现)"""
        self._log(f"{title}\n{msg}")

    def _tutorial_on_action(self, action):
        """用户执行了动作 → 检查是否匹配当前步骤, 匹配则推进"""
        if not self._tutorial_active:
            return
        kind, target, _ = self.TUTORIAL_STEPS[self._tutorial_step] if 0 <= self._tutorial_step < len(self.TUTORIAL_STEPS) else (None, None, None)
        matched = False
        if kind == "ref" and action == "ref":
            matched = True
        elif kind == "btn_run" and action == "run":
            matched = True
        elif kind == "btn_step" and action == "step":
            matched = True
        elif kind == "btn_stop" and action == "stop":
            matched = True
        elif kind == "btn_save" and action == "save":
            matched = True
        if matched:
            self._tutorial_next()

    def _tutorial_on_node_moved(self):
        """节点被拖动 → 推进教程 (node 步骤)"""
        if not self._tutorial_active:
            return
        if self._tutorial_step < len(self.TUTORIAL_STEPS) and self.TUTORIAL_STEPS[self._tutorial_step][0] == "node":
            self._tutorial_next()

    def _tutorial_cleanup(self):
        """退出教程: 清除高亮"""
        self._tutorial_active = False
        self._tutorial_cleanup_highlight()
        self._tutorial_step = -1

    # ── 工作流过滤 (对标 MathWorks 6 大分区导航) ──
    def _filter_library(self, wf_key):
        for k, b in self._wf_btns.items():
            b.setChecked(k == wf_key)
        self.library.set_filter(wf_key)
        self._log(f"🗂 工作流: {dict(data='① 访问·标注', scene='② 仿真场景', plan='③ 规划·控制', percept='④ 感知', deploy='⑤ 部署', test='⑥ 集成·测试').get(wf_key, wf_key)} · 模块库已过滤")

    # ── 参考应用模板 (对标 MathWorks 参考应用列表) ──
    def load_reference_app(self, name, node_specs, link_specs):
        if self.nodes:
            ret = QMessageBox.question(self, "加载参考应用",
                                       f"加载「{name}」将清空当前画布，继续？",
                                       QMessageBox.Yes | QMessageBox.No)
            if ret != QMessageBox.Yes:
                return
        self.clear()
        ids = []
        base_x, base_y = 120, 80
        for i, (ntype, nm, params) in enumerate(node_specs):
            n = self.add_node(ntype, nm, base_x + i * 260, base_y, params)
            ids.append(n["id"])
        for fi, ti in link_specs:
            if fi < len(ids) and ti < len(ids):
                self.add_link(self._items[ids[fi]], self._items[ids[ti]])
        self.canvas._scene.update()
        self._log(f"🗂 已加载参考应用: {name} ({len(ids)}节点 {len(link_specs)}连线) · 双击节点改参数")
        self._tutorial_on_action("ref")

    # ── 节点操作 ──
    def add_node_at_center(self, ntype, name, params=None):
        c = self.canvas.mapToScene(self.canvas.viewport().rect().center())
        return self.add_node(ntype, name, int(c.x() - 75 + random.uniform(-30, 30)),
                             int(c.y() - 25 + random.uniform(-30, 30)), params)

    def add_node(self, ntype, name, x, y, params=None):
        node = {
            "id": gen_id(),
            "type": ntype,
            "name": name,
            "x": int(x), "y": int(y), "w": 150,
            "icon": {"condition": "❖", "model": "◈", "action": "➤",
                     "system": "◉", "hardware": "▣"}[ntype],
            "color": COLORS[ntype],
            "params": params or {},
            "inputs": [{"id": "in1", "label": "in", "dtype": "any"}],
            "outputs": [{"id": "out1", "label": "out", "dtype": "any"}],
            "actions": [],
        }
        self.nodes.append(node)
        item = SimNodeItem(node, self)
        self._items[node["id"]] = item
        self.canvas._scene.addItem(item)
        self.canvas._scene.update()
        self._log(f"➕ 添加节点 [{NODE_TYPES[ntype]['cn']}] {name}")
        self._sync()
        return node

    def add_link(self, src_item, dst_item):
        src, dst = src_item.node, dst_item.node
        if src["id"] == dst["id"]:
            return
        # 防重复
        for lk in self.links:
            if lk["f"] == src["id"] and lk["t"] == dst["id"]:
                self._log("⚠️ 连线已存在")
                return
        link = {"id": link_id(), "f": src["id"], "t": dst["id"],
                "f_port": "out1", "t_port": "in1"}
        self.links.append(link)
        self._draw_links()
        self._log(f"🔗 {src['name']} → {dst['name']}")
        self._sync()

    def delete_link(self, link):
        if link in self.links:
            self.links.remove(link)
            self._draw_links()
            self._log("🗑 连线已删除")
            self._sync()

    def delete_selected(self):
        sel = [it for it in self._items.values() if it.isSelected()]
        if not sel:
            return
        ids = {it.node["id"] for it in sel}
        for it in sel:
            self.canvas._scene.removeItem(it)
        self.nodes = [n for n in self.nodes if n["id"] not in ids]
        self.links = [l for l in self.links if l["f"] not in ids and l["t"] not in ids]
        self._items = {k: v for k, v in self._items.items() if k not in ids}
        self._draw_links()
        self._log(f"🗑 删除 {len(sel)} 个节点")
        self._sync()

    def duplicate_selected(self):
        sel = [it for it in self._items.values() if it.isSelected()]
        for it in sel:
            n = it.node
            self.add_node(n["type"], n["name"] + " (副本)",
                          n["x"] + 40, n["y"] + 40, dict(n.get("params", {})))

    # ── 连线绘制 ──
    def _draw_links(self):
        for li in self._link_items:
            self.canvas._scene.removeItem(li)
        self._link_items = []
        for lk in self.links:
            s, d = self._items.get(lk["f"]), self._items.get(lk["t"])
            if s and d:
                item = SimLinkItem(lk, s, d, self)
                self._link_items.append(item)
                self.canvas._scene.addItem(item)

    def on_node_moved(self, item):
        for li in self._link_items:
            li.update()
        self._tutorial_on_node_moved()

    def on_zoom(self, scale):
        self._log(f"🔍 {round(scale * 100)}%")

    # ── 仿真 (对标 Simulink Run/Step) ──
    def _tick(self):
        """定时器驱动连续仿真"""
        self.step_sim()
        if self._sim_t >= self._sim_t_end:
            self.stop_sim()

    def start_sim(self):
        if not self.nodes:
            self._log("⚠️ 画布为空 — 先从左侧模块库添加节点 (0帧起手)")
            return
        self._sim_t = 0.0
        self._sim_dt = self.sp_dt.value()
        self._sim_t_end = self.sp_t_end.value()
        self._sim_running = True
        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self._log(f"▶ 仿真开始 · t∈[0, {self._sim_t_end}s] · dt={self._sim_dt}s · 节点数={len(self.nodes)}")
        self._timer.start(max(16, int(self._sim_dt * 1000 / 10)))  # 每步最多10x加速
        self._tutorial_on_action("run")

    def step_sim(self):
        if not self.nodes:
            self._log("⚠️ 画布为空")
            return
        self._sim_t += self._sim_dt
        self._exec_topological()
        self.lbl_clock.setText(f"t = {self._sim_t:.2f}s")
        self._tutorial_on_action("step")
        if self._sim_t >= self._sim_t_end:
            self.stop_sim()

    def _exec_topological(self):
        order = self._topo_sort()
        self._log(f"⚡ 单步执行 [{len(order)} 节点] · " + " → ".join(
            [self._by_id(n)["name"] for n in order][:6]) + (" …" if len(order) > 6 else ""))
        for nid in order:
            n = self._by_id(nid)
            self._sim_node(n)
        self.lbl_clock.setText(f"t = {self._sim_t:.2f}s")

    def _sim_node(self, n):
        """本地模拟节点执行 (真实后端: 转发到硬件/远程, 后续接入)"""
        t = n["type"]
        p = n.get("params", {})
        if t == "model":
            self._log(f"  🧠 {n['name']}: 推理完成 ({p.get('checkpoint', 'model')})")
        elif t == "action":
            self._log(f"  ➤ {n['name']}: 动作执行 {' | '.join(f'{k}={v}' for k, v in p.items())}")
        elif t == "hardware":
            self._log(f"  ▣ {n['name']}: 心跳 OK ({p.get('ip', '-')})")
        elif t == "condition":
            self._log(f"  ❖ {n['name']}: 条件评估 → 通过")
        else:
            self._log(f"  ◉ {n['name']}: 调度节点运行")

    def _topo_sort(self):
        """DAG 拓扑排序 (连线确定执行顺序)"""
        adj = {n["id"]: [] for n in self.nodes}
        indeg = {n["id"]: 0 for n in self.nodes}
        for l in self.links:
            if l["f"] in adj and l["t"] in adj:
                adj[l["f"]].append(l["t"])
                indeg[l["t"]] += 1
        q = [nid for nid, d in indeg.items() if d == 0]
        order = []
        while q:
            nid = q.pop(0)
            order.append(nid)
            for m in adj[nid]:
                indeg[m] -= 1
                if indeg[m] == 0:
                    q.append(m)
        # 剩余 (有环) 追加
        for n in self.nodes:
            if n["id"] not in order:
                order.append(n["id"])
        return order

    def stop_sim(self):
        self._sim_running = False
        self._timer.stop()
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self._log(f"⏹ 仿真停止 · t = {self._sim_t:.2f}s")
        self._tutorial_on_action("stop")

    def _by_id(self, nid):
        for n in self.nodes:
            if n["id"] == nid:
                return n
        return None

    # ── 导入/导出 (与 web 一致) ──
    def export_flow(self):
        flow = {"format": "zmax-simulink", "version": "1.0", "name": "untitled",
                "sim": {"dt": self._sim_dt, "t_end": self._sim_t_end, "solver": "fixed-step"},
                "nodes": self.nodes, "links": self.links}
        from PyQt5.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self, "导出工作流", "flow.json", "JSON (*.json)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(flow, f, ensure_ascii=False, indent=2)
            self._log(f"💾 已导出: {path}")
            self._tutorial_on_action("save")

    def import_flow(self):
        from PyQt5.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, "导入工作流", "", "JSON (*.json)")
        if not path:
            return
        try:
            flow = json.load(open(path, encoding="utf-8"))
            self.load_flow(flow)
            self._log(f"📂 已导入: {path}")
        except Exception as ex:
            QMessageBox.warning(self, "导入失败", str(ex))

    def load_flow(self, flow):
        self.clear()
        for n in flow.get("nodes", []):
            node = dict(n)
            node.setdefault("w", 150)
            node.setdefault("params", {})
            node.setdefault("inputs", [{"id": "in1", "label": "in", "dtype": "any"}])
            node.setdefault("outputs", [{"id": "out1", "label": "out", "dtype": "any"}])
            self.nodes.append(node)
            item = SimNodeItem(node, self)
            self._items[node["id"]] = item
            self.canvas._scene.addItem(item)
        for l in flow.get("links", []):
            self.links.append(dict(l))
        self._draw_links()
        self.canvas._scene.update()

    def clear(self):
        self.canvas._scene.clear()
        self.nodes = []
        self.links = []
        self._items = {}
        self._link_items = []

    def _sync(self):
        """节点变更 → 通知主窗口 (可用于推送 web /api/comfy/task)"""
        try:
            cb = getattr(self, "flow_synced", None) or getattr(self.window(), "on_flow_sync", None)
            if cb:
                cb({"format": "zmax-simulink", "nodes": self.nodes, "links": self.links})
        except Exception:
            pass

    def _log(self, msg):
        self.log_box.append(msg)
        self.log_box.verticalScrollBar().setValue(self.log_box.verticalScrollBar().maximum())


# ── 独立运行入口 (调试) ──
def main():
    from PyQt5.QtWidgets import QApplication
    app = QApplication(sys.argv)
    w = SimulinkModule()
    w.resize(1200, 760)
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
