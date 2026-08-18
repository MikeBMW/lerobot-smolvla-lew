# -*- coding: utf-8 -*-
"""
NodeLogicDialog — 节点逻辑查看/编辑器

交互模式 (老倪 2026-08-04 需求):
  · 右键节点 → 「📖 查看/编辑节点逻辑」→ 弹出本对话框
  · 上半: 节点名 + 类型 + 说明
  · 中部: 逻辑源码, ✏️ 可修改区金底高亮, 其余 = 🔒 框架区
  · 按钮: ✏️编辑 / 💾保存并生效(热重载) / 🔄恢复默认 / ❌关闭
  · 保存时检测框架区是否被改动 → 警告确认 (深色 QMessageBox)
"""
import os
import sys

from PyQt5.QtCore import Qt, QRect, QSize
from PyQt5.QtGui import QColor, QFont, QTextCursor, QTextFormat
from PyQt5.QtWidgets import (QDialog, QHBoxLayout, QLabel, QMessageBox,
                             QPlainTextEdit, QPushButton, QTextEdit,
                             QVBoxLayout, QFrame, QWidget)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import node_logic

# 🎨 2026-08-16 老倪铁律: 只能红/黑/白+高光灰 — 从 studio 导入 C_* (浅色主题自动跟随)
try:
    from studio import C_BG as _BG, C_BG2 as _PANEL, C_WHITE as _TEXT, \
        C_GRAY as _DIM, C_BLUE as _GOLD, C_GREEN as _GREEN, C_BORDER as _BRD
    _GOLD_BG = "#f0e8ec"     # ✏️ 可修改区底纹 (浅朱红调)
    _GOLD_LINE = "#b70032"   # ✏️ 分隔线 (朱红)
except Exception:
    _BG = "#0d1117"; _PANEL = "#161b22"; _TEXT = "#e6edf3"; _DIM = "#8b949e"
    _GOLD = "#ffd700"; _GOLD_BG = "#3d3410"; _GOLD_LINE = "#d4a800"; _GREEN = "#3fb950"
    _BRD = "#30363d"
_BTN_SS = ("QPushButton {{ background:{bg}; color:{fg}; border:1px solid {br};"
           " border-radius:6px; padding:6px 14px; font-size:12px; font-weight:600; }}"
           "QPushButton:hover {{ border-color:{hc}; }}")
_MSG_SS = ("QMessageBox {{ background:{bg0}; }} QLabel {{ color:{fg0}; font-size:12px; }}"
           "QPushButton {{ background:#ffffff; color:#000000; border:1px solid #000000;"
           " border-radius:6px; padding:6px 18px; font-size:12px; min-width:72px; }}"
           "QPushButton:hover {{ border-color:#b70032; }}")

_START_MARK = "✏️ 可修改区 START"
_END_MARK = "✏️ 可修改区 END"


def _ask(parent, title, text):
    mb = QMessageBox(parent)
    mb.setWindowTitle(title)
    mb.setText(text)
    mb.setStyleSheet(_MSG_SS)
    mb.addButton("确认", QMessageBox.AcceptRole)
    mb.addButton("取消", QMessageBox.RejectRole)
    return mb.exec_() == QMessageBox.Accepted


