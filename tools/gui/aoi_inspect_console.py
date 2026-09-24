#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aoi_inspect_console.py — 🔍 外观质量检测 · **质量检测汇总终端窗口** (2026-09-24 老倪需求)

需求: 「在外观质量检测节点上右键打开一个新窗口，能够将光模块金手指检查技能、图像定位、拉伸等技能，
以及光模块外观检测、外观图像的显示、缺陷显示、框选，以及当视频里看到新缺陷的时候，能够马上标定，
进行在线的 YOLO 训练；这个窗口是**质量检测的汇总终端窗口**」

设计: docs/design/aoi_quality_head_and_console_20260924.md
  · 一行技能 (金手指/外观/光口/全帧) · 一行标定 (复用 YoloLabelWidget) · 一行数据/训练
  · 左画面 (缺陷框 + ROI 高亮 + 拉伸倍率) · 右面板 (判决表 / 定位 / 缺陷清单 / 训练日志)
  · 所有按钮 = 真函数 (禁止占位); 无权重时启发式兜底并明标 source=heuristic
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (os.path.join(ROOT, "tools"), os.path.join(ROOT, "tools", "gui"),
           os.path.join(ROOT, "src", "lerobot", "policies", "yolo_3d")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from PyQt5 import QtCore, QtGui, QtWidgets                             # noqa: E402
from yolo_label_widget import YoloLabelWidget                          # noqa: E402
import yolo_annot_dataset as yad                                       # noqa: E402
from aoi_head import AoiQualityHead, AOI_CLASSES, CLASS_CN, ROI_SKILLS  # noqa: E402

SHARED = os.environ.get("ZMAX_SS_REMOTE_DIR", "/home/ubuntu/zmax_ss_remote")
REAL_CANDS = ("cam_rs.png", "cam_local.png", "cam_usb.png")
TRAIN_PY = os.path.join(ROOT, "tools", "yolo_annot_train.py")
PY = os.path.join(ROOT, "gui-venv311", "bin", "python")
GREEN, RED, ORANGE = "#3fb950", "#f85149", "#d29922"


def _qss() -> str:
    return ("QDialog{background:#0d1117;color:#e6edf3} QLabel{color:#e6edf3}"
            "QPushButton{background:#21262d;color:#e6edf3;border:1px solid #30363d;padding:4px 8px;border-radius:4px}"
            "QPushButton:hover{background:#30363d} QPushButton:disabled{color:#6e7681}"
            "QCheckBox{color:#e6edf3} QComboBox,QLineEdit,QSpinBox{background:#161b22;color:#e6edf3;border:1px solid #30363d}"
            "QTableWidget{background:#0d1117;color:#e6edf3;gridline-color:#30363d}"
            "QHeaderView::section{background:#161b22;color:#e6edf3;border:1px solid #30363d}"
            "QPlainTextEdit{background:#010409;color:#7ee787;border:1px solid #30363d}")


class AoiInspectConsole(QtWidgets.QDialog):
    """质量检测汇总终端 (右键「🔍 外观质量检测」→ 打开)。"""

    def __init__(self, parent=None, module=None, source: str = "real", head=None):
        super().__init__(parent)
        self.setWindowTitle("🔍 外观质量检测 · 汇总终端 (质量检测任务头)")
        self.resize(1540, 940)
        self.setStyleSheet(_qss())
        self.module = module
        self.source = source
        self.head = head or AoiQualityHead()
        self._last_rgb = None
        self._last_tag = "无帧"
        self._last_res = None
        self._train_proc = None
        self._build()
        self._sync_classes()
        self._init_data_root()
        self._tick()                                    # 立即取一帧
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(500)

    # ══════════════════════ UI ══════════════════════
    def _build(self):
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)

        # ── 第 1 行 技能 (入口恒常显) ──
        r1 = QtWidgets.QHBoxLayout()
        self.skill_btns = {}
        for key in ("gold_finger", "module_body", "optical_port", "full"):
            name, _ = ROI_SKILLS[key]
            b = QtWidgets.QPushButton(name)
            b.setToolTip(f"技能: {name} (ROI={'全帧' if key == 'full' else key})")
            b.clicked.connect(lambda _=False, k=key: self.run_skill(k))
            r1.addWidget(b)
            self.skill_btns[key] = b
        r1.addStretch(1)
        r1.addWidget(QtWidgets.QLabel("源:"))
        self.cmb_src = QtWidgets.QComboBox()
        self.cmb_src.addItems(["🎥 真机 RealSense", "🧪 仿真 metaworld", "🖼 载入帧文件"])
        self.cmb_src.setCurrentIndex(0 if self.source != "sim" else 1)
        self.cmb_src.currentIndexChanged.connect(self._on_src_change)
        r1.addWidget(self.cmb_src)
        self.lbl_chain = QtWidgets.QLabel("链路: 取帧中…")
        self.lbl_chain.setMinimumWidth(320)
        r1.addWidget(self.lbl_chain)
        self.lbl_time = QtWidgets.QLabel("推理: -")
        r1.addWidget(self.lbl_time)
        v.addLayout(r1)

        # ── 第 2 行 标定 ──
        r2 = QtWidgets.QHBoxLayout()
        self.chk_label = QtWidgets.QCheckBox("✏️ 标定模式")
        self.chk_label.setToolTip("勾选后在画面上拖框/移动/四角缩放 (存原始帧像素坐标)")
        self.chk_label.toggled.connect(self._on_label_toggle)
        r2.addWidget(self.chk_label)
        self.cmb_cls = QtWidgets.QComboBox()
        self.cmb_cls.setMinimumWidth(180)
        r2.addWidget(QtWidgets.QLabel("类别:"))
        r2.addWidget(self.cmb_cls)
        self.btn_newcls = QtWidgets.QPushButton("＋新类别")
        self.btn_newcls.clicked.connect(self._add_class)
        r2.addWidget(self.btn_newcls)
        self.btn_save = QtWidgets.QPushButton("💾 保存标注")
        self.btn_save.clicked.connect(lambda: self._save_annot(next_frame=False))
        r2.addWidget(self.btn_save)
        self.btn_savenext = QtWidgets.QPushButton("⏭ 保存并下一帧")
        self.btn_savenext.clicked.connect(lambda: self._save_annot(next_frame=True))
        r2.addWidget(self.btn_savenext)
        self.btn_setcls = QtWidgets.QPushButton("🏷 改选中类别")
        self.btn_setcls.clicked.connect(self._set_selected_class)
        r2.addWidget(self.btn_setcls)
        self.btn_undo = QtWidgets.QPushButton("↩ 撤销")
        self.btn_undo.clicked.connect(lambda: self.wid.undo())
        r2.addWidget(self.btn_undo)
        self.btn_del = QtWidgets.QPushButton("🗑 删选中")
        self.btn_del.clicked.connect(lambda: self.wid.remove_selected())
        r2.addWidget(self.btn_del)
        self.btn_clear = QtWidgets.QPushButton("✖ 清空框")
        self.btn_clear.clicked.connect(lambda: self.wid.clear_boxes())
        r2.addWidget(self.btn_clear)
        r2.addWidget(QtWidgets.QLabel("标定员:"))
        self.ed_annotator = QtWidgets.QLineEdit("engineer")
        self.ed_annotator.setMaximumWidth(100)
        r2.addWidget(self.ed_annotator)
        v.addLayout(r2)

        # ── 第 3 行 数据 / 训练 ──
        r3 = QtWidgets.QHBoxLayout()
        self.lbl_data = QtWidgets.QLabel("样本 -")
        self.lbl_data.setWordWrap(True)
        self.lbl_data.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        r3.addWidget(self.lbl_data, 1)
        self.btn_build = QtWidgets.QPushButton("📦 构建数据集")
        self.btn_build.clicked.connect(self._build_dataset)
        r3.addWidget(self.btn_build)
        self.btn_check = QtWidgets.QPushButton("🔍 体检")
        self.btn_check.clicked.connect(self._check_dataset)
        r3.addWidget(self.btn_check)
        r3.addWidget(QtWidgets.QLabel("epochs:"))
        self.sp_epochs = QtWidgets.QSpinBox()
        self.sp_epochs.setRange(1, 500)
        self.sp_epochs.setValue(30)
        r3.addWidget(self.sp_epochs)
        self.btn_train = QtWidgets.QPushButton("🚀 在线训练 (增量)")
        self.btn_train.clicked.connect(self._train)
        r3.addWidget(self.btn_train)
        self.btn_live = QtWidgets.QPushButton("⬆ 切到在役")
        self.btn_live.setToolTip("人工确认后把最新权重软链到 models/yolo_aoi_live.pt (旧链留档可回滚)")
        self.btn_live.clicked.connect(self._switch_live)
        r3.addWidget(self.btn_live)
        self.btn_datadir = QtWidgets.QPushButton("📂 数据目录")
        self.btn_datadir.clicked.connect(self._open_datadir)
        r3.addWidget(self.btn_datadir)
        v.addLayout(r3)

        # ── 主体: 左画面 / 右面板 ──
        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        left = QtWidgets.QWidget()
        lv = QtWidgets.QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        self.wid = YoloLabelWidget(editable=False)
        lv.addWidget(self.wid, 1)
        lr = QtWidgets.QHBoxLayout()
        self.chk_freeze = QtWidgets.QCheckBox("🧊 冻结 (标定用)")
        self.chk_freeze.toggled.connect(lambda *_: None)
        lr.addWidget(self.chk_freeze)
        self.sp_zoom = QtWidgets.QDoubleSpinBox()
        self.sp_zoom.setRange(1.0, 6.0)
        self.sp_zoom.setSingleStep(0.5)
        self.sp_zoom.setValue(self.head.zoom)
        self.sp_zoom.setPrefix("拉伸 ")
        self.sp_zoom.valueChanged.connect(lambda _v: self._run_skill(self._cur_skill, quiet=True))
        lr.addWidget(self.sp_zoom)
        self.chk_roi = QtWidgets.QCheckBox("ROI 高亮")
        self.chk_roi.setChecked(True)
        lr.addWidget(self.chk_roi)
        self.lbl_roi = QtWidgets.QLabel("ROI: -")
        lr.addWidget(self.lbl_roi)
        lr.addStretch(1)
        lv.addLayout(lr)
        split.addWidget(left)

        right = QtWidgets.QWidget()
        rv = QtWidgets.QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.addWidget(self._hdr("① 判决表 (启发式数值 ‖ 学习头缺陷, 来源可辨)"))
        self.tbl_verdict = self._table(["目标", "缺陷/判据", "数值", "阈值", "结论", "来源"])
        rv.addWidget(self.tbl_verdict, 3)
        rv.addWidget(self._hdr("② 定位结果 (图像定位 → ROI 拉伸)"))
        self.tbl_loc = self._table(["类别", "conf", "框 (原帧 px)"])
        rv.addWidget(self.tbl_loc, 2)
        rv.addWidget(self._hdr("③ 缺陷清单 (新缺陷 → 框选标定)"))
        self.tbl_def = self._table(["类别", "目标", "conf", "框"])
        self.tbl_def.cellDoubleClicked.connect(self._goto_defect)
        rv.addWidget(self.tbl_def, 2)
        rv.addWidget(self._hdr("④ 在线训练日志"))
        self.txt_log = QtWidgets.QPlainTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumBlockCount(2000)
        rv.addWidget(self.txt_log, 3)
        split.addWidget(right)
        split.setSizes([900, 620])
        v.addWidget(split, 1)

        # ── 第 4 行 状态栏 ──
        r4 = QtWidgets.QHBoxLayout()
        self.lbl_verdict = QtWidgets.QLabel("判决: -")
        self.lbl_verdict.setMinimumWidth(240)
        r4.addWidget(self.lbl_verdict)
        self.lbl_defects = QtWidgets.QLabel("缺陷: -")
        r4.addWidget(self.lbl_defects, 1)
        self.btn_expjson = QtWidgets.QPushButton("📄 导出判决 JSON")
        self.btn_expjson.clicked.connect(self._export_json)
        r4.addWidget(self.btn_expjson)
        self.btn_expcsv = QtWidgets.QPushButton("📥 导出清单 CSV")
        self.btn_expcsv.clicked.connect(self._export_csv)
        r4.addWidget(self.btn_expcsv)
        v.addLayout(r4)

        self._cur_skill = "gold_finger"
        self.log(f"🔍 质量检测汇总终端启动 · 任务头权重: {self.head.weights or '(无 → 启发式兜底)'}")
        self.log(f"   类别 schema ({len(AOI_CLASSES)}): " + " / ".join(AOI_CLASSES))
        if self.head._load_err:
            self.log(f"   ⚠️ {self.head._load_err}")

    def _hdr(self, t):
        lbl = QtWidgets.QLabel(t)
        lbl.setStyleSheet("color:#58a6ff;font-weight:bold;padding-top:4px")
        return lbl

    def _table(self, cols):
        t = QtWidgets.QTableWidget(0, len(cols))
        t.setHorizontalHeaderLabels(cols)
        t.verticalHeader().setVisible(False)
        t.setEditTriggers(QtWidgets.QTableWidget.NoEditTriggers)
        t.setSelectionBehavior(QtWidgets.QTableWidget.SelectRows)
        t.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
        t.horizontalHeader().setStretchLastSection(True)
        return t

    def log(self, s: str):
        try:
            self.txt_log.appendPlainText(str(s))
        except RuntimeError:                                   # 窗口已销毁 (进程收尾信号晚到)
            print("[aoi-console]", s)

    # ══════════════════════ 取帧 / 链路 ══════════════════════
    def _grab(self):
        if self.chk_freeze.isChecked() and self._last_rgb is not None:
            return self._last_rgb, f"冻结/{self._last_tag}", None
        if self.cmb_src.currentIndex() == 1:                       # 仿真
            try:
                import yolo_input_viewer as yiv
                fr = yiv._engine_live_frame(2.0)
                if fr is not None:
                    return fr, "🧪 引擎实时帧 (metaworld corner2)", 0.0
                return None, "🧪 引擎未出帧 (需先运行引擎/输入图像窗口)", None
            except Exception as e:                                 # noqa: BLE001
                return None, f"🧪 仿真取帧失败: {type(e).__name__}", None
        if self.cmb_src.currentIndex() == 2:                       # 载入文件
            return None, "🖼 载入帧文件: 用「载入帧文件」按钮选图", None
        # 真机: 与 L2 同源 (Docker tap 落盘) — 帧龄校验, 负/超龄拒用
        for name in REAL_CANDS:
            p = os.path.join(SHARED, name)
            if not os.path.isfile(p):
                continue
            age = time.time() - os.path.getmtime(p)
            if age < 0:
                return None, f"🎥 {name} 帧龄为负 (时钟异常) → 拒用", None
            if age > 5.0:
                return None, f"🎥 {name} 帧龄 {age:.1f}s > 5s → 拒用 (不拿旧图冒充实时)", age
            try:
                import yolo_input_viewer as yiv
                return yiv.rgb_from_file(p), f"🎥 真机 {name}", age
            except Exception:                                      # noqa: BLE001
                continue
        return None, "🎥 无真机实时帧 (需开『打开输入图像』拉流 / 或切仿真)", None

    def load_frame_file(self, path: str):
        """载入单帧文件 (测试/离线复看/标定素材)。"""
        if path.lower().endswith((".mp4", ".avi", ".mov", ".mkv")):
            import cv2
            cap = cv2.VideoCapture(path)
            ok, fr = cap.read()
            cap.release()
            if not ok:
                self.log(f"⚠️ 视频读不出首帧: {path}")
                return False
            self.cmb_src.setCurrentIndex(2)
            self._set_frame(cv2.cvtColor(fr, cv2.COLOR_BGR2RGB), f"🖼 视频首帧 {os.path.basename(path)}")
            self.run_skill(self._cur_skill, quiet=True)
            return True
        try:
            import yolo_input_viewer as yiv
            rgb = yiv.rgb_from_file(path)
        except Exception:                                          # noqa: BLE001
            import cv2
            bgr = cv2.imread(path)
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB) if bgr is not None else None
        if rgb is None:
            self.log(f"⚠️ 载入失败: {path}")
            return False
        self.cmb_src.setCurrentIndex(2)
        self._set_frame(rgb, f"🖼 文件 {os.path.basename(path)}")
        self.run_skill(self._cur_skill, quiet=True)
        return True

    def _set_frame(self, rgb, tag):
        self._last_rgb = np.asarray(rgb)
        self._last_tag = tag
        self.wid.set_frame_rgb(self._last_rgb)

    def _tick(self):
        rgb, tag, age = self._grab()
        if rgb is not None:
            self._set_frame(rgb, tag)
            self.wid.set_classes([CLASS_CN.get(c, c) for c in self._cls_names()])
            if not self.chk_label.isChecked():
                self.run_skill(self._cur_skill, quiet=True)
            self.lbl_chain.setText(f"链路: ✅ {tag}" + (f" · 帧龄 {age:.1f}s" if age is not None else ""))
        else:
            self.lbl_chain.setText(f"链路: ⚠️ {tag}")

    def _on_src_change(self, idx):
        self.source = "sim" if idx == 1 else "real"
        self._tick()

    # ══════════════════════ 技能 ══════════════════════
    def run_skill(self, roi_key: str, quiet: bool = False):
        """技能执行: 定位 → ROI 拉伸 → 缺陷检测 → 判决表。"""
        self._cur_skill = roi_key
        if self._last_rgb is None:
            if not quiet:
                self.log("⚠️ 还没有帧 (取帧中… 或切仿真/载入帧文件)")
            return None
        roi = ROI_SKILLS[roi_key][1]
        res = self.head.inspect(self._last_rgb, roi=roi, zoom=self.sp_zoom.value())
        self._last_res = res
        self._fill_verdict(res)
        # 缺陷框叠加 (学习头检出) + ROI 高亮
        for d in res["defects"]:
            if d["box"]:
                self.wid.add_box_px(d["box"], cls=CLASS_CN.get(d["cls"], d["cls"]))
        self.lbl_time.setText(f"推理 {res['elapsed_ms']:.0f}ms" +
                              (f" · {os.path.basename(res['weights'])}" if res["weights"] else " · 启发式"))
        rm = res["roi_meta"]
        self.lbl_roi.setText(f"ROI: {res['roi_skill'] or '全帧'} · 拉伸 ×{rm.get('zoom', 1):.2f} · "
                             f"框 {rm.get('box')}")
        if not quiet:
            self.log(f"▶ {ROI_SKILLS[roi_key][0]} · 定位 {len(res['loc'])} · 缺陷 {len(res['defects'])} · "
                     f"{res['elapsed_ms']:.0f}ms · 判决 {'PASS' if res['verdict']['pass'] else 'FAIL'}"
                     + (f" · {res['note']}" if res["note"] else ""))
        return res

    def _fill_verdict(self, res):
        v = res["verdict"]
        rows = v["items"]
        self.tbl_verdict.setRowCount(len(rows))
        for i, it in enumerate(rows):
            concl = "PASS" if it.get("pass") else "FAIL"
            cells = [it.get("target_id", "-"), f'{it.get("target", "")} · {it.get("defect", "")}',
                     str(it.get("value")), str(it.get("threshold")), concl,
                     it.get("source", "-")]
            for j, c in enumerate(cells):
                item = QtWidgets.QTableWidgetItem(c)
                if j == 4:
                    item.setForeground(QtGui.QColor(GREEN if it.get("pass") else RED))
                if it.get("source") == "model":
                    item.setForeground(QtGui.QColor(ORANGE))
                self.tbl_verdict.setItem(i, j, item)
        self.lbl_verdict.setText(f"判决: {'✅ PASS' if v['pass'] else '❌ FAIL'} "
                                 f"({sum(1 for r in rows if r.get('pass'))}/{len(rows)} 项通过)")
        self.lbl_verdict.setStyleSheet(f"color:{GREEN if v['pass'] else RED};font-weight:bold")
        self.tbl_loc.setRowCount(len(res["loc"]))
        for i, l in enumerate(res["loc"]):
            for j, c in enumerate([f'{l["cls"]} ({l["cn"]})', str(l["conf"]),
                                   ", ".join(f"{v:.0f}" for v in l["box"])]):
                self.tbl_loc.setItem(i, j, QtWidgets.QTableWidgetItem(c))
        self.tbl_def.setRowCount(len(res["defects"]))
        for i, d in enumerate(res["defects"]):
            for j, c in enumerate([f'{d["cls"]} ({d["cn"]})', d["target"], str(d["conf"]),
                                   ", ".join(f"{v:.0f}" for v in d["box"])]):
                self.tbl_def.setItem(i, j, QtWidgets.QTableWidgetItem(c))
        self.lbl_defects.setText(f"缺陷: {v['n_defects']} 个" +
                                 (" · " + " / ".join(f'{d["cn"]}×1' for d in res["defects"])
                                  if res["defects"] else " (无检出)"))

    def _goto_defect(self, row, _col):
        """双击缺陷行 → 冻结 + 把该缺陷框加入标定 (新缺陷马上标定的入口)。"""
        if not self._last_res or row >= len(self._last_res["defects"]):
            return
        d = self._last_res["defects"][row]
        self.chk_freeze.setChecked(True)
        self.chk_label.setChecked(True)
        self._select_class_in_combo(d["cls"])
        self.wid.add_box_px(d["box"], cls=CLASS_CN.get(d["cls"], d["cls"]))
        self.log(f"🎯 已把该缺陷框加入标定 (类别 {CLASS_CN.get(d['cls'], d['cls'])}); "
                 f"确认/修改后点 💾 保存标注")

    # ══════════════════════ 标定 ══════════════════════
    def _cls_names(self) -> list:
        try:
            names = yad.load_classes(self.head.root)
            return names or list(AOI_CLASSES)
        except Exception:                                          # noqa: BLE001
            return list(AOI_CLASSES)

    def _sync_classes(self):
        self.head.ensure_schema()
        names = self._cls_names()
        self.cmb_cls.clear()
        for c in names:
            self.cmb_cls.addItem(f"{CLASS_CN.get(c, c)} [{c}]", c)
        self.wid.set_classes([CLASS_CN.get(c, c) for c in names])
        try:
            self.lbl_data.setText(f"样本 {len(list(yad.iter_samples(self.head.root)))} 张 · "
                                  f"类别 {len(names)} · 根 {self.head.root}"
                                  f" · 权重 {os.path.basename(self.head.weights) if self.head.weights else '无(启发式)'}")
        except Exception:                                          # noqa: BLE001
            pass

    def _init_data_root(self):
        try:
            yad.ensure_layout(self.head.root, classes=self._cls_names())
        except Exception as e:                                     # noqa: BLE001
            self.log(f"⚠️ 数据根初始化失败: {type(e).__name__}: {e}")

    def _on_label_toggle(self, on):
        self.wid.set_editable(bool(on))
        self.log(f"✏️ 标定模式: {'开 (画面上拖框/缩放, 存原始帧像素坐标)' if on else '关'}")

    def _add_class(self):
        name, ok = QtWidgets.QInputDialog.getText(self, "新类别", "类名 (英文, 作为 class id):")
        if not ok or not name.strip():
            return
        name = name.strip().replace(" ", "_")
        try:
            cid = yad.add_class(self.head.root, name)
            self._sync_classes()
            self.log(f"➕ 新类别 {name} → id {cid} (已写入 {self.head.classes_path()}; "
                     f"⚠️ 类别顺序=schema, 改后需重启任务头生效)")
        except Exception as e:                                     # noqa: BLE001
            self.log(f"⚠️ 加类别失败: {type(e).__name__}: {e}")

    def _select_class_in_combo(self, name):
        for i in range(self.cmb_cls.count()):
            if self.cmb_cls.itemData(i) == name:
                self.cmb_cls.setCurrentIndex(i)
                self.wid.set_current_class(self.cmb_cls.currentText())
                return

    def _save_annot(self, next_frame=False):
        if self._last_rgb is None:
            self.log("⚠️ 无帧可存")
            return
        # ⚠️ 数据层契约: boxes = [(x1,y1,x2,y2, cls_id|cls_name), ...] (5 元组, 不是 (box, id))
        boxes = []
        for b in self.wid.boxes_px():
            cls_txt = b.get("cls", "") if isinstance(b, dict) else ""
            cname = None
            for i in range(self.cmb_cls.count()):
                if self.cmb_cls.itemText(i) == cls_txt or self.cmb_cls.itemData(i) == cls_txt:
                    cname = self.cmb_cls.itemData(i)
                    break
            if cname is None:
                cname = self.cmb_cls.currentData() or AOI_CLASSES[0]
            bb = list(b["box"]) if isinstance(b, dict) else list(b)
            boxes.append((bb[0], bb[1], bb[2], bb[3], cname))
        kw = {"device": self._last_tag, "annotator": self.ed_annotator.text() or "engineer",
              "src": ("sim" if self.cmb_src.currentIndex() == 1 else "real")}
        try:
            sig = set(yad.save_sample.__code__.co_varnames[:yad.save_sample.__code__.co_argcount])
            kw = {k: v for k, v in kw.items() if k in sig}
            r = yad.save_sample(self.head.root, self._last_rgb, boxes, **kw)
            n = len(boxes)
            self.log(f"💾 已保存标注: {n} 框 → {json.dumps(r, ensure_ascii=False)[:160]}")
        except Exception as e:                                     # noqa: BLE001
            self.log(f"❌ 保存失败: {type(e).__name__}: {e}")
            return
        self.wid.clear_boxes()
        self._sync_classes()
        if next_frame:
            self.chk_freeze.setChecked(False)

    def _set_selected_class(self):
        self.wid.set_selected_class(self.cmb_cls.currentText())
        self.log(f"🏷 选中框类别 → {self.cmb_cls.currentText()}")

    # ══════════════════════ 数据 / 训练 ══════════════════════
    def _build_dataset(self):
        try:
            st = yad.build_dataset(self.head.root)
            self.log(f"📦 构建数据集: {json.dumps(st, ensure_ascii=False)[:300]}")
            self._sync_classes()
        except Exception as e:                                     # noqa: BLE001
            self.log(f"❌ 构建失败: {type(e).__name__}: {e}")

    def _check_dataset(self):
        st = self.head.stats()
        self.log(f"🔍 体检: {json.dumps(st, ensure_ascii=False)[:400]}")

    def _train(self):
        if self._train_proc is not None:
            self.log("⚠️ 已有训练在跑")
            return
        ds = os.path.join(self.head.root, "dataset")
        if not os.path.isdir(ds) or not os.path.isfile(os.path.join(ds, "data.yaml")):
            self.log("⚠️ 还没有数据集 → 先「📦 构建数据集」")
            return
        base = self.head.weights if self.head.model_ready else "auto"
        name = "aoi_" + time.strftime("%m%d_%H%M")
        cmd = [PY, TRAIN_PY, "--data", ds, "--root", self.head.root, "--base", base,
               "--epochs", str(self.sp_epochs.value()), "--name", name,
               "--project", "outputs/yolo_aoi"]
        self.log(f"🚀 在线训练 (增量微调): {' '.join(cmd)}")
        self._train_proc = QtCore.QProcess(self)
        self._train_proc.setWorkingDirectory(ROOT)
        # ⚠️ 信号里**别引用 self._train_proc** (进程结束时 C++ 对象已删 → RuntimeError);
        #    用默认参数把进程对象绑进闭包 (2026-09-24 实测踩到)
        _p = self._train_proc
        self._train_proc.readyReadStandardOutput.connect(
            lambda pr=_p: self.log(pr.readAllStandardOutput().data().decode(errors="ignore").rstrip()))
        self._train_proc.readyReadStandardError.connect(
            lambda pr=_p: self.log(pr.readAllStandardError().data().decode(errors="ignore").rstrip()))
        self._train_proc.finished.connect(lambda code, _s: self._on_train_done(code, name))
        env = QtCore.QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")
        self._train_proc.setProcessEnvironment(env)
        self._train_proc.start(cmd[0], cmd[1:])

    def _on_train_done(self, code, name):
        self._train_proc = None
        self.log(f"🏁 训练进程退出 code={code} · run={name}")
        w = os.path.join(ROOT, "runs", "detect", "outputs", "yolo_aoi", name, "weights", "best.pt")
        if os.path.isfile(w):
            self._last_best = w
            self.log(f"✅ 产物: {w}  →  在曲线/精度确认后点「⬆ 切到在役」(人工确认, 不自动切)")
        else:
            self._last_best = ""
            self.log("⚠️ 未找到 best.pt (训练可能失败; 看上面日志)")

    def _switch_live(self):
        w = getattr(self, "_last_best", "")
        if not w or not os.path.isfile(w):
            self.log("⚠️ 没有可切的权重 (先训练出 best.pt)")
            return
        link = os.path.join(ROOT, "models", "yolo_aoi_live.pt")
        try:
            old = os.path.realpath(link) if os.path.islink(link) else ""
            with open(os.path.join(ROOT, "models", "yolo_aoi_live.prev.txt"), "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%F %T')} old={old} new={w}\n")
            if os.path.islink(link) or os.path.isfile(link):
                os.remove(link)
            os.symlink(w, link)
            self.log(f"⬆ 已切在役: models/yolo_aoi_live.pt → {w} (旧链 {old or '无'} 已留档 .prev.txt)")
        except Exception as e:                                     # noqa: BLE001
            self.log(f"❌ 切在役失败: {type(e).__name__}: {e}")

    def _open_datadir(self):
        try:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(self.head.root))
        except Exception:                                          # noqa: BLE001
            self.log(f"数据根: {self.head.root}")

    # ══════════════════════ 导出 ══════════════════════
    def _export_json(self):
        if not self._last_res:
            self.log("⚠️ 无结果可导出")
            return
        p = os.path.join(ROOT, "reports", f"aoi_inspect_{time.strftime('%Y%m%d_%H%M%S')}.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self._last_res, f, ensure_ascii=False, indent=1)
        self.log(f"📄 判决 JSON → {p}")

    def _export_csv(self):
        if not self._last_res:
            self.log("⚠️ 无结果可导出")
            return
        p = os.path.join(ROOT, "reports", f"aoi_inspect_{time.strftime('%Y%m%d_%H%M%S')}.csv")
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["target_id", "target", "defect", "value", "threshold", "pass", "source"])
            for it in self._last_res["verdict"]["items"]:
                w.writerow([it.get("target_id"), it.get("target"), it.get("defect"), it.get("value"),
                            it.get("threshold"), it.get("pass"), it.get("source")])
        self.log(f"📥 清单 CSV → {p}")

    # 标定快捷键 (输入框有焦点不抢键)
    def closeEvent(self, ev):                                      # noqa: N802
        """关窗收口: 断开信号 + 终止在跑训练 (避免进程收尾信号打到已销毁控件)。"""
        p = self._train_proc
        self._train_proc = None
        if p is not None:
            for sig in ("readyReadStandardOutput", "readyReadStandardError", "finished"):
                try:
                    getattr(p, sig).disconnect()
                except Exception:                                  # noqa: BLE001
                    pass
            try:
                if p.state() != QtCore.QProcess.NotRunning:
                    p.kill()
                    self.log("⚠️ 关窗: 训练进程已终止")
            except Exception:                                      # noqa: BLE001
                pass
        self._timer.stop()
        super().closeEvent(ev)

    def keyPressEvent(self, ev):                                   # noqa: N802
        fw = QtWidgets.QApplication.focusWidget()
        if isinstance(fw, (QtWidgets.QLineEdit, QtWidgets.QComboBox, QtWidgets.QPlainTextEdit,
                           QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):
            return super().keyPressEvent(ev)
        k = ev.key()
        if k == QtCore.Qt.Key_Return and self.chk_label.isChecked():
            self._save_annot(False)
        elif k == QtCore.Qt.Key_N and self.chk_label.isChecked():
            self._save_annot(True)
        elif k == QtCore.Qt.Key_F:
            self.chk_freeze.setChecked(not self.chk_freeze.isChecked())
        elif k == QtCore.Qt.Key_G:
            self.chk_roi.setChecked(not self.chk_roi.isChecked())
        else:
            return super().keyPressEvent(ev)
        ev.accept()


def open_aoi_console(parent=None, module=None, source: str = "real", head=None):
    """右键入口: 打开质量检测汇总终端 (单实例复用)。"""
    w = getattr(AoiInspectConsole, "_cur", None)
    if w is not None:
        try:
            w.close()
        except Exception:                                          # noqa: BLE001
            pass
    w = AoiInspectConsole(parent=parent, module=module, source=source, head=head)
    AoiInspectConsole._cur = w
    w.show()
    w.raise_()
    w.activateWindow()
    return w
