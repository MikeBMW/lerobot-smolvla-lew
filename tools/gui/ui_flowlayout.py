#!/usr/bin/env python3
"""🧱 FlowLayout — 自动换行布局 (Qt 官方 Flow Layout 移植, PyQt5)

用途: simulink 画布顶部工具栏按钮放大后单行放不下 → 自动折到第二行,
      按钮永远保持 sizeHint 原始大小, 不会被 QHBoxLayout 压扁/文字挤在一起。

2026-08-25 老倪: "画布上面的按钮太小了, 里面的字都挤在一起了" → 按钮放大 +
本布局承载 (窄窗口/浮动画布时自动多行, 宽窗口时自动收成一行)。

兼容 QHBoxLayout 常用调用:
  - addWidget(w)
  - addSpacing(px)  → 插入固定宽度占位 (不换行时留间隔)
  - addStretch()    → 空操作 (流式布局靠换行, 无需弹簧)
"""
from PyQt5.QtCore import QMargins, QPoint, QRect, QSize, Qt
from PyQt5.QtWidgets import QFrame, QLayout, QSizePolicy, QSpacerItem


class FlowLayout(QLayout):
    """从左到右排列, 一行放不下自动折行。高度随宽度变化 (heightForWidth)。"""

    def __init__(self, parent=None, margin=(10, 6, 10, 6), h_spacing=10, v_spacing=8):
        super().__init__(parent)
        self._items = []
        self._h_space = h_spacing
        self._v_space = v_spacing
        if isinstance(margin, (tuple, list)):
            self.setContentsMargins(*margin)
        else:
            self.setContentsMargins(margin, margin, margin, margin)

    # ── QLayout 必需接口 ──
    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, idx):
        if 0 <= idx < len(self._items):
            return self._items[idx]
        return None

    def takeAt(self, idx):
        if 0 <= idx < len(self._items):
            return self._items.pop(idx)
        return None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Horizontal)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    # ── QHBoxLayout 兼容糖 ──
    def addSpacing(self, px):
        self.addItem(QSpacerItem(int(px), 1, QSizePolicy.Fixed, QSizePolicy.Minimum))

    def addStretch(self, _factor=0):
        return None  # 流式布局无需弹簧 (换行自然对齐左侧)

    def spacing(self):
        return self._h_space

    def setSpacing(self, px):
        self._h_space = int(px)

    # ── 核心排布 ──
    def _do_layout(self, rect, test_only):
        m = self.contentsMargins()
        eff = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y = eff.x(), eff.y()
        line_h = 0
        for it in self._items:
            # 隐藏控件 (如 ⬅ 返回总系统 默认 setVisible(False)) 不占位, 否则行里留空洞
            # ⚠️ 不能用 it.isEmpty(): QSpacerItem.isEmpty() 恒为 True, 会把 addSpacing 也吃掉
            try:
                _w = it.widget()
                if _w is not None and _w.isHidden():
                    continue
            except Exception:
                pass
            hint = it.sizeHint()
            w, h = hint.width(), hint.height()
            nx = x + w
            if nx > eff.right() + 1 and line_h > 0:   # 本行放不下 → 换行
                x = eff.x()
                y = y + line_h + self._v_space
                nx = x + w
                line_h = 0
            if not test_only:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x = nx + self._h_space
            line_h = max(line_h, h)
        return y + line_h - rect.y() + m.bottom()

    def contentsMargins(self):
        try:
            return super().contentsMargins()
        except Exception:
            return QMargins(10, 6, 10, 6)


class FlowBar(QFrame):
    """🧰 自动换行工具栏容器 — 高度随内容行数自适应 (不再 setFixedHeight 卡死 44px)

    QBoxLayout 对子 widget 的 heightForWidth 支持不稳定 → 这里在 resizeEvent 里
    显式把自身高度设成 FlowLayout 算出的所需高度 (同值不再 set, 不会递归抖动)。
    """

    def __init__(self, parent=None, margin=(10, 6, 10, 6), h_spacing=10, v_spacing=8):
        super().__init__(parent)
        self._flow = FlowLayout(self, margin=margin, h_spacing=h_spacing, v_spacing=v_spacing)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)

    def flow(self):
        return self._flow

    def _sync_height(self):
        try:
            need = self._flow.heightForWidth(max(1, self.width()))
            if need > 0 and need != self.minimumHeight():
                self.setFixedHeight(need)
        except Exception:
            pass

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._sync_height()

    def showEvent(self, ev):
        super().showEvent(ev)
        self._sync_height()