class NodeLogicDialog(QDialog):
    """节点逻辑查看/编辑器 — 可修改区金底高亮, 保存即热重载生效"""

    def __init__(self, node_name, node_type="", parent=None):
        super().__init__(parent)
        self._key = node_logic.match_node(node_name)
        self._node_name = node_name
        self._orig_src = ""
        self._editing = False
        self.setWindowTitle(f"📖 节点逻辑 — {node_name}")
        self.setMinimumSize(760, 560)
        self.setStyleSheet(f"QDialog {{ background:{_BG}; }}")
        self._build()
        self._load_source()  # 无条件: 未知节点显示「无独立逻辑」提示
        self._apply_highlight()

    # ── UI ─────────────────────────────────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        # 顶部: 节点名 + 类型 + 说明
        head = QFrame()
        head.setStyleSheet(f"QFrame {{ background:{_PANEL}; border-radius:8px; }}")
        hl = QVBoxLayout(head)
        hl.setContentsMargins(12, 10, 12, 10)
        t1 = QLabel(f"🔷 {self._node_name}")
        t1.setStyleSheet(f"color:{_TEXT}; font-size:15px; font-weight:700;")
        # 📂 代码位置行 (VSCode 打开用): 路径:行号 · 函数名
        loc_row = QHBoxLayout()
        loc_row.setSpacing(6)
        self.lbl_loc = QLabel("📂 定位中…")
        self.lbl_loc.setStyleSheet(f"color:{_GOLD}; font-size:11px; font-family:DejaVu Sans Mono;")
        self.lbl_loc.setTextInteractionFlags(Qt.TextSelectableByMouse)  # 可选中复制
        self.btn_copy_loc = QPushButton("📋 复制路径")
        self.btn_copy_loc.setStyleSheet(
            f"QPushButton {{ background:{_PANEL}; color:{_GOLD}; border:1px solid {_GOLD}66;"
            " border-radius:4px; padding:2px 10px; font-size:10px; }"
            f"QPushButton:hover {{ border-color:{_GOLD}; }}")
        self.btn_copy_loc.setCursor(Qt.PointingHandCursor)
        self.btn_copy_loc.clicked.connect(self._copy_location)
        loc_row.addWidget(self.lbl_loc, 1)
        loc_row.addWidget(self.btn_copy_loc)
        self.lbl_doc = QLabel("加载中…")
        self.lbl_doc.setWordWrap(True)
        self.lbl_doc.setStyleSheet(f"color:{_DIM}; font-size:11px;")
        self.lbl_hint = QLabel("🛠 只改金色 ✏️ 可修改区 (保存即生效) · 🔒 框架区勿动")
        self.lbl_hint.setStyleSheet(f"color:{_GOLD}; font-size:11px; font-weight:600;")
        hl.addWidget(t1)
        hl.addLayout(loc_row)
        hl.addWidget(self.lbl_doc)
        hl.addWidget(self.lbl_hint)
        root.addWidget(head)

        # 中部: 源码编辑器
        self.edit = QPlainTextEdit()
        self.edit.setStyleSheet(
            f"QPlainTextEdit {{ background:{_PANEL}; color:{_TEXT}; border:1px solid {_BRD};"
            " border-radius:6px; font-family:DejaVu Sans Mono;"
            " font-size:12px; padding:8px; }}")
        self.edit.setReadOnly(True)
        self.edit.setLineWrapMode(QPlainTextEdit.NoWrap)
        root.addWidget(self.edit, 1)

        # 底部按钮
        btns = QHBoxLayout()
        btns.setSpacing(8)
        self.btn_edit = QPushButton("✏️ 编辑")
        self.btn_save = QPushButton("💾 保存并生效")
        self.btn_restore = QPushButton("🔄 恢复默认")
        self.btn_close = QPushButton("❌ 关闭")
        for b, fg, br in ((self.btn_edit, _GOLD, _GOLD), (self.btn_save, _GREEN, _GREEN),
                          (self.btn_restore, _TEXT, _BRD), (self.btn_close, _DIM, _BRD)):
            b.setStyleSheet(_BTN_SS.format(bg=_PANEL, fg=fg, br=br, hc=fg))
        self.btn_save.setEnabled(False)
        self.btn_edit.clicked.connect(self._on_edit)
        self.btn_save.clicked.connect(self._on_save)
        self.btn_restore.clicked.connect(self._on_restore)
        self.btn_close.clicked.connect(self.reject)
        btns.addStretch(1)
        for b in (self.btn_edit, self.btn_save, self.btn_restore, self.btn_close):
            btns.addWidget(b)
        root.addLayout(btns)

    # ── 数据 ─────────────────────────────────────────────
    def _copy_location(self):
        from PyQt5.QtWidgets import QApplication as _QA
        _QA.clipboard().setText(self.lbl_loc.text())
        self.lbl_loc.setText("📋 已复制!")

    def _load_source(self):
        # 🐛 2026-08-10 老倪: 外部映射节点 (left_right) 直接显示真实实现源码 (modeling_left_right.py),
        #   不是 node_logic.py 的占位函数 — "代码对不上" 根因
        ext_src = node_logic.get_external_source(self._key) if self._key else None
        if ext_src:
            self.edit.setPlainText(ext_src)
            self.edit.setReadOnly(True)
            self.btn_edit.setEnabled(False)
            self.btn_save.setEnabled(False)
            self.btn_restore.setEnabled(False)
            self.lbl_doc.setText(node_logic.NODE_LOGIC[self._key]["doc"] if self._key in node_logic.NODE_LOGIC else "")
            self.lbl_hint.setText("🔒 真实实现 (src/lerobot/policies/left_right/) · 只读参考 — 编辑请直接打开源文件")
            self._orig_src = None
        src, doc = node_logic.get_node_source(self._key)
        # 📂 代码位置: 文件绝对路径:行号 · 函数名 (VSCode 打开用)
        path, line, modified = node_logic.get_node_location(self._key) if self._key else (None, None, False)
        if path:
            # 🐛 2026-08-10 老倪: 外部映射 (left_right) 显示真实符号名 class LeftBrainMLP,
            #   不是 node_logic.py 里的函数名 node_left_brain — 之前两者混着显示误导
            ext_sym = node_logic.get_node_external_symbol(self._key) if self._key else None
            if ext_sym:
                fn_name = ext_sym
                loc = f"📂 {path}" + (f":{line}" if line else "") + f" · {fn_name}"
            else:
                fn_name = node_logic.NODE_LOGIC[self._key]["fn"].__name__
                loc = f"📂 {path}" + (f":{line}" if line else "") + f" · def {fn_name}()"
            if modified:
                loc += " · ⚡已修改(动态生效)"
            self.lbl_loc.setText(loc)
            self.lbl_loc.setToolTip("在 VSCode 中打开: code -g " + path + (f":{line}" if line else ""))
            self.btn_copy_loc.setEnabled(True)
        else:
            self.lbl_loc.setText("📂 无独立逻辑文件")
            self.btn_copy_loc.setEnabled(False)
        if ext_src:
            # 🐛 2026-08-10: 外部真实源码已显示 (只读) — 不再走 node_logic 占位函数路径
            return
        if src is None:
            self.edit.setPlainText(f"# 节点「{self._node_name}」没有独立逻辑\n# 双击运行时走框架默认动作 (无用户可修改区)")
            self.lbl_doc.setText("🔒 该节点无独立逻辑 — 使用框架默认行为")
            self.btn_edit.setEnabled(False)
            return
        self._orig_src = src
        self.edit.setPlainText(src)
        self.lbl_doc.setText(node_logic.NODE_LOGIC[self._key]["doc"])

    def _apply_highlight(self):
        """金底高亮 ✏️ 可修改区行"""
        if not self._key:
            return
        doc = self.edit.document()
        extra = []
        inside = False
        block = doc.firstBlock()
        while block.isValid():
            txt = block.text()
            if _START_MARK in txt:
                inside = True
            if inside:
                sel = QTextEdit.ExtraSelection()
                sel.format.setBackground(QColor(_GOLD_BG))
                sel.format.setForeground(QColor(_GOLD))
                sel.format.setProperty(QTextFormat.FullWidthSelection, True)
                sel.cursor = QTextCursor(block)
                sel.cursor.clearSelection()
                extra.append(sel)
            if _END_MARK in txt:
                inside = False
            block = block.next()
        self.edit.setExtraSelections(extra)

    # ── 动作 ─────────────────────────────────────────────
    def _on_edit(self):
        self._editing = not self._editing
        self.edit.setReadOnly(not self._editing)
        self.btn_save.setEnabled(self._editing)
        self.btn_edit.setText("🔒 停止编辑" if self._editing else "✏️ 编辑")
        self.lbl_hint.setText(
            "🛠 正在编辑 — 只改金色可修改区, 保存后立即生效" if self._editing
            else "🛠 只改金色 ✏️ 可修改区 (保存即生效) · 🔒 框架区勿动")

    def _framework_changed(self):
        """检测可修改区之外是否有改动 → [(行号, 原文, 新文)]"""
        old_lines = self._orig_src.split("\n")
        new_lines = self.edit.toPlainText().split("\n")
        # old 源码中可修改区行范围 [s_lo, e_lo]
        s_lo = e_lo = None
        for i, l in enumerate(old_lines):
            if _START_MARK in l:
                s_lo = i
            if _END_MARK in l:
                e_lo = i
                break
        changed = []
        for i in range(max(len(old_lines), len(new_lines))):
            o = old_lines[i] if i < len(old_lines) else "<新增>"
            n = new_lines[i] if i < len(new_lines) else "<删除>"
            if o != n:
                # 可修改区内的行不算框架区 (用户改这里合法)
                if s_lo is not None and s_lo <= i <= e_lo:
                    continue
                changed.append((i + 1, o.strip(), n.strip()))
        return changed

    def _on_save(self):
        if not self._key:
            return
        code = self.edit.toPlainText()
        # 框架区改动警告
        fw = self._framework_changed()
        if fw:
            preview = "; ".join(f"L{r}: {o!r}→{n!r}" for r, o, n in fw[:2])
            more = f" 等{len(fw)}处" if len(fw) > 2 else ""
            if not _ask(self, "⚠️ 框架区被改动",
                        f"你修改了 🔒 框架区 (可修改区之外):\n{preview}{more}\n\n"
                        "框架区改动可能导致节点异常。确认保存?"):
                return
        ok, msg, _warn = node_logic.save_node_logic(self._key, code)
        if ok:
            # 保存成功后重新加载 (热重载后函数已替换, 重新取源码)
            self._editing = False
            self.edit.setReadOnly(True)
            self.btn_save.setEnabled(False)
            self.btn_edit.setText("✏️ 编辑")
            self._load_source()
            self._apply_highlight()
        mb = QMessageBox(self)
        mb.setWindowTitle("保存结果")
        mb.setText(msg)
        mb.setStyleSheet(_MSG_SS)
        mb.addButton("好的", QMessageBox.AcceptRole)
        mb.exec_()

    def _on_restore(self):
        if not self._key:
            return
        if not _ask(self, "🔄 恢复默认", f"恢复节点「{self._node_name}」的出厂逻辑?\n当前修改将被覆盖。"):
            return
        ok, msg = node_logic.restore_default(self._key)
        if ok:
            self._load_source()
            self._apply_highlight()
        mb = QMessageBox(self)
        mb.setWindowTitle("恢复结果")
        mb.setText(msg)
        mb.setStyleSheet(_MSG_SS)
        mb.addButton("好的", QMessageBox.AcceptRole)
        mb.exec_()


