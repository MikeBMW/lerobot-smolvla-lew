#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""vlm_panel.py — 🧿 DeepSeek-V4-Flash 视觉语言判读结果窗口 (人机在环)

老倪 2026-09-19: 「做一个 deepseek-v4-flash 节点 … 让用户明确感觉到, 这个工程是在人机在环的使用
deepseek 视觉语言大模型的方案。这个节点, 右键可以打开视觉语言大模型的输出结果, 你来设计输出给用户
的结果显示 UI, 要实现清晰的理解场景, 提升大模型层的高级理解能力。」

UI 设计 (单色为主, 不自造数据; 每条数字都能指到来源):
  顶部 状态条: 路径/provider · 模型 · 端点 · 最近一次耗时 · 累计调用次数 · 日志文件路径 (可点开)
  左   实时画面: 最新真机/仿真帧 + 帧龄 (负帧龄=时钟异常会明确标出)
  右   场景理解: 字段表 (中文含义 → 值), 画面质量逐项 ✓/✗, 并列出"标定建议"
  底   人机在环提示: 模型只给"判读与建议", 动作/指令须由操作员确认后才执行 (红线)
  下   历史: 最近 20 次判读 (时间/模式/耗时/来源/摘要) —— 实时滚动, 5s 自动刷新
按钮: [立即判读 describe] [标定向导 guide] [采集质检 quality] [刷新] [打开记录目录]
数据来源: ~/zmax_data/vlm_calls.jsonl (scene_vlm 每次调用落盘) + 最新帧文件
"""
from __future__ import annotations

import json
import os
import time

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (QDialog, QHBoxLayout, QHeaderView, QLabel, QPushButton,
                             QSplitter, QTableWidget, QTableWidgetItem, QTextEdit,
                             QVBoxLayout, QWidget)

# 🎨 深色配色 (与工程既有面板统一: tools/gui/calibration_dialog.py 的 _DARK)
#    老倪 2026-09-19: 「右面显示的字体和背景都是黑色, 看不清啊。字体改成白色。」
_DARK = ("QDialog { background:#0d1117; color:#e6edf3; } "
         "QLabel { color:#e6edf3; background:transparent; } "
         "QTableWidget { background:#161b22; color:#e6edf3; border:1px solid #30363d; "
         "gridline-color:#30363d; alternate-background-color:#0d1117; } "
         "QTableWidget::item { color:#e6edf3; padding:3px; } "
         "QTableWidget::item:selected { background:#1f6feb; color:#ffffff; } "
         "QHeaderView::section { background:#21262d; color:#e6edf3; border:none; padding:5px; } "
         "QTextEdit { background:#161b22; color:#e6edf3; border:1px solid #30363d; } "
         "QPushButton { background:#21262d; color:#e6edf3; border:1px solid #30363d; "
         "border-radius:5px; padding:7px 14px; font-size:13px; } "
         "QPushButton:hover { background:#1f6feb; color:#ffffff; } "
         "QScrollBar { background:#0d1117; } "
         "QToolTip { background:#161b22; color:#e6edf3; border:1px solid #30363d; }")


CALLS = os.path.expanduser("~/zmax_data/vlm_calls.jsonl")
FRAMES = [os.path.expanduser("~/zmax_ss_remote/cam_rs.png"),
          os.path.expanduser("~/zmax_ss_remote/cam_fp.png")]

# 字段中文含义 (面板自解释: 标签 + 数值 + 物理含义)
FIELD_HELP = {
    "目标可见": "画面里是否看到目标工件",
    "目标是什么": "模型认出的物体 (对照 YOLO 类别 peg=光模块)",
    "目标位置": "画面九宫位置 (与检测框中心对照)",
    "在夹爪上吗": "是否已在夹爪内 (夹持态才可做手眼标定)",
    "目标是否在夹爪里": "是否已在夹爪内 (标定前置条件)",
    "朝向": "目标姿态 (竖直/倾斜; 拉环方向)",
    "画面质量": "模糊/过暗过曝/太远太小/遮挡",
    "光照": "现场光照条件",
    "背景线索": "工装/托盘/标定板等可辨识参照",
    "标定建议": "模型给出的下一步标定动作",
    "这帧可用": "该帧能否进入标定数据集",
    "不能用原因": "不可用的具体原因",
    "看见的目标个数": "画面里目标数量",
    "下一步动作": "给操作员的具体动作",
    "为什么": "给出该建议的理由",
    "验收判据": "做完后画面应满足的可检验条件",
    "合格": "采集帧质检是否通过",
    "问题": "质检发现的问题列表",
    "目标清晰度": "0~1 清晰度",
    "周边是否有干扰物": "是否有干扰物体",
}


def _read_calls(limit=40):
    if not os.path.exists(CALLS):
        return []
    out = []
    try:
        with open(CALLS, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except Exception:                                          # noqa: BLE001
                        pass
    except Exception:                                                          # noqa: BLE001
        return []
    return out[-limit:][::-1]


def _fmt_val(v):
    if isinstance(v, dict):
        bad = [k for k, x in v.items() if x not in (False, None, "false", "False")]
        return ("✓ 无问题" if not bad else "✗ " + " / ".join(bad))
    if isinstance(v, list):
        return "无" if not v else " / ".join(str(x) for x in v)
    if isinstance(v, bool):
        return "是" if v else "否"
    return str(v)


class VlmPanel(QDialog):
    def __init__(self, parent=None, module=None, node=None):
        super().__init__(parent)
        self.module = module
        self.node = node or {}
        self.setWindowTitle("🧿 DeepSeek-V4-Flash 视觉语言判读 (人机在环)")
        # 🐛 2026-09-19 老倪: 「最大化的按钮不好使」+「窗口还无法拖动」
        #   QDialog 默认 flags 不带最大化按钮; 且原来以父窗口为 parent → 被当瞬时窗口, 标题栏拖不动。
        #   → 显式给 最小化/最大化/关闭/系统菜单 + 顶层窗口 (parent 只用于首次定位) + 非模态, 可自由拖动/最大化
        self.setWindowFlags(Qt.Window | Qt.WindowMinMaxButtonsHint
                            | Qt.WindowCloseButtonHint | Qt.WindowSystemMenuHint)
        self.setWindowModality(Qt.NonModal)
        self.setMinimumSize(880, 560)
        self.setStyleSheet(_DARK)      # 🎨 白字深底 (原来继承系统默认 → 黑字黑底看不清)
        self._restore_geom()
        self._busy = False
        v = QVBoxLayout(self)

        # ── 顶部状态条 ──
        self.lbl_status = QLabel("状态: 读取中…")
        self.lbl_status.setWordWrap(True)
        v.addWidget(self.lbl_status)
        row = QHBoxLayout()
        for text, fn in (("立即判读 (场景理解)", lambda: self._ask("describe")),
                         ("标定向导 (下一步动作)", lambda: self._ask("guide")),
                         ("采集质检 (能否进数据集)", lambda: self._ask("quality")),
                         ("刷新", self.refresh),
                         ("打开记录目录", self._open_dir)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        v.addLayout(row)

        # ── 中部: 左画面 / 右判读 (QSplitter: 中间分隔条可拖动, 自己分配显示区域) ──
        split = QSplitter(Qt.Horizontal)
        left = QVBoxLayout()
        self.lbl_img = QLabel("(无最新帧)")
        self.lbl_img.setMinimumSize(640, 480)
        self.lbl_img.setAlignment(Qt.AlignCenter)
        self.lbl_img.setStyleSheet("border: 1px solid #30363d; background:#161b22; color:#8b949e;")
        left.addWidget(self.lbl_img)
        self.lbl_img_info = QLabel("")
        left.addWidget(self.lbl_img_info)
        # (left/right 交给下面的 QSplitter 承载; 别先 addLayout 到中间层, 否则 setLayout 冲突告警)
        right = QVBoxLayout()
        self.tbl = QTableWidget(0, 3)
        self.tbl.setHorizontalHeaderLabels(["字段", "含义 (物理/工程)", "模型判读"])
        # 🐛 2026-09-19 老倪: 「含义里面有很多字, 你给省略了」→ 换行 + 行高自适应 + 该列可拖宽
        self.tbl.setWordWrap(True)
        self.tbl.setTextElideMode(Qt.ElideNone)
        _hh = self.tbl.horizontalHeader()
        _hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        _hh.setSectionResizeMode(1, QHeaderView.Interactive)
        _hh.setSectionResizeMode(2, QHeaderView.Stretch)
        self.tbl.setColumnWidth(1, 360)
        self.tbl.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tbl.verticalHeader().setVisible(False)
        right.addWidget(self.tbl)
        self.txt_raw = QTextEdit()
        self.txt_raw.setReadOnly(True)
        self.txt_raw.setPlaceholderText("原始输出 (模型返回全文)")
        self.txt_raw.setMaximumHeight(150)
        right.addWidget(self.txt_raw)
        _lw, _rw = QWidget(), QWidget()
        _lw.setLayout(left); _rw.setLayout(right)
        split.addWidget(_lw); split.addWidget(_rw)
        split.setStretchFactor(0, 4); split.setStretchFactor(1, 5)   # 画面:判读 ≈ 4:5
        split.setSizes([560, 660])
        v.addWidget(split, 4)
        self.split = split

        # ── 人机在环红线 ──
        self.lbl_gate = QLabel("⚠️ 人机在环: 本节点输出=『场景判读 + 建议』; "
                               "任何机械臂动作仍须操作员确认后才下发 (模型不直接驱动机器人)。")
        self.lbl_gate.setStyleSheet("color:#f0c674; background:#161b22; border:1px solid #30363d; "
                                    "border-radius:5px; padding:6px;")
        self.lbl_gate.setWordWrap(True)
        v.addWidget(self.lbl_gate)

        # ── 历史 ──
        v.addWidget(QLabel("判读历史 (最近 20 次, 自动刷新)"))
        self.tbl_hist = QTableWidget(0, 6)
        self.tbl_hist.setHorizontalHeaderLabels(["时间", "模式", "耗时ms", "来源", "结论 (标定建议/下一步)", "画面"])
        self.tbl_hist.setWordWrap(True)
        self.tbl_hist.setTextElideMode(Qt.ElideNone)
        _h2 = self.tbl_hist.horizontalHeader()
        for _c in (0, 1, 2, 4):
            _h2.setSectionResizeMode(_c, QHeaderView.ResizeToContents)
        _h2.setSectionResizeMode(3, QHeaderView.Interactive)
        _h2.setSectionResizeMode(5, QHeaderView.Stretch)
        self.tbl_hist.setColumnWidth(3, 170)
        self.tbl_hist.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tbl_hist.verticalHeader().setVisible(False)
        v.addWidget(self.tbl_hist, 2)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(5000)
        self.refresh()

    # ── 数据刷新 ──
    def refresh(self):
        calls = _read_calls(40)
        last = calls[0] if calls else {}
        st = {}
        try:
            import sys
            sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))
            from lerobot.policies.left_right.state_space.scene_vlm import SceneVLM      # noqa: PLC0415
            st = SceneVLM.get().status()
        except Exception as e:                                                     # noqa: BLE001
            st = {"path": "未知", "model": "未知", "detail": f"{type(e).__name__}: {e}"}
        n_ok = sum(1 for c in calls if c.get("ok"))
        self.lbl_status.setText(
            f"模型: {st.get('model')} · 路径: {st.get('detail')} · 累计调用 {len(calls)} 次 (成功 {n_ok}) · "
            f"最近耗时 {last.get('latency_ms', '—')}ms\n日志: {CALLS}")
        # 图像
        fp = next((f for f in FRAMES if os.path.exists(f)), None)
        if fp:
            age = time.time() - os.path.getmtime(fp)
            pix = QPixmap(fp)
            if not pix.isNull():
                self.lbl_img.setPixmap(pix.scaled(self.lbl_img.width(), self.lbl_img.height(),
                                                  Qt.KeepAspectRatio, Qt.SmoothTransformation))
            clock = " ⏰时钟异常(负帧龄, 拒用)" if age < 0 else ""
            self.lbl_img_info.setText(f"画面: {os.path.basename(fp)} · 帧龄 {age:.2f}s{clock} · "
                                      f"分辨率 {pix.width()}x{pix.height()}")
        # 判读字段
        j = (last.get("json") or {}) if isinstance(last.get("json"), dict) else {}
        self.tbl.setRowCount(0)
        for k, val in j.items():
            r = self.tbl.rowCount()
            self.tbl.insertRow(r)
            self.tbl.setItem(r, 0, QTableWidgetItem(str(k)))
            self.tbl.setItem(r, 1, QTableWidgetItem(FIELD_HELP.get(str(k), "(模型输出字段)")))
            self.tbl.setItem(r, 2, QTableWidgetItem(_fmt_val(val)))
        self.txt_raw.setPlainText(str(last.get("text") or last.get("why") or "(暂无判读记录 — 点上面的按钮跑一次)"))
        # 历史
        self.tbl_hist.setRowCount(0)
        for c in calls[:20]:
            r = self.tbl_hist.rowCount()
            self.tbl_hist.insertRow(r)
            ts = time.strftime("%m-%d %H:%M:%S", time.localtime(c.get("ts", 0)))
            jj = c.get("json") or {}
            concl = (jj.get("标定建议") or jj.get("下一步动作") or jj.get("问题")
                     or ("OK" if c.get("ok") else c.get("why", "失败")))
            if isinstance(concl, list):
                concl = " / ".join(str(x) for x in concl) or "OK"
            for i, t in enumerate([ts, c.get("mode", ""), str(c.get("latency_ms", "")),
                                   str(c.get("src", "")), str(concl)[:70],
                                   os.path.basename(str(c.get("frame", "")))]):
                self.tbl_hist.setItem(r, i, QTableWidgetItem(t))
        try:
            self.tbl.resizeRowsToContents()
            self.tbl_hist.resizeRowsToContents()
        except Exception:                                                      # noqa: BLE001
            pass

    # ── 窗口几何记忆 (拖动/最大化后下次照旧) ──
    GEOM = os.path.expanduser("~/zmax_data/vlm_panel_geom.txt")

    def _restore_geom(self):
        try:
            with open(self.GEOM) as f:
                x, y, w, h = (int(v) for v in f.read().split()[:4])
            self.setGeometry(x, y, max(w, 880), max(h, 560))
        except Exception:                                                      # noqa: BLE001
            self.resize(1240, 780)

    def closeEvent(self, e):
        try:
            g = self.geometry()
            with open(self.GEOM, "w") as f:
                f.write(f"{g.x()} {g.y()} {g.width()} {g.height()}")
        except Exception:                                                      # noqa: BLE001
            pass
        super().closeEvent(e)

    def resizeEvent(self, e):
        """窗口放大/最大化后立刻重排画面与列宽 (不等 5s 轮询)"""
        super().resizeEvent(e)
        try:
            fp = next((f for f in FRAMES if os.path.exists(f)), None)
            if fp:
                pix = QPixmap(fp)
                if not pix.isNull():
                    self.lbl_img.setPixmap(pix.scaled(self.lbl_img.width(), self.lbl_img.height(),
                                                      Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.tbl.resizeRowsToContents()
            self.tbl_hist.resizeRowsToContents()
        except Exception:                                                      # noqa: BLE001
            pass

    # ── 动作 ──
    def _ask(self, mode):
        if self._busy:
            return
        fp = next((f for f in FRAMES if os.path.exists(f)), None)
        if not fp:
            self.lbl_status.setText("⚠️ 没有可用画面 (真机帧不在) — 先在画布切到真机/仿真数据源")
            return
        self._busy = True
        self.lbl_status.setText(f"⏳ 已把画面发给 {mode} … (DeepSeek 冷启动可能 1~2 分钟, 缓存命中约 1s)")
        try:
            import sys
            sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))
            from lerobot.policies.left_right.state_space.scene_vlm import SceneVLM      # noqa: PLC0415
            v = SceneVLM.get()
            r = getattr(v, mode)(fp, {"stage": "现场"})
            if not r.get("ok"):
                self.lbl_status.setText(f"⚠️ 判读未成功: {r.get('why')}"
                                        + (f" · 规则回退: {r.get('rule')}" if r.get("rule") else ""))
        except Exception as e:                                                     # noqa: BLE001
            self.lbl_status.setText(f"⚠️ 调用异常: {type(e).__name__}: {e}")
        finally:
            self._busy = False
            self.refresh()

    def _open_dir(self):
        try:
            os.system(f'xdg-open "{os.path.dirname(CALLS)}" >/dev/null 2>&1 &')
        except Exception:                                                          # noqa: BLE001
            pass


_PANEL = None


def open_vlm_panel(parent=None, module=None, node=None):
    """菜单入口: 打开 (或前置) 判读结果窗口"""
    global _PANEL
    try:
        if _PANEL is not None:
            _PANEL.close()
    except Exception:                                                              # noqa: BLE001
        pass
    _PANEL = VlmPanel(parent=parent, module=module, node=node)
    _PANEL.show()
    return _PANEL
