#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aoi_inspect_console.py — 🔍 外观质量检测 · **质量检测汇总终端** (UI v2, 2026-09-24)

老倪 v2 反馈: 「最大化按钮不好用; 字数太多太挤, 有的显示不全; 太乱了, 要简洁清晰」

UI v2 三条纪律:
  ① **最大化必须真能用**: QDialog 默认 Qt.Dialog 类型在 X11 下最大化按钮画了不响应 →
     显式 `setWindowFlags(Qt.Window | Max|Min|Close)` (类型必须换, 只加 hint 无效)
  ② **文案极简**: 一行一个词 (≤6 字), 长解释一律进 tooltip; 表格只留必要列
  ③ **不挤不截断**: 统一字体族/字号 (Noto Sans CJK SC, 标题 9pt 表 8pt) + 行高 30px +
     长文本 `elidedText` 省略号 + tooltip 全文; 右面板改 **Tab 分离** (判决/检测/标定训练) 去堆叠

复用件 (不自造): 标定控件 YoloLabelWidget · 数据层 yolo_annot_dataset · 训练 yolo_annot_train
功能与接口不变 (离线/t真桌面验证脚本照跑): 四技能 / 图像定位+拉伸 / 缺陷框选标定 / 在线训练 / 切在役
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
import opt_camera_client as optc                                        # noqa: E402  (工控机 OPT 相机)

SHARED = os.environ.get("ZMAX_SS_REMOTE_DIR", "/home/ubuntu/zmax_ss_remote")
REAL_CANDS = ("cam_rs.png", "cam_local.png", "cam_usb.png")
TRAIN_PY = os.path.join(ROOT, "tools", "yolo_annot_train.py")
PY = os.path.join(ROOT, "gui-venv311", "bin", "python")
GREEN, RED, ORANGE, DIM = "#3fb950", "#f85149", "#d29922", "#8b949e"
FONT = '"Noto Sans CJK SC", "DejaVu Sans", sans-serif'


def _qss() -> str:
    return f"""
    QDialog,QWidget{{background:#0d1117;color:#e6edf3;font-family:{FONT};font-size:9pt}}
    QLabel{{color:#e6edf3}}
    QLabel#sec{{color:#58a6ff;font-weight:bold}}
    QLabel#dim{{color:{DIM}}}
    QPushButton{{background:#21262d;color:#e6edf3;border:1px solid #30363d;border-radius:4px;
                padding:5px 10px;min-height:22px}}
    QPushButton:hover{{background:#30363d}} QPushButton:disabled{{color:#6e7681}}
    QPushButton#pri{{background:#1f6feb;border-color:#1f6feb}}
    QPushButton#pri:hover{{background:#388bfd}}
    QCheckBox{{color:#e6edf3;padding:2px}}
    QComboBox,QLineEdit,QSpinBox,QDoubleSpinBox{{background:#161b22;color:#e6edf3;
        border:1px solid #30363d;border-radius:4px;padding:3px 6px;min-height:20px}}
    QTabWidget::pane{{border:1px solid #30363d;top:-1px}}
    QTabBar::tab{{background:#161b22;color:#8b949e;padding:6px 14px;border:1px solid #30363d}}
    QTabBar::tab:selected{{background:#0d1117;color:#e6edf3;border-bottom-color:#0d1117}}
    QTableWidget{{background:#0d1117;color:#e6edf3;gridline-color:#21262d;font-size:8pt;
                 border:1px solid #30363d}}
    QHeaderView::section{{background:#161b22;color:#c9d1d9;border:0;border-right:1px solid #30363d;
                         padding:4px 6px;font-size:8pt}}
    QPlainTextEdit{{background:#010409;color:#7ee787;border:1px solid #30363d;font-size:8pt}}
    QSplitter::handle{{background:#21262d;width:3px}}
    QFrame#hsep{{background:#21262d;max-height:1px}}
    """