class _CodeEditor(QPlainTextEdit):
    """带行号边栏的只读编辑器 — resize 时同步行号区几何 (SourceViewDialog 用)"""

    def __init__(self, ln_area=None):
        super().__init__()
        self._ln_area = ln_area

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._ln_area:
            cr = self.contentsRect()
            self._ln_area.setGeometry(
                QRect(cr.left(), cr.top(), self._ln_area.sizeHint().width(), cr.height()))


class _LineNumberArea(QWidget):
    """行号边栏 — 跟随 QPlainTextEdit 滚动 (SourceViewDialog 用)"""

    def __init__(self, editor):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self):
        digits = len(str(max(1, self._editor.blockCount())))
        w = 10 + self._editor.fontMetrics().horizontalAdvance("9") * digits
        return QSize(w, 0)

    def paintEvent(self, ev):
        from PyQt5.QtGui import QPainter
        p = QPainter(self)
        p.fillRect(ev.rect(), QColor(_PANEL))
        block = self._editor.firstVisibleBlock()
        num = block.blockNumber()
        top = self._editor.blockBoundingGeometry(block).translated(
            self._editor.contentOffset()).top()
        while block.isValid() and top <= ev.rect().bottom():
            if block.isVisible():
                bottom = top + self._editor.blockBoundingRect(block).height()
                p.setPen(QColor(_DIM))
                p.drawText(0, int(top), self.width() - 6, int(bottom - top),
                           Qt.AlignRight, str(num + 1))
            block = block.next()
            top = self._editor.blockBoundingGeometry(block).translated(
                self._editor.contentOffset()).top()
            num += 1


