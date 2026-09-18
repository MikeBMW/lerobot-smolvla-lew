#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""l2_autolearn_panel.py — 「🎯 真机数据 L2 训练」状态面板 (老倪 2026-09-18)

画布 🔀 模式开关选「真机数据 L2 训练」后点 ▶ 运行 → 本面板回显闭环状态:
  环1 采集 (新鲜真机帧 + 真值侧车 + 自动标注) · 环2 训练→同口径对照→有提升才上在役 · 环3 人工标注
面板只读产物文件 (state.json / verdicts.jsonl / heartbeat.json / autolearn.log / 指针) 拿**真值**,
不编造: 标定未就绪 / 无新鲜帧 / 无提升 都如实显示。
"""
from __future__ import annotations

import json
import os
import subprocess
import time

from PyQt5 import QtCore, QtGui, QtWidgets

WORK = os.environ.get("ZMAX_L2_WORK", "/home/ubuntu/zmax_data/l2_autolearn")
REPO = os.environ.get("ZMAX_REPO_ROOT") or "/home/ubuntu/lerobot-smolvla-lew"
PY = os.path.join(REPO, "gui-venv311", "bin", "python")
TOOL = os.path.join(REPO, "tools", "ss_l2_autolearn.py")
UNIT = "zmax-l2-autolearn"


def _j(p, d=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                          # noqa: BLE001
        return d if d is not None else {}


def _tail(p, n=14):
    try:
        with open(p, encoding="utf-8", errors="ignore") as f:
            return "".join(f.readlines()[-n:])
    except Exception:                                                          # noqa: BLE001
        return ""


class L2AutoLearnPanel(QtWidgets.QDialog):
    """真机数据 L2 边干边学面板 (非模态, 3s 自刷新)"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🎯 真机数据 L2 训练 — 边干边学闭环 (sim→real)")
        self.resize(980, 700)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)

        v = QtWidgets.QVBoxLayout(self)
        self.lb_head = QtWidgets.QLabel("…")
        self.lb_head.setWordWrap(True)
        self.lb_head.setStyleSheet("font-size:13px;")
        v.addWidget(self.lb_head)

        row = QtWidgets.QHBoxLayout()
        self.b_start = QtWidgets.QPushButton("▶ 开始边干边学 (采集+自动训练)")
        self.b_start.setToolTip("启动常驻单元 (systemd 独立单元, 关/重启控制台不会中断): "
                                "边插拔边采数据 → 满触发条件就跑一轮训练 → 有提升才上在役")
        self.b_once = QtWidgets.QPushButton("🔁 立即跑一轮")
        self.b_once.setToolTip("不等触发条件, 现在就跑一轮完整闭环 (采集→建集→训练→同口径对照→判定)")
        self.b_stop = QtWidgets.QPushButton("⏹ 停止")
        self.b_ref = QtWidgets.QPushButton("🔄 刷新")
        for b in (self.b_start, self.b_once, self.b_stop, self.b_ref):
            row.addWidget(b)
        v.addLayout(row)

        row2 = QtWidgets.QHBoxLayout()
        self.cb_promote = QtWidgets.QCheckBox("有提升→自动上在役 (关掉=只演练不上线)")
        self.cb_promote.setChecked(True)
        self.cb_promote.setToolTip("交付门槛: 与在役权重同口径对照 (训练后新采真机帧), 检出率↑ 或 conf↑ 才算提升")
        self.sp_epochs = QtWidgets.QSpinBox()
        self.sp_epochs.setRange(5, 1000)
        self.sp_epochs.setValue(60)
        self.sp_epochs.setPrefix("训练轮数 ")
        self.sp_trig = QtWidgets.QSpinBox()
        self.sp_trig.setRange(2, 500)
        self.sp_trig.setValue(12)
        self.sp_trig.setPrefix("新样本触发 ")
        row2.addWidget(self.cb_promote)
        row2.addWidget(self.sp_epochs)
        row2.addWidget(self.sp_trig)
        row2.addStretch(1)
        v.addLayout(row2)

        self.te = QtWidgets.QPlainTextEdit()
        self.te.setReadOnly(True)
        self.te.setStyleSheet("font-family:Consolas,monospace;font-size:12px;")
        v.addWidget(self.te, 3)

        row3 = QtWidgets.QHBoxLayout()
        self.lb_path = QtWidgets.QLabel(f"证据/状态目录: {WORK}")
        self.lb_path.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        b_copy = QtWidgets.QPushButton("📋 复制路径")
        b_ts = QtWidgets.QPushButton("🗒 打开日志")
        row3.addWidget(self.lb_path, 1)
        row3.addWidget(b_ts)
        row3.addWidget(b_copy)
        v.addLayout(row3)

        b_copy.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(WORK))
        b_ts.clicked.connect(self._open_log)
        self.b_start.clicked.connect(self.start_daemon)
        self.b_once.clicked.connect(self.run_cycle)
        self.b_stop.clicked.connect(self.stop_all)
        self.b_ref.clicked.connect(self.refresh)

        self.tm = QtCore.QTimer(self)
        self.tm.timeout.connect(self.refresh)
        self.tm.start(3000)
        self.refresh()

    # ── 启动/停止 (systemd 独立单元: 不挂在控制台 cgroup 下) ──
    def _run_unit(self, unit, args):
        cmd = (f"systemd-run --user --collect --unit {unit} --working-directory {REPO} "
               f"bash -lc 'exec {PY} {TOOL} {args} > {WORK}/{unit}.log 2>&1'")
        rc = os.system(cmd)
        return rc == 0

    def start_daemon(self):
        ok = self._run_unit(UNIT, f"--daemon --trigger-n {self.sp_trig.value()} "
                                  f"--epochs {self.sp_epochs.value()} "
                                  + ("" if self.cb_promote.isChecked() else "--no-promote "))
        self.te.appendPlainText(f"[{time.strftime('%H:%M:%S')}] ▶ 启动边干边学常驻单元 {UNIT} "
                                f"({'成功' if ok else '失败 — 检查 systemd --user'})")
        self.refresh()

    def run_cycle(self):
        u = f"zmax-l2-cycle-{time.strftime('%m%d-%H%M%S')}"
        ok = self._run_unit(u, f"--cycle --epochs {self.sp_epochs.value()} "
                               + ("" if self.cb_promote.isChecked() else "--no-promote "))
        self.te.appendPlainText(f"[{time.strftime('%H:%M:%S')}] 🔁 启动单轮闭环 {u} "
                                f"({'成功' if ok else '失败'}) · 进度看 {WORK}/{u}.log")
        self.refresh()

    def stop_all(self):
        subprocess.run([PY, TOOL, "--stop"], capture_output=True, text=True, cwd=REPO)
        os.system(f"systemctl --user stop {UNIT} 2>/dev/null")
        self.te.appendPlainText(f"[{time.strftime('%H:%M:%S')}] ⏹ 已发停止 (采集器 + {UNIT})")
        self.refresh()

    def _open_log(self):
        p = os.path.join(WORK, "autolearn.log")
        os.system(f"xdg-open {p} >/dev/null 2>&1 &") if os.path.isfile(p) else None
        self.te.appendPlainText(f"[{time.strftime('%H:%M:%S')}] 🗒 日志路径 (可复制): {p}")

    # ── 刷新 (只读产物文件) ──
    def refresh(self):
        st = _j(os.path.join(WORK, "state.json"))
        hb = _j(os.path.join(WORK, "heartbeat.json"))
        ptr = os.path.join(REPO, "models", "yolo_peg_live.pt")
        tgt = os.path.realpath(ptr) if os.path.exists(ptr) else None
        stats = _j(os.path.join(REPO, "data", "yolo_annot", "dataset", "stats.json"))
        meta = _j(os.path.join(REPO, "data", "yolo_annot", "meta.json"))
        sess = meta.get("sessions") or []
        n_h = len([s for s in sess if not str(s.get("annotator", "")).startswith("auto")])
        n_a = len([s for s in sess if str(s.get("annotator", "")).startswith("auto")])
        n_p = sum(int(s.get("n_images", 0)) for s in sess
                  if str(s.get("annotator", "")) == "auto:pending")
        calib = _j(os.path.join(REPO, "models", "real_cam_calib.json"))
        cam = os.path.join(os.environ.get("ZMAX_SS_REMOTE_DIR", "/home/ubuntu/zmax_ss_remote"), "cam_rs.png")
        age = (time.time() - os.stat(cam).st_mtime) if os.path.isfile(cam) else None
        pid_alive = False
        try:
            pid = int(open(os.path.join(WORK, "daemon.pid"), encoding="utf-8").read().strip())
            os.kill(pid, 0)
            pid_alive = True
        except Exception:                                                      # noqa: BLE001
            pid = None
        vers = []
        try:
            with open(os.path.join(WORK, "verdicts.jsonl"), encoding="utf-8") as f:
                vers = [json.loads(x) for x in f if x.strip()]
        except Exception:                                                      # noqa: BLE001
            pass

        head = [
            f"<b>在役权重</b>: {(os.path.relpath(tgt, REPO) if tgt else '—')}",
            f"<b>数据集</b>: train {stats.get('n_train')} / val {stats.get('n_val')} · 样本 {stats.get('n_samples')} "
            f"(人工会话 {n_h} · 自动会话 {n_a}) · auto混入val={stats.get('auto_in_val', '—')}"
            f"<br><b>待人工标注池</b>: {n_p} 张 (未标注 → 不进训练集, 在控制台「输入图像」窗口补标后进 train/val)",
            f"<b>相机新鲜度</b>: " + (f"{age:.1f}s" + (" ✅" if 0 <= age <= 3 else " ⚠️ 无新鲜帧 (先起真机旁路)")
                                      if age is not None else "—"),
            "<b>几何真值标注</b>: " + ("✅ 标定就绪" if calib.get("ready") else
                                  "⚠️ 未就绪 → 只走伪标注 (在役权重 conf≥门槛); " + str(calib.get("reason", ""))[:70]),
            f"<b>采集器</b>: " + (f"运行中 pid={pid} · 心跳 {time.time() - float(hb.get('t') or 0):.0f}s 前"
                                 if pid_alive else "未运行")
            + f" · 累计采样 {st.get('n_collected', 0)} 张",
        ]
        if vers:
            last = vers[-1]
            vd = last.get("verdict") or {}
            head.append("<b>最近一轮</b>: " + f"{last.get('ts')} {last.get('name')} · "
                        + ("✅ 有提升" if vd.get("improved") else "➖ 无提升")
                        + f" ({str(vd.get('reason'))[:90]}) · 上在役={((last.get('promote') or {}).get('done'))}")
        self.lb_head.setText("<br>".join(head))
        self.te.setPlainText(_tail(os.path.join(WORK, "autolearn.log"), 20)
                             or "(暂无日志 — 点「▶ 开始边干边学」或「🔁 立即跑一轮」)")
