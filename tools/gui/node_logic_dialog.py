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

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont, QTextCursor, QTextFormat
from PyQt5.QtWidgets import (QDialog, QHBoxLayout, QLabel, QMessageBox,
                             QPlainTextEdit, QPushButton, QTextEdit,
                             QVBoxLayout, QFrame)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import node_logic

_BG = "#0d1117"
_PANEL = "#161b22"
_TEXT = "#e6edf3"
_DIM = "#8b949e"
_GOLD = "#ffd700"
_GOLD_BG = "#3d3410"      # ✏️ 可修改区底纹
_GOLD_LINE = "#d4a800"    # ✏️ 分隔线
_GREEN = "#3fb950"
_BTN_SS = ("QPushButton {{ background:{bg}; color:{fg}; border:1px solid {br};"
           " border-radius:6px; padding:6px 14px; font-size:12px; font-weight:600; }}"
           "QPushButton:hover {{ border-color:{hc}; }}")
_MSG_SS = ("QMessageBox {{ background:#0d1117; }} QLabel {{ color:#e6edf3; font-size:12px; }}"
           "QPushButton {{ background:#21262d; color:#e6edf3; border:1px solid #30363d;"
           " border-radius:6px; padding:6px 18px; font-size:12px; min-width:72px; }}"
           "QPushButton:hover {{ border-color:#00d4aa; }}")

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
        self.lbl_doc = QLabel("加载中…")
        self.lbl_doc.setWordWrap(True)
        self.lbl_doc.setStyleSheet(f"color:{_DIM}; font-size:11px;")
        self.lbl_hint = QLabel("🛠 只改金色 ✏️ 可修改区 (保存即生效) · 🔒 框架区勿动")
        self.lbl_hint.setStyleSheet(f"color:{_GOLD}; font-size:11px; font-weight:600;")
        hl.addWidget(t1)
        hl.addWidget(self.lbl_doc)
        hl.addWidget(self.lbl_hint)
        root.addWidget(head)

        # 中部: 源码编辑器
        self.edit = QPlainTextEdit()
        self.edit.setStyleSheet(
            f"QPlainTextEdit {{ background:#010409; color:{_TEXT}; border:1px solid #30363d;"
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
                          (self.btn_restore, _TEXT, "#30363d"), (self.btn_close, _DIM, "#30363d")):
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
    def _load_source(self):
        src, doc = node_logic.get_node_source(self._key)
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


# ── 独立调试入口 ─────────────────────────────────────
def main():
    from PyQt5.QtWidgets import QApplication
    app = QApplication(sys.argv)
    dlg = NodeLogicDialog("🚀 全新训练")
    dlg.exec_()


if __name__ == "__main__":
    main()