class SourceViewDialog(QDialog):
    """📂 打开源代码 (容器环境 2026-08-18 老倪):
    容器无 /mnt/c + 无 explorer.exe (WSL interop 断) → explorer 链路打不开源码,
    改弹窗查看: 绝对路径 + 行号 + 📋复制路径按钮 + 只读源码 (可选中复制)。"""

    def __init__(self, abs_path, rel_src="", parent=None):
        super().__init__(parent)
        self._abs = abs_path
        self.setWindowTitle(f"📂 {os.path.basename(abs_path)} — {rel_src}")
        self.setMinimumSize(820, 600)
        self.setStyleSheet(f"QDialog {{ background:{_BG}; }}")
        self._build()
        self._load()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        head = QFrame()
        head.setStyleSheet(f"QFrame {{ background:{_PANEL}; border-radius:8px; }}")
        hl = QVBoxLayout(head)
        hl.setContentsMargins(12, 10, 12, 10)
        t1 = QLabel(f"📂 {os.path.basename(self._abs)}")
        t1.setStyleSheet(f"color:{_TEXT}; font-size:14px; font-weight:700;")
        loc_row = QHBoxLayout()
        loc_row.setSpacing(6)
        self.lbl_loc = QLabel(self._abs)
        self.lbl_loc.setStyleSheet(f"color:{_GOLD}; font-size:11px; font-family:DejaVu Sans Mono;")
        self.lbl_loc.setTextInteractionFlags(Qt.TextSelectableByMouse)  # 可选中复制
        self.btn_copy = QPushButton("📋 复制路径")
        self.btn_copy.setStyleSheet(
            f"QPushButton {{ background:{_PANEL}; color:{_GOLD}; border:1px solid {_GOLD}66;"
            " border-radius:4px; padding:2px 10px; font-size:10px; }"
            f"QPushButton:hover {{ border-color:{_GOLD}; }}")
        self.btn_copy.setCursor(Qt.PointingHandCursor)
        self.btn_copy.clicked.connect(self._copy_path)
        loc_row.addWidget(self.lbl_loc, 1)
        loc_row.addWidget(self.btn_copy)
        hl.addWidget(t1)
        hl.addLayout(loc_row)
        root.addWidget(head)

        # 中部: 只读源码 + 行号 (编程式样式 — PyQt 子类 metaObject 名非 QSS 已知类,
        # setStyleSheet 会报 "Could not parse stylesheet", 故用 QFont+QPalette)
        self.edit = _CodeEditor()
        from PyQt5.QtGui import QFont as _QF, QPalette as _QP
        _f = _QF("DejaVu Sans Mono", 12)
        _f.setStyleHint(_QF.Monospace)
        self.edit.setFont(_f)
        _pal = self.edit.palette()
        _pal.setColor(_QP.Base, QColor(_BG))
        _pal.setColor(_QP.Text, QColor(_TEXT))
        _pal.setColor(_QP.Highlight, QColor(_GOLD))
        _pal.setColor(_QP.HighlightedText, QColor("#000000"))
        self.edit.setPalette(_pal)
        self.edit.setFrameShape(QFrame.StyledPanel)
        self.edit.setStyleSheet("")  # 清空继承样式, 避免警告
        self.edit.setReadOnly(True)
        self.edit.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.edit.setTabStopDistance(4 * 8)  # 等宽字体 4 空格
        self._ln = _LineNumberArea(self.edit)
        self.edit._ln_area = self._ln  # resize 时同步行号区几何
        self.edit.blockCountChanged.connect(lambda _n: self._ln.update())
        self.edit.updateRequest.connect(self._update_ln)
        self.edit.cursorPositionChanged.connect(lambda: self._ln.update())
        root.addWidget(self.edit, 1)

        btn_close = QPushButton("❌ 关闭")
        btn_close.setStyleSheet(_BTN_SS.format(bg=_PANEL, fg=_DIM, br=_BRD, hc=_TEXT))
        btn_close.clicked.connect(self.reject)
        btm = QHBoxLayout()
        btm.addStretch(1)
        btm.addWidget(btn_close)
        root.addLayout(btm)

    def _update_ln(self, rect, dy):
        if dy:
            self._ln.scroll(0, dy)
        else:
            self._ln.update(0, rect.y(), self._ln.width(), rect.height())
        if rect.contains(self.edit.viewport().rect()):
            self._ln.update(0, 0, self._ln.width(), self.edit.height())

    def _copy_path(self):
        from PyQt5.QtWidgets import QApplication as _QA
        _QA.clipboard().setText(self._abs)
        self.btn_copy.setText("📋 已复制!")

    def _load(self):
        try:
            with open(self._abs, "r", encoding="utf-8", errors="replace") as f:
                self.edit.setPlainText(f.read())
        except Exception as e:
            self.edit.setPlainText(f"⚠️ 读取失败: {e}")


# ── 独立调试入口 ─────────────────────────────────────
def main():
    from PyQt5.QtWidgets import QApplication
    app = QApplication(sys.argv)
    dlg = NodeLogicDialog("🚀 全新训练")
    dlg.exec_()


if __name__ == "__main__":
    main()