class AoiInspectConsole(QtWidgets.QDialog):
    """质量检测汇总终端 v2 (简洁版): 三行工具 + 左画面 / 右 Tab + 一行状态。"""

    def __init__(self, parent=None, module=None, source: str = "real", head=None):
        super().__init__(parent)
        # ① 最大化真能用 (必须换窗口类型; 只加 hint 在 X11 无效)
        self.setWindowFlags(QtCore.Qt.Window | QtCore.Qt.WindowMaximizeButtonHint
                            | QtCore.Qt.WindowMinimizeButtonHint | QtCore.Qt.WindowCloseButtonHint)
        self.setWindowTitle("🔍 外观质量检测 · 汇总终端")
        self.resize(1500, 920)
        self.setMinimumSize(1200, 700)
        self.setStyleSheet(_qss())
        self.module = module
        self.source = source
        self.head = head or AoiQualityHead()
        self._last_rgb = None
        self._last_tag = "无帧"
        self._last_res = None
        self._last_best = ""
        self._cur_skill = "gold_finger"
        self._train_proc = None
        self._opt_rgb = None                     # 🏭 OPT 相机最近一帧 (绝不自动真拍)
        self._opt_meta = {}
        self._opt_tag = ""
        self._opt_lastres = {}
        self._build()
        self._sync_classes()
        self._init_data_root()
        self._tick()
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(500)

    # ══════════════════════ 小工具 ══════════════════════
    def _btn(self, text, tip, slot, primary=False):
        b = QtWidgets.QPushButton(text)
        b.setToolTip(tip)
        b.clicked.connect(slot)
        # 🚫 防截断 (老倪: "有的显示不全"): 最小宽 = 文本提示宽 → 布局挤压时按钮不再被裁字
        b.setMinimumWidth(b.sizeHint().width())
        if primary:
            b.setObjectName("pri")
        return b

    def _sep(self):
        f = QtWidgets.QFrame()
        f.setObjectName("hsep")
        f.setFrameShape(QtWidgets.QFrame.HLine)
        return f

    def _dim(self, text=""):
        lbl = QtWidgets.QLabel(text)
        lbl.setObjectName("dim")
        return lbl

    def _elide(self, lbl, text, tip=None):
        """长文本省略号 + tooltip 全文 (防显示不全)。"""
        fm = lbl.fontMetrics()
        lbl.setText(fm.elidedText(str(text), QtCore.Qt.ElideMiddle, max(60, lbl.width() or 260)))
        lbl.setToolTip(tip or str(text))

    def _table(self, cols, min_h=120):
        t = QtWidgets.QTableWidget(0, len(cols))
        t.setHorizontalHeaderLabels(cols)
        t.verticalHeader().setVisible(False)
        t.setEditTriggers(QtWidgets.QTableWidget.NoEditTriggers)
        t.setSelectionBehavior(QtWidgets.QTableWidget.SelectRows)
        t.setWordWrap(False)
        t.setShowGrid(False)
        t.setAlternatingRowColors(False)
        t.verticalHeader().setDefaultSectionSize(24)
        t.horizontalHeader().setStyleSheet("QHeaderView::section{padding:4px 6px}")
        t.setMinimumHeight(min_h)
        return t

    # ══════════════════════ UI ══════════════════════
    def _build(self):
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(5)

        # ── 行 1 技能 + 链路 ──
        r1 = QtWidgets.QHBoxLayout(); r1.setSpacing(6)
        self.skill_btns = {}
        for key in ("gold_finger", "module_body", "optical_port", "full"):
            short = {"gold_finger": "🔍 金手指", "module_body": "🪞 外观",
                     "optical_port": "🔘 光口", "full": "🖼 全帧"}[key]
            b = self._btn(short, f"{ROI_SKILLS[key][0]} — 定位→拉伸→缺陷检测→判决",
                          lambda _=False, k=key: self.run_skill(k))
            r1.addWidget(b)
            self.skill_btns[key] = b
        r1.addStretch(1)
        self.lbl_chain = self._dim("链路: 取帧中…")
        self.lbl_chain.setMinimumWidth(220)
        self.lbl_time = self._dim("推理 -")
        r1.addWidget(self.lbl_chain); r1.addWidget(self.lbl_time)
        v.addLayout(r1)
        v.addWidget(self._sep())

        # ── 行 2 数据源 (真机/仿真/文件/🏭 OPT 相机) ──
        r2src = QtWidgets.QHBoxLayout(); r2src.setSpacing(6)
        r2src.addWidget(self._dim("源"))
        self.cmb_src = QtWidgets.QComboBox()
        self.cmb_src.addItems(["🎥 真机", "🧪 仿真", "🖼 文件", "🏭 OPT 相机"])
        self.cmb_src.setToolTip("帧源: 真机 RealSense / 仿真 metaworld / 载入文件 / "
                                "工控机 OPT 相机 (金手指 10082 · 表面 10083)")
        self.cmb_src.setCurrentIndex(0 if self.source != "sim" else 1)
        self.cmb_src.setMinimumWidth(120)
        self.cmb_src.currentIndexChanged.connect(self._on_src_change)
        r2src.addWidget(self.cmb_src)
        # 🏭 OPT 相机控件 (工控机 192.168.23.23 → 奥普特相机; 真拍必须手动点)
        self.cmb_cam = QtWidgets.QComboBox()
        self.cmb_cam.addItems(["金手指 10082", "表面 10083"])
        self.cmb_cam.setToolTip("工控机上的两台 OPT 相机 (金手指 OPT-CC1-GG50 / 表面 OPT-CC1-C050-GG3-00)")
        self.cmb_cam.setMinimumWidth(120)
        self.cmb_via = QtWidgets.QComboBox()
        self.cmb_via.addItems(["本机直连", "经 Orin"])
        self.cmb_via.setToolTip("经 Orin = ssh 到 192.168.23.66 再 request (本机不在产线网时用)")
        self.cmb_via.setMinimumWidth(100)
        self.btn_opt_grab = self._btn("📸 拍帧", "⚠️ 真拍产线台一张 (工控机 /capture_detect + 取图)",
                                      lambda: self._opt_fetch(grab=True), primary=True)
        self.btn_opt_recent = self._btn("🖼 最近图", "取工控机内存里的最近一张 (不拍照, 但会过期)",
                                        lambda: self._opt_fetch(grab=False))
        self.btn_opt_verd = self._btn("📋 工控机判决", "GET /last_result (工控机自家模型判决: OK/NG/缺陷数)",
                                      self._opt_verdict)
        for wdg in (self.cmb_cam, self.cmb_via, self.btn_opt_grab, self.btn_opt_recent, self.btn_opt_verd):
            r2src.addWidget(wdg)
        self.btn_load = self._btn("📂 载入", "载入单帧图片/视频首帧 (离线复看与标定素材)", self._pick_file)
        r2src.addWidget(self.btn_load)
        r2src.addStretch(1)
        v.addLayout(r2src)
        v.addWidget(self._sep())

        # ── 行 2 标定 ──
        r2 = QtWidgets.QHBoxLayout(); r2.setSpacing(6)
        self.chk_label = QtWidgets.QCheckBox("✏️ 标定")
        self.chk_label.setToolTip("勾选后在画面上拖框/移动/四角缩放 (存原始帧像素坐标)")
        self.chk_label.toggled.connect(self._on_label_toggle)
        r2.addWidget(self.chk_label)
        self.cmb_cls = QtWidgets.QComboBox(); self.cmb_cls.setMinimumWidth(150); self.cmb_cls.setMaximumWidth(190)
        self.cmb_cls.setToolTip("标注类别 (定位类/缺陷类)")
        r2.addWidget(self._dim("类别")); r2.addWidget(self.cmb_cls)
        self.btn_newcls = self._btn("＋类别", "新增类别 (写入 classes.txt, 行号=class id)", self._add_class)
        self.btn_save = self._btn("💾 保存", "保存当前帧 + 框 (原始帧像素坐标)", lambda: self._save_annot(False))
        self.btn_savenext = self._btn("⏭ 下一帧", "保存并取下一帧 (实时流)", lambda: self._save_annot(True))
        self.btn_setcls = self._btn("🏷 改类", "把选中框改成 combo 里的类别", self._set_selected_class)
        self.btn_undo = self._btn("↩ 撤销", "撤销上一次框操作", lambda: self.wid.undo())
        self.btn_del = self._btn("🗑 删", "删除选中的框", lambda: self.wid.remove_selected())
        self.btn_clear = self._btn("✖ 清空", "清空全部框", lambda: self.wid.clear_boxes())
        for b in (self.btn_newcls, self.btn_save, self.btn_savenext, self.btn_setcls,
                  self.btn_undo, self.btn_del, self.btn_clear):
            r2.addWidget(b)
        r2.addStretch(1)
        r2.addWidget(self._dim("标定员"))
        self.ed_annotator = QtWidgets.QLineEdit("engineer")
        self.ed_annotator.setMaximumWidth(92)
        r2.addWidget(self.ed_annotator)
        v.addLayout(r2)

        # ── 行 3 数据 / 训练 ──
        r3 = QtWidgets.QHBoxLayout(); r3.setSpacing(6)
        self.lbl_data = self._dim("样本 -")
        self.lbl_data.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        r3.addWidget(self.lbl_data, 1)
        self.btn_build = self._btn("📦 构建", "把已保存标注构建成训练数据集", self._build_dataset)
        self.btn_check = self._btn("🔍 体检", "数据体检 (配对/类别/坐标/退化框/重复图)", self._check_dataset)
        r3.addWidget(self._dim("epochs"))
        self.sp_epochs = QtWidgets.QSpinBox(); self.sp_epochs.setRange(1, 500); self.sp_epochs.setValue(30)
        self.sp_epochs.setMaximumWidth(70)
        self.btn_train = self._btn("🚀 训练", "在线增量微调 (基座=当前权重, 日志在『标定·训练』页)",
                                   self._train, primary=True)
        self.btn_live = self._btn("⬆ 切在役", "把最新 best.pt 软链到 models/yolo_aoi_live.pt (旧链留档可回滚)",
                                  self._switch_live)
        self.btn_datadir = self._btn("📂 目录", "打开数据目录", self._open_datadir)
        for b in (self.btn_build, self.btn_check, self.btn_train, self.btn_live, self.btn_datadir):
            r3.addWidget(b)
        v.addLayout(r3)
        v.addWidget(self._sep())

        # ── 主体: 左画面 / 右 Tab ──
        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        split.setChildrenCollapsible(False)

        left = QtWidgets.QWidget(); lv = QtWidgets.QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0); lv.setSpacing(4)
        self.wid = YoloLabelWidget(editable=False)
        lv.addWidget(self.wid, 1)
        lr = QtWidgets.QHBoxLayout(); lr.setSpacing(8)
        lr.addWidget(self._dim("画面"))
        self.chk_freeze = QtWidgets.QCheckBox("🧊 冻结")
        self.chk_freeze.setToolTip("冻结当前帧 (标定时用); 取消=跟随实时流")
        lr.addWidget(self.chk_freeze)
        lr.addWidget(self._dim("拉伸"))
        self.sp_zoom = QtWidgets.QDoubleSpinBox(); self.sp_zoom.setRange(1.0, 6.0)
        self.sp_zoom.setSingleStep(0.5); self.sp_zoom.setValue(self.head.zoom); self.sp_zoom.setMaximumWidth(80)
        self.sp_zoom.setToolTip("ROI 拉伸倍率 (小缺陷需高分辨率才可见)")
        self.sp_zoom.valueChanged.connect(lambda _v: self.run_skill(self._cur_skill, quiet=True))
        lr.addWidget(self.sp_zoom)
        self.chk_roi = QtWidgets.QCheckBox("ROI 高亮")
        self.chk_roi.setChecked(True)
        lr.addWidget(self.chk_roi)
        self.lbl_roi = self._dim("ROI -")
        self.lbl_roi.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        lr.addWidget(self.lbl_roi, 1)
        lv.addLayout(lr)
        split.addWidget(left)

        right = QtWidgets.QWidget(); rv = QtWidgets.QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0); rv.setSpacing(4)
        self.tabs = QtWidgets.QTabWidget()
        # Tab1 判决
        t1 = QtWidgets.QWidget(); t1v = QtWidgets.QVBoxLayout(t1); t1v.setContentsMargins(6, 6, 6, 6)
        self.tbl_verdict = self._table(["目标", "判据", "数值", "阈值", "结论"], min_h=200)
        t1v.addWidget(self.tbl_verdict, 1)
        self.lbl_verdict = QtWidgets.QLabel("判决 -")
        t1v.addWidget(self.lbl_verdict)
        self.tabs.addTab(t1, "判决")
        # Tab2 检测
        t2 = QtWidgets.QWidget(); t2v = QtWidgets.QVBoxLayout(t2); t2v.setContentsMargins(6, 6, 6, 6)
        t2v.addWidget(self._dim("定位 (图像定位 → ROI)"))
        self.tbl_loc = self._table(["类别", "conf", "框 px"], min_h=100)
        t2v.addWidget(self.tbl_loc, 1)
        t2v.addWidget(self._dim("缺陷 (双击行 → 加入标定)"))
        self.tbl_def = self._table(["类别", "目标", "conf", "框"], min_h=120)
        self.tbl_def.cellDoubleClicked.connect(self._goto_defect)
        t2v.addWidget(self.tbl_def, 1)
        self.tabs.addTab(t2, "检测")
        # Tab3 标定·训练
        t3 = QtWidgets.QWidget(); t3v = QtWidgets.QVBoxLayout(t3); t3v.setContentsMargins(6, 6, 6, 6)
        self.lbl_train = self._dim("训练: 待启动 (先📦构建 → 🚀训练)")
        t3v.addWidget(self.lbl_train)
        self.txt_log = QtWidgets.QPlainTextEdit(); self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumBlockCount(1500)
        t3v.addWidget(self.txt_log, 1)
        self.tabs.addTab(t3, "标定·训练")
        rv.addWidget(self.tabs, 1)
        split.addWidget(right)
        split.setSizes([860, 560])
        v.addWidget(split, 1)

        # ── 状态行 ──
        r4 = QtWidgets.QHBoxLayout(); r4.setSpacing(8)
        self.lbl_state = QtWidgets.QLabel("判决 -")
        self.lbl_state.setMinimumWidth(200)
        self.lbl_defects = self._dim("缺陷 -")
        self.lbl_defects.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        r4.addWidget(self.lbl_state); r4.addWidget(self.lbl_defects, 1)
        self.btn_expjson = self._btn("📄 JSON", "导出本次判决 JSON", self._export_json)
        self.btn_expcsv = self._btn("📥 CSV", "导出判决清单 CSV", self._export_csv)
        r4.addWidget(self.btn_expjson); r4.addWidget(self.btn_expcsv)
        v.addLayout(r4)

        self.log(f"🔍 质量检测汇总终端 · 权重 {os.path.basename(self.head.weights) if self.head.weights else '无(启发式兜底)'}")
        self.log(f"   类别 {len(AOI_CLASSES)}: " + " ".join(AOI_CLASSES))
        if self.head._load_err:
            self.log(f"   ⚠️ {self.head._load_err}")

    def _sep_v(self):
        f = QtWidgets.QFrame()
        f.setFrameShape(QtWidgets.QFrame.VLine)
        f.setStyleSheet("color:#30363d")
        return f

    def log(self, s: str):
        try:
            self.txt_log.appendPlainText(str(s))
            self.lbl_train.setText("训练: " + str(s)[:110])
        except RuntimeError:                                   # 窗口已销毁 (进程收尾信号晚到)
            print("[aoi-console]", s)

    # ══════════════════════ 取帧 / 链路 ══════════════════════
    def _grab(self):
        if self.chk_freeze.isChecked() and self._last_rgb is not None:
            return self._last_rgb, f"冻结/{self._last_tag}", None
        if self.cmb_src.currentIndex() == 3:                        # 🏭 OPT: **绝不自动真拍**
            if self._opt_rgb is not None:
                return self._opt_rgb, self._opt_tag, None
            return None, "🏭 OPT: 点『📸 拍帧』(真拍) 或『🖼 最近图』(不拍)", None
        if self.cmb_src.currentIndex() == 1:
            try:
                import yolo_input_viewer as yiv
                fr = yiv._engine_live_frame(2.0)
                if fr is not None:
                    return fr, "🧪 引擎帧", 0.0
                return None, "🧪 引擎未出帧 (先开『输入图像』)", None
            except Exception as e:                                 # noqa: BLE001
                return None, f"🧪 仿真取帧失败 {type(e).__name__}", None
        if self.cmb_src.currentIndex() == 2:
            return None, "🖼 文件模式: 点『📂 载入』", None
        for name in REAL_CANDS:
            p = os.path.join(SHARED, name)
            if not os.path.isfile(p):
                continue
            age = time.time() - os.path.getmtime(p)
            if age < 0:
                return None, f"🎥 {name} 帧龄异常 → 拒用", None
            if age > 5.0:
                return None, f"🎥 {name} 旧帧 {age:.0f}s → 拒用", age
            try:
                import yolo_input_viewer as yiv
                return yiv.rgb_from_file(p), f"🎥 {name}", age
            except Exception:                                      # noqa: BLE001
                continue
        return None, "🎥 无实时帧 (开『输入图像』拉流)", None

    def _pick_file(self):
        p, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "载入帧 / 视频", ROOT, "图像/视频 (*.png *.jpg *.jpeg *.bmp *.mp4 *.avi *.mov)")
        if p:
            self.load_frame_file(p)

    def load_frame_file(self, path: str):
        """载入单帧文件 / 视频首帧 (测试与离线复看同源)。"""
        if path.lower().endswith((".mp4", ".avi", ".mov", ".mkv")):
            import cv2
            cap = cv2.VideoCapture(path); ok, fr = cap.read(); cap.release()
            if not ok:
                self.log(f"⚠️ 视频读不出首帧: {path}")
                return False
            self.cmb_src.setCurrentIndex(2)
            self._set_frame(cv2.cvtColor(fr, cv2.COLOR_BGR2RGB), f"🖼 {os.path.basename(path)}")
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
        self._set_frame(rgb, f"🖼 {os.path.basename(path)}")
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
            self._elide(self.lbl_chain, "链路 ✅ " + tag + (f" {age:.1f}s" if age is not None else ""),
                        f"帧源: {tag} · 帧龄 {age}")
        else:
            self._elide(self.lbl_chain, "链路 ⚠️ " + tag, tag)

    def _on_src_change(self, idx):
        self.source = "sim" if idx == 1 else "real"
        self._tick()

    # ══════════════════════ 技能 ══════════════════════
    # ── 🏭 工控机 OPT 相机 ──
    def _opt_fetch(self, grab: bool):
        """从工控机取 OPT 相机图 → 任务头识别 → 显示/判决/可标定。grab=True 会真拍一张。"""
        cam = 1 if self.cmb_cam.currentIndex() == 0 else 2
        via = "orin" if self.cmb_via.currentIndex() == 1 else "local"
        c = optc.CAMERAS[cam]
        if grab:
            r = optc.capture_detect(cam, via=via)
            self.log(f"📸 {c['name']} 相机真拍: HTTP {r.get('http')} {r.get('ms')}ms via {r.get('via')} "
                     f"→ {r.get('resp')}")
        rgb, meta = optc.fetch_frame(cam, kind="topview", grab=grab, via=via)
        if rgb is None:
            self.log(f"❌ 取图失败: {meta.get('err')} (相机 {c['name']} SN {c['sn']})")
            self._elide(self.lbl_chain, "链路 ❌ " + str(meta.get("err"))[:60], str(meta))
            return
        self._opt_rgb = rgb
        self._opt_meta = meta
        self._opt_tag = f"🏭 {c['name']} {meta['kind']} {meta['shape'][1]}x{meta['shape'][0]}"
        self.cmb_src.setCurrentIndex(3)
        self._set_frame(rgb, self._opt_tag)
        self.wid.set_classes([CLASS_CN.get(x, x) for x in self._cls_names()])
        res = self.run_skill(self._cur_skill, quiet=True)
        self._elide(self.lbl_chain, f"链路 ✅ {c['name']} {meta['shape'][1]}x{meta['shape'][0]} "
                                    f"{meta['ms']:.0f}ms via {meta['via']}", json.dumps(meta, ensure_ascii=False))
        self.log(f"🏭 {c['name']}相机图: {meta['shape']} 灰度均值 {meta['mean_gray']} · HTTP {meta['http']} "
                 f"· {meta['ms']:.0f}ms · {meta['bytes']//1024}KB · via {meta['via']}"
                 + (f" → 任务头: 定位 {len(res['loc'])} 缺陷 {len(res['defects'])}" if res else ""))

    def _opt_verdict(self):
        """读工控机自家模型判决 (只读) → 追加到判决表 (source=opt-工控机), 与任务头同表对照。"""
        cam = 1 if self.cmb_cam.currentIndex() == 0 else 2
        via = "orin" if self.cmb_via.currentIndex() == 1 else "local"
        lr = optc.last_result(cam, via=via)
        self._opt_lastres = lr
        self.log(f"📋 工控机判决: {json.dumps(lr, ensure_ascii=False)[:260]}")
        if self._last_res:
            self._fill_verdict(self._last_res)

    def run_skill(self, roi_key: str, quiet: bool = False):
        self._cur_skill = roi_key
        if self._last_rgb is None:
            if not quiet:
                self.log("⚠️ 还没有帧 (等取帧 / 切仿真 / 📂载入)")
            return None
        roi = ROI_SKILLS[roi_key][1]
        res = self.head.inspect(self._last_rgb, roi=roi, zoom=self.sp_zoom.value())
        self._last_res = res
        self._fill_verdict(res)
        for d in res["defects"]:
            if d["box"]:
                self.wid.add_box_px(d["box"], cls=CLASS_CN.get(d["cls"], d["cls"]))
        self.lbl_time.setText(f"⚡{res['elapsed_ms']:.0f}ms")
        rm = res["roi_meta"]
        self._elide(self.lbl_roi, f"ROI {res['roi_skill'] or '全帧'} ×{rm.get('zoom', 1):.2f} {rm.get('box')}",
                    f"ROI 框 {rm.get('box')} · 拉伸 ×{rm.get('zoom')} · 输出 {rm.get('out')}")
        if not quiet:
            self.log(f"▶ {ROI_SKILLS[roi_key][0]}: 定位 {len(res['loc'])} 缺陷 {len(res['defects'])} "
                     f"{res['elapsed_ms']:.0f}ms 判决 {'PASS' if res['verdict']['pass'] else 'FAIL'}")
        return res

    def _fill_verdict(self, res):
        v = res["verdict"]
        rows = list(v["items"])
        # 🏭 工控机自家模型判决同表对照 (只读 /last_result; 与本任务头两路并列, 来源可辨)
        lr = self._opt_lastres or {}
        if lr.get("code") == 200:
            rows.append({"target_id": "OPT-工控机",
                         "target": f"工控机模型({lr.get('detect_type', 'gf')})",
                         "defect": f"count={lr.get('count')} verdict={lr.get('verdict', '-')}",
                         "value": lr.get("count"), "threshold": "count=0",
                         "pass": lr.get("count") == 0, "source": "opt-工控机"})
        self.tbl_verdict.setRowCount(len(rows))
        for i, it in enumerate(rows):
            cells = [it.get("target_id", "-"), f'{it.get("target", "")} {it.get("defect", "")}',
                     str(it.get("value")), str(it.get("threshold")),
                     "PASS" if it.get("pass") else "FAIL"]
            for j, c in enumerate(cells):
                item = QtWidgets.QTableWidgetItem(str(c))
                if j == 4:
                    item.setForeground(QtGui.QColor(GREEN if it.get("pass") else RED))
                elif it.get("source") == "model":
                    item.setForeground(QtGui.QColor(ORANGE))
                item.setToolTip(f'来源={it.get("source")} · {it.get("target", "")} · {it.get("defect", "")}')
                self.tbl_verdict.setItem(i, j, item)
        # 列宽: 判据列自适应, 其余内容自适应; 末列拉满
        hh = self.tbl_verdict.horizontalHeader()
        hh.setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
        hh.setStretchLastSection(True)
        ok = v["pass"]
        self.lbl_verdict.setText(("✅ 全项通过" if ok else "❌ 存在不合格项")
                                 + f"  ({sum(1 for r in rows if r.get('pass'))}/{len(rows)})")
        self.lbl_verdict.setStyleSheet(f"color:{GREEN if ok else RED};font-weight:bold")
        self.lbl_state.setText(("判决 ✅ PASS" if ok else "判决 ❌ FAIL"))
        self.lbl_state.setStyleSheet(f"color:{GREEN if ok else RED};font-weight:bold")
        self.tbl_loc.setRowCount(len(res["loc"]))
        for i, l in enumerate(res["loc"]):
            for j, c in enumerate([f'{l["cn"]}', str(l["conf"]), ",".join(f"{v:.0f}" for v in l["box"])]):
                self.tbl_loc.setItem(i, j, QtWidgets.QTableWidgetItem(c))
        self.tbl_loc.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
        self.tbl_loc.horizontalHeader().setStretchLastSection(True)
        self.tbl_def.setRowCount(len(res["defects"]))
        for i, d in enumerate(res["defects"]):
            for j, c in enumerate([d["cn"], d["target"], str(d["conf"]),
                                   ",".join(f"{v:.0f}" for v in d["box"])]):
                self.tbl_def.setItem(i, j, QtWidgets.QTableWidgetItem(c))
        self.tbl_def.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
        self.tbl_def.horizontalHeader().setStretchLastSection(True)
        self._elide(self.lbl_defects, f"缺陷 {v['n_defects']} 个" +
                    (" · " + " ".join(d["cn"] for d in res["defects"]) if res["defects"] else ""),
                    " / ".join(f'{d["cn"]} conf={d["conf"]} {d["box"]}' for d in res["defects"]) or "无检出")

    def _goto_defect(self, row, _col):
        """双击缺陷行 → 冻结 + 该缺陷框加入标定 (新缺陷马上标定)。"""
        if not self._last_res or row >= len(self._last_res["defects"]):
            return
        d = self._last_res["defects"][row]
        self.chk_freeze.setChecked(True)
        self.chk_label.setChecked(True)
        self._select_class_in_combo(d["cls"])
        self.wid.add_box_px(d["box"], cls=CLASS_CN.get(d["cls"], d["cls"]))
        self.tabs.setCurrentIndex(2)
        self.log(f"🎯 缺陷框已加入标定 ({CLASS_CN.get(d['cls'], d['cls'])}); 确认后 💾保存")

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
            self.cmb_cls.addItem(f"{CLASS_CN.get(c, c)}", c)
        self.wid.set_classes([CLASS_CN.get(c, c) for c in names])
        try:
            n = len(list(yad.iter_samples(self.head.root)))
            self._elide(self.lbl_data, f"样本 {n} · 类别 {len(names)} · {os.path.basename(self.head.root)}"
                                       f" · 权重 {os.path.basename(self.head.weights) if self.head.weights else '无(启发式)'}",
                        f"数据根 {self.head.root}\n类别: {names}")
        except Exception:                                          # noqa: BLE001
            pass

    def _init_data_root(self):
        try:
            yad.ensure_layout(self.head.root, classes=self._cls_names())
        except Exception as e:                                     # noqa: BLE001
            self.log(f"⚠️ 数据根初始化失败: {type(e).__name__}: {e}")

    def _on_label_toggle(self, on):
        self.wid.set_editable(bool(on))
        self.log("✏️ 标定模式开 (拖框/缩放, 存原始帧坐标)" if on else "✏️ 标定模式关")

    def _add_class(self):
        name, ok = QtWidgets.QInputDialog.getText(self, "新类别", "类名 (英文, 作为 class id):")
        if not ok or not name.strip():
            return
        name = name.strip().replace(" ", "_")
        try:
            cid = yad.add_class(self.head.root, name)
            self._sync_classes()
            self.log(f"＋类别 {name} id={cid} → {self.head.classes_path()} (改 schema 需重启任务头生效)")
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
            yad.save_sample(self.head.root, self._last_rgb, boxes, **kw)
            self.log(f"💾 已存 {len(boxes)} 框")
        except Exception as e:                                     # noqa: BLE001
            self.log(f"❌ 保存失败: {type(e).__name__}: {e}")
            return
        self.wid.clear_boxes()
        self._sync_classes()
        if next_frame:
            self.chk_freeze.setChecked(False)

    def _set_selected_class(self):
        self.wid.set_selected_class(self.cmb_cls.currentText())
        self.log(f"🏷 选中框 → {self.cmb_cls.currentText()}")

    # ══════════════════════ 数据 / 训练 ══════════════════════
    def _build_dataset(self):
        try:
            yad.build_dataset(self.head.root)
            self.log("📦 数据集已构建 (" + os.path.join(self.head.root, "dataset") + ")")
            self._sync_classes()
        except Exception as e:                                     # noqa: BLE001
            self.log(f"❌ 构建失败: {type(e).__name__}: {e}")

    def _check_dataset(self):
        st = self.head.stats()
        self.log(f"🔍 体检: 图 {st.get('n_images')} 框 {st.get('n_boxes')} "
                 f"错 {len(st.get('errors', []))} 警 {len(st.get('warnings', []))}")
        for e in st.get("errors", [])[:5]:
            self.log(f"   ❌ {e}")

    def _train(self):
        if self._train_proc is not None:
            self.log("⚠️ 已有训练在跑")
            return
        ds = os.path.join(self.head.root, "dataset")
        if not os.path.isfile(os.path.join(ds, "data.yaml")):
            self.log("⚠️ 无数据集 → 先 📦构建")
            return
        base = self.head.weights if self.head.model_ready else "auto"
        name = "aoi_" + time.strftime("%m%d_%H%M")
        cmd = [PY, TRAIN_PY, "--data", ds, "--root", self.head.root, "--base", base,
               "--epochs", str(self.sp_epochs.value()), "--name", name, "--project", "outputs/yolo_aoi"]
        self.log(f"🚀 训练: {' '.join(cmd)}")
        self.tabs.setCurrentIndex(2)
        self._train_proc = QtCore.QProcess(self)
        self._train_proc.setWorkingDirectory(ROOT)
        _p = self._train_proc                              # 信号里别引用 self._train_proc (对象会先删)
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
        self.log(f"🏁 训练退出 code={code}")
        w = os.path.join(ROOT, "runs", "detect", "outputs", "yolo_aoi", name, "weights", "best.pt")
        if os.path.isfile(w):
            self._last_best = w
            self.log(f"✅ best.pt → {w} (精度确认后点 ⬆切在役)")
        else:
            self._last_best = ""
            self.log("⚠️ 无 best.pt (训练失败, 看上面日志)")

    def _switch_live(self):
        w = self._last_best
        if not w or not os.path.isfile(w):
            self.log("⚠️ 没有可切权重 (先训练出 best.pt)")
            return
        link = os.path.join(ROOT, "models", "yolo_aoi_live.pt")
        try:
            old = os.path.realpath(link) if os.path.islink(link) else ""
            with open(os.path.join(ROOT, "models", "yolo_aoi_live.prev.txt"), "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%F %T')} old={old} new={w}\n")
            if os.path.islink(link) or os.path.isfile(link):
                os.remove(link)
            os.symlink(w, link)
            self.log(f"⬆ 已切在役 → {os.path.basename(os.path.dirname(os.path.dirname(w)))} (旧链留档)")
        except Exception as e:                                     # noqa: BLE001
            self.log(f"❌ 切在役失败: {type(e).__name__}: {e}")

    def _open_datadir(self):
        try:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(self.head.root))
        except Exception:                                          # noqa: BLE001
            self.log(f"数据根 {self.head.root}")

    # ══════════════════════ 导出 / 收口 ══════════════════════
    def _export_json(self):
        if not self._last_res:
            self.log("⚠️ 无结果")
            return
        p = os.path.join(ROOT, "reports", f"aoi_inspect_{time.strftime('%Y%m%d_%H%M%S')}.json")
        json.dump(self._last_res, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        self.log(f"📄 {p}")

    def _export_csv(self):
        if not self._last_res:
            self.log("⚠️ 无结果")
            return
        p = os.path.join(ROOT, "reports", f"aoi_inspect_{time.strftime('%Y%m%d_%H%M%S')}.csv")
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["target_id", "target", "defect", "value", "threshold", "pass", "source"])
            for it in self._last_res["verdict"]["items"]:
                w.writerow([it.get("target_id"), it.get("target"), it.get("defect"), it.get("value"),
                            it.get("threshold"), it.get("pass"), it.get("source")])
        self.log(f"📥 {p}")

    def closeEvent(self, ev):                                      # noqa: N802
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
