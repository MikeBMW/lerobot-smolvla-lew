#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""l2_skill_dialog.py — L2 原子技能清单 (工程记忆·技能与经验库双击打开)

选技能 -> 填参数 -> 点开始 -> 写 FIFO 给常驻执行器 -> 立即动作
"""
import json
import os

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import (QDialog, QDoubleSpinBox, QHBoxLayout, QLabel, QListWidget,
                             QListWidgetItem, QPlainTextEdit, QPushButton, QVBoxLayout)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REG = os.path.join(REPO, "data/skills/l2_atomic/registry.json")
FIFO = os.path.expanduser("~/zmax_data/l2_cmd.fifo")


def send(spec):
    with open(FIFO, "w", encoding="utf-8") as f:
        f.write(json.dumps(spec, ensure_ascii=False) + "\n")
    return "已下发: " + json.dumps(spec, ensure_ascii=False)


class L2SkillDialog(QDialog):
    """L2 原子技能清单: 单独调用任一原子技能 (抬升/下降/平移/合爪/张爪/到点)"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("💪 L2 原子技能清单 — 技能与经验库")
        self.resize(620, 460)
        self.reg = json.load(open(REG, encoding="utf-8"))
        lay = QHBoxLayout(self)
        left = QVBoxLayout()
        left.addWidget(QLabel("L2 原子技能 (双击或选中后点开始)"))
        self.lst = QListWidget()
        for s in self.reg["skills"]:
            it = QListWidgetItem("%s %s" % (s.get("icon", "•"), s["name"]))
            it.setData(32, s)
            self.lst.addItem(it)
        self.lst.currentRowChanged.connect(self._sel)
        left.addWidget(self.lst)
        lay.addLayout(left)
        right = QVBoxLayout()
        self.lbl = QLabel("—")
        right.addWidget(self.lbl)
        self.spin = QDoubleSpinBox()
        self.spin.setRange(-1000, 1000)
        self.spin.setDecimals(1)
        right.addWidget(self.spin)
        self.btn = QPushButton("▶ 开始")
        self.btn.clicked.connect(self._go)
        right.addWidget(self.btn)
        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        right.addWidget(self.out)
        lay.addLayout(right)
        self.lst.setCurrentRow(0)
        self._sel(0)

    def _sel(self, row):
        it = self.lst.item(row)
        if not it:
            return
        s = it.data(32)
        self.lbl.setText("技能: %s\n%s" % (s["name"], s.get("ros", "")))
        p = s.get("param") or {}
        if p:
            k, meta = list(p.items())[0]
            self.spin.setValue(float(meta.get("default", 50)))
            self.spin.setSuffix(" " + str(meta.get("unit", "")))
            self.spin.setEnabled(True)
        else:
            self.spin.setValue(0)
            self.spin.setEnabled(False)

    def _go(self):
        it = self.lst.currentItem()
        if not it:
            return
        s = it.data(32)
        spec = {"skill": s["id"], "speed": 60}
        p = s.get("param") or {}
        if p:
            k = list(p.keys())[0]
            spec[k] = float(self.spin.value())
        try:
            msg = send(spec)
            self.out.appendPlainText("[%s] %s" % (self._now(), msg))
        except Exception as e:
            self.out.appendPlainText("[%s] ✗ %s" % (self._now(), e))

    @staticmethod
    def _now():
        import time
        return time.strftime("%H:%M:%S")
