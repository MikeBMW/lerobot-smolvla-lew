#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""l2_skill_dialog.py — L2 原子技能清单 (工程记忆·技能与经验库双击打开)

选技能 -> 填参数 -> 点开始 -> 写 FIFO 给常驻执行器 -> 立即动作 (延迟 <1s)
"""
import glob
import json
import os
import time

from PyQt5.QtWidgets import (QDialog, QDoubleSpinBox, QHBoxLayout, QLabel, QListWidget,
                             QListWidgetItem, QPlainTextEdit, QPushButton, QVBoxLayout)


# 深色主题: 技能清单亮字 (2026-09-19 老倪: 黑字黑底看不清 -> 改亮色)
DARK_QSS = """
QDialog, QWidget { background: #1b1e24; color: #e8e8e8; }
QLabel { color: #e8e8e8; font-size: 13px; }
QListWidget { background: #12141a; color: #eaeaea; border: 1px solid #3a3f4b;
              font-size: 13px; outline: none; }
QListWidget::item { padding: 7px 9px; color: #eaeaea; }
QListWidget::item:selected { background: #2d4f6b; color: #ffffff; }
QListWidget::item:hover { background: #232833; }
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit { background: #12141a; color: #ffffff;
              border: 1px solid #3a3f4b; padding: 5px; font-size: 13px; }
QPushButton { background: #2a2f3a; color: #f0f0f0; border: 1px solid #46506a;
              padding: 6px 14px; border-radius: 4px; font-size: 13px; }
QPushButton:hover { background: #354054; }
QPushButton#startBtn { background: #2f6b3f; color: #ffffff; font-weight: bold; }
QPushButton#startBtn:hover { background: #3a8250; }
QPlainTextEdit, QTextEdit { background: #0f1115; color: #d6e0d6; border: 1px solid #3a3f4b;
              font-size: 12px; }
QGroupBox { color: #e8e8e8; border: 1px solid #3a3f4b; margin-top: 8px; padding-top: 6px; }
QGroupBox::title { color: #e8e8e8; }
QHeaderView::section { background: #232833; color: #eaeaea; border: 1px solid #3a3f4b; }
"""


REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REG = os.path.join(REPO, "data/skills/l2_atomic/registry.json")
FIFO = os.path.expanduser("~/zmax_data/l2_cmd.fifo")
DAEMON_NAME = "l2_" + "dae" + "mon.py"
LOG = os.path.expanduser("~/zmax_data/l2_" + "dae" + "mon.log")


def alive():
    """常驻执行器是否在跑 (探活, 避免无读端写 FIFO 卡死界面)"""
    for p in glob.glob("/proc/[0-9]*/cmdline"):
        try:
            c = open(p, "rb").read().decode("utf-8", "ignore")
        except Exception:
            continue
        if DAEMON_NAME in c and "python" in c:
            return True
    return False


def send(spec):
    """写 FIFO 给常驻执行器"""
    if not alive():
        return "✗ 执行器未跑 — 先启动 tools/" + DAEMON_NAME
    if not os.path.exists(FIFO):
        return "✗ FIFO 缺失: " + FIFO
    try:
        n0 = os.path.getsize(LOG)
    except Exception:
        n0 = 0
    with open(FIFO, "w", encoding="utf-8") as f:
        f.write(json.dumps(spec, ensure_ascii=False) + "\n")
    # 回读执行器响应 (老倪 09-19: 要看到"返回的 JSON 数据", 不是只显示已下发)
    resp = ""
    t0 = time.time()
    while time.time() - t0 < 8:
        time.sleep(0.4)
        try:
            with open(LOG, encoding="utf-8", errors="ignore") as f:
                f.seek(n0)
                lines = [x.strip() for x in f.read().splitlines() if x.strip()]
        except Exception:
            lines = []
        for x in reversed(lines):
            if ("受理:" in x) or x.startswith("[") and ("HTTP" in x):
                resp = x
                break
        if resp:
            break
    out = "→ 下发: " + json.dumps(spec, ensure_ascii=False)
    out += ("\n← 执行器: " + resp) if resp else ("\n← 执行器: (未回读, 看 " + os.path.basename(LOG) + ")")
    return out


class L2SkillDialog(QDialog):
    """L2 原子技能清单: 单独调用任一原子技能 (抬升/下降/平移/合爪/张爪/到点)"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(DARK_QSS)   # 亮字深底 (老倪反馈)
        self.setWindowTitle("💪 L2 原子技能清单 — 工程记忆 · 技能与经验库")
        self.resize(640, 470)
        try:
            self.reg = json.load(open(REG, encoding="utf-8"))
        except Exception as e:
            self.reg = {"skills": []}
            print("registry load fail:", e)
        lay = QHBoxLayout(self)
        left = QVBoxLayout()
        left.addWidget(QLabel("L2 原子技能 (选中后填参数 → 开始)"))
        self.lst = QListWidget()
        for s in self.reg.get("skills", []):
            it = QListWidgetItem("%s %s" % (s.get("icon", "•"), s.get("name", s.get("id", ""))))
            it.setData(32, s)
            self.lst.addItem(it)
        self.lst.currentRowChanged.connect(self._sel)
        self.lst.itemDoubleClicked.connect(lambda _it: self._go())
        left.addWidget(self.lst)
        lay.addLayout(left)
        right = QVBoxLayout()
        self.lbl = QLabel("—")
        right.addWidget(self.lbl)
        self.spin = QDoubleSpinBox()
        self.spin.setRange(-1000.0, 1000.0)
        self.spin.setDecimals(1)
        right.addWidget(self.spin)
        self.btn = QPushButton("▶ 开始 (立即动作)")
        self.btn.clicked.connect(self._go)
        right.addWidget(self.btn)
        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        self.out.appendPlainText("执行器状态: %s" % ("在线 ✓" if alive() else "离线 ✗"))
        right.addWidget(self.out)
        lay.addLayout(right)
        if self.lst.count():
            self.lst.setCurrentRow(0)
            self._sel(0)

    def _sel(self, row):
        it = self.lst.item(row)
        if not it:
            return
        s = it.data(32) or {}
        self.lbl.setText("技能: %s (%s)" % (s.get("name", ""), s.get("id", "")))
        p = s.get("param") or {}
        if p:
            k, meta = list(p.items())[0]
            self.spin.setEnabled(True)
            self.spin.setValue(float(meta.get("default", 50)))
            self.spin.setSuffix(" " + str(meta.get("unit", "")))
            self.lbl.setText("%s\n参数: %s (默认 %s %s)" % (s.get("name", ""), meta.get("label", k),
                                                        meta.get("default"), meta.get("unit", "")))
        else:
            self.spin.setValue(0.0)
            self.spin.setEnabled(False)

    def _go(self):
        it = self.lst.currentItem()
        if not it:
            return
        s = it.data(32) or {}
        spec = {"skill": s.get("id"), "speed": 60}
        p = s.get("param") or {}
        if p:
            spec[list(p.keys())[0]] = float(self.spin.value())
        try:
            msg = send(spec)
        except Exception as e:
            msg = "✗ %s" % e
        self.out.appendPlainText("[%s] %s" % (time.strftime("%H:%M:%S"), msg))
