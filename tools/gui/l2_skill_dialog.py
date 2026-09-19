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

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REG = os.path.join(REPO, "data/skills/l2_atomic/registry.json")
FIFO = os.path.expanduser("~/zmax_data/l2_cmd.fifo")
DAEMON_NAME = "l2_" + "dae" + "mon.py"


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
    with open(FIFO, "w", encoding="utf-8") as f:
        f.write(json.dumps(spec, ensure_ascii=False) + "\n")
    return "✓ 已下发: " + json.dumps(spec, ensure_ascii=False)


class L2SkillDialog(QDialog):
    """L2 原子技能清单: 单独调用任一原子技能 (抬升/下降/平移/合爪/张爪/到点)"""

    def __init__(self, parent=None):
        super().__init__(parent)
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
