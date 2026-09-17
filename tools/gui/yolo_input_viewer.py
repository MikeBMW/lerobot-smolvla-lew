#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""yolo_input_viewer.py — 「打开输入图像」实时视频流窗口 + **标定 (画框标注)** (节点右键菜单入口)

老倪 2026-09-17: 「yolo 目标检测节点, 增加右键打开输入图像的功能, 右键打开就能实时看到我
当前接入的输入原始视频流, 我要看到现在是否能看到 realsense 的相机图像」
+ 「4060 上的视频流窗口要从本地 docker 的 ros2 节点获取图像; orin 上传的视频流, 在 ROS2 srv
节点做视频压缩处理」
+ 「相机总是翻转, 所以要同时显示两个窗口: 一个原始, 一个旋转180度」
+ 「现在要采集真机图片训练 YOLO。增加标定功能: 标定工程师根据图像圈选光模块、输入类别、保存当前图片,
   而且 YOLO 模型可以通过保存的图片进行模型训练」(→ 见 yolo_label_widget.py / yolo_annot_dataset.py)

输入源 (同一窗口切换, 显示**原始**帧):
  ① 🎥 真机 RealSense (Orin → ROS2 srv → 4060 Docker → 本地文件):
     链路 = `tools/orin_frame_srv.py` (Orin, UVC 取帧 + **JPEG 压缩在服务端**, 服务 /zmax/live_frame)
           → `tools/ss_frame_srv_client.py` (本机 Docker, srv 客户端, 落 live_frame.jpg + .json)
           → 本窗口轮询该文件显示 (GUI 无需 rclpy)。
  ② 🧪 仿真渲染 (metaworld corner2) ③ 📁 回放目录 — 口径对照/离线核对。

显示: 左 = 原始 (0°) / 右 = 旋转 (默认 180°, 可选 90/270) —— 相机翻转时并排对照 (同一帧, 只是观察方向)。
标定: 「✏️ 标定模式」 → 画面冻结可拖框 → 选/输入类别 → 💾 保存标注 (图片 + YOLO 标签落
      data/yolo_annot/sessions/<会话>/, 流水记 annotations.jsonl) → 📦 构建数据集 → 🚀 训练 YOLO。
      **框永远存"原始帧像素坐标"**: 在旋转窗上圈选也会自动换算回来 (避免镜像标签污染训练数据)。
纪律: 只显示原始帧 (不画框); 勾「叠加 YOLO 框」才跑检测 (默认关, 保持"原始视频流"语义)。
新鲜度: meta.age_s 超阈值即显示 "⚠️ 无新帧", 绝不拿旧图冒充实时 (老倪红线)。
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.dirname(_HERE)):                 # tools/gui + tools
    if _p not in sys.path:
        sys.path.insert(0, _p)

from yolo_label_widget import YoloLabelWidget             # noqa: E402
import yolo_annot_dataset as yad                          # noqa: E402

ORIN = os.environ.get("ZMAX_ORIN_HOST", "tashan@192.168.23.66")
CONTAINER = os.environ.get("ZMAX_TAP_CONTAINER", "ss-remote-tap")
SHARED = os.environ.get("ZMAX_SS_REMOTE_DIR", "/home/ubuntu/zmax_ss_remote")
LIVE_JPG = os.path.join(SHARED, "live_frame.jpg")
LIVE_META = os.path.join(SHARED, "live_frame.json")
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ANNOT_ROOT = os.environ.get("ZMAX_ANNOT_ROOT", yad.ROOT_DEFAULT)
_SSH = ["ssh", "-o", "ConnectTimeout=6", "-o", "StrictHostKeyChecking=no", ORIN]

_CSS = ("QDialog{background:#0d1117;} QLabel{color:#e6edf3;font-size:12px;}"
        "QLabel#img{background:#161b22;border:1px solid #30363d;}"
        "QLabel#ph{color:#8b949e;font-size:11px;padding:1px 2px;}"
        "QLabel#st{background:#161b22;border:1px solid #30363d;padding:6px;}"
        "QPushButton{background:#21262d;color:#e6edf3;border:1px solid #30363d;padding:5px 10px;border-radius:4px;}"
        "QPushButton:hover{background:#30363d;} QCheckBox{color:#e6edf3;} QComboBox{background:#161b22;color:#e6edf3;}"
        "QLineEdit{background:#161b22;color:#e6edf3;border:1px solid #30363d;padding:3px;}")


def _run(cmd, timeout=15, shell=False):
    try:
        r = subprocess.run(cmd, shell=shell, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception as e:                                                 # noqa: BLE001
        return -1, f"{type(e).__name__}: {e}"


def rgb_from_file(path):
    """读图 → RGB uint8 (cv2 优先; 无 cv2 用 Qt 解码)"""
    try:
        import cv2
        bgr = cv2.imread(path)
        if bgr is not None:
            return np.ascontiguousarray(bgr[:, :, ::-1])
    except Exception:                                                      # noqa: BLE001
        pass
    pm = QtGui.QPixmap(path)
    if pm.isNull():
        return None
    return qimage_to_rgb(pm.toImage())


def qimage_to_rgb(qimg: QtGui.QImage):
    """QImage → RGB uint8 (处理 bytesPerLine 对齐填充, 避免条纹错位)"""
    qimg = qimg.convertToFormat(QtGui.QImage.Format_RGB888)
    w, h = qimg.width(), qimg.height()
    ptr = qimg.constBits()
    ptr.setsize(qimg.byteCount())
    arr = np.frombuffer(bytes(ptr), np.uint8).reshape(h, qimg.bytesPerLine())[:, :3 * w]
    return np.ascontiguousarray(arr.reshape(h, w, 3))


class _RemoteChain:
    """真机链路编排: 确保 Orin srv 节点 + 本地 Docker 客户端在跑 (幂等)"""

    LOG: list = []

    @classmethod
    def _log(cls, s):
        cls.LOG.append(f"[{time.strftime('%H:%M:%S')}] {s}")
        cls.LOG[:] = cls.LOG[-200:]

    @classmethod
    def ensure(cls) -> str:
        msgs = []
        # ① Orin 侧 srv 节点 (临时进程, 自带单实例守卫 + 无调用自动退出)
        rc, out = _run(_SSH + ["bash /home/tashan/zmax_yolo/tools/start_frame_srv.sh"], timeout=45)
        tail = [l for l in out.strip().splitlines() if l.strip()][-3:]
        msgs.append(("Orin srv", rc, " | ".join(tail)))
        cls._log(f"Orin srv 启动 rc={rc}: {' | '.join(tail)}")
        # ② 本机 Docker 客户端 (复用常驻 tap 容器, 已有 /repo:ro 与 /out 挂载)
        rc2, out2 = _run(["sudo", "docker", "exec", CONTAINER, "pgrep", "-f", "ss_frame_srv_[c]lient"],
                         timeout=10)
        if rc2 == 0 and out2.strip():
            msgs.append(("Docker 客户端", 0, f"已在跑 pid={out2.strip().split()[0]}"))
            cls._log("Docker 客户端已在跑")
        else:
            cmd = ("source /opt/ros/humble/setup.bash; source /repo/tools/ros2_interfaces/install/setup.bash; "
                   "setsid nohup python3 /repo/tools/ss_frame_srv_client.py --out /out --rate 10 "
                   "</dev/null >/tmp/frame_srv_client.log 2>&1 & echo started")
            rc3, out3 = _run(["sudo", "docker", "exec", "-d", CONTAINER, "bash", "-lc", cmd], timeout=20)
            cls._log(f"Docker 客户端启动 rc={rc3}: {out3.strip()[:120]}")
            msgs.append(("Docker 客户端", rc3, out3.strip()[:80]))
        return " · ".join(f"{n}: {'OK' if r == 0 else 'rc=' + str(r) + ' ' + d}" for n, r, d in msgs)

    @classmethod
    def stop(cls):
        rc, out = _run(["sudo", "docker", "exec", CONTAINER, "pkill", "-f", "ss_frame_srv_[c]lient"],
                       timeout=10)
        cls._log(f"Docker 客户端停止 rc={rc} {out.strip()[:60]}")
        rc2, out2 = _run(_SSH + ["pkill -f 'orin_frame_[s]rv'"], timeout=10)
        cls._log(f"Orin srv 停止 rc={rc2} {out2.strip()[:60]}")


class _SimGrabber(threading.Thread):
    """仿真渲染取帧 (worker 线程: 只做 mujoco render, 不碰 Qt)"""

    def __init__(self, out_q: queue.Queue, yolo_overlay: bool):
        super().__init__(daemon=True)
        self.q = out_q
        self.overlay = yolo_overlay
        self.stop_flag = False

    def run(self):
        try:
            sys.path.insert(0, os.path.join(REPO, "tools", "gui"))
            import node_logic as nl
        except Exception as e:                                             # noqa: BLE001
            self.q.put({"err": f"node_logic 加载失败: {e}"})
            return
        while not self.stop_flag:
            t0 = time.time()
            try:
                al = nl._yolo_ensure_aligner(None)
                img = al.env.render()          # RGB 原始渲染帧 (与引擎同源)
                info = {"src": "sim:metaworld corner2", "shape": f"{img.shape[1]}x{img.shape[0]}",
                        "device": "mujoco 渲染 (非真机相机)"}
                if self.overlay:
                    try:                       # 可选: 同时跑检测, 证明模型看到的就是这帧
                        _bgr = img[:, :, ::-1].copy()
                        res = al.model.predict(_bgr, conf=0.4, verbose=False)[0]
                        _plotted = res.plot()
                        img = _plotted[:, :, ::-1] if _plotted is not None else img
                        info["yolo"] = f"{len(res.boxes)} 框"
                    except Exception as e:                                     # noqa: BLE001
                        info["yolo"] = f"检测失败 {type(e).__name__}"
                self.q.put({"rgb": np.ascontiguousarray(img), "info": info})
            except Exception as e:                                         # noqa: BLE001
                self.q.put({"err": f"仿真取帧失败: {type(e).__name__}: {e}"})
                time.sleep(0.5)
            dt = 0.08 - (time.time() - t0)
            if dt > 0:
                time.sleep(dt)


class YoloInputViewer(QtWidgets.QDialog):
    """实时输入图像窗口 (非模态, 可与其后窗口复用) + 标定"""

    _instances: list = []

    def __init__(self, parent=None, module=None, source: str = "real"):
        super().__init__(parent, QtCore.Qt.Window)
        self.setWindowTitle("📺 输入图像 · 实时视频流 + 标定 (YOLO 目标检测 节点)")
        self.setStyleSheet(_CSS)
        self.setWindowFlag(QtCore.Qt.WindowMinimizeButtonHint, True)
        self.setWindowFlag(QtCore.Qt.WindowMaximizeButtonHint, True)
        self.module = module
        self.source = source
        self._q: queue.Queue = queue.Queue(maxsize=6)
        self._sim: _SimGrabber | None = None
        self._last_sig = None
        self._sim_fps_t, self._sim_fps_n = time.time(), 0
        self._sim_fps = 0.0
        self._rgb = None                      # 当前显示帧 (原始朝向 RGB)
        self._frozen = False                  # 冻结 (标定用): 不再跟随实时帧
        self._pending = None                  # 冻结期间攒下的最新帧
        self._frame_meta = {}                 # 当前帧来源 (device/seq/age/src)
        self._session = yad.session_name("d405")
        self._n_saved = 0
        self._syncing = False

        P = yad.ensure_layout(ANNOT_ROOT)
        self.annot_root = P["root"]

        # ── 第 1 行: 输入源 / 显示 ──
        v = QtWidgets.QVBoxLayout(self)
        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel("输入源:"))
        self.cb = QtWidgets.QComboBox()
        self.cb.addItems(["🎥 真机 RealSense (Orin→ROS2 srv→Docker)", "🧪 仿真渲染 (metaworld corner2)"])
        self.cb.setCurrentIndex(0 if source == "real" else 1)
        self.cb.currentIndexChanged.connect(self._switch)
        top.addWidget(self.cb, 1)
        self.chk = QtWidgets.QCheckBox("叠加 YOLO 框")
        self.chk.setChecked(False)
        self.chk.setToolTip("默认关 = 纯原始视频流; 打开则同时跑 detect_3d 并画框 (证明模型看到的是这帧)")
        top.addWidget(self.chk)
        self.chk_rot = QtWidgets.QCheckBox("🔄 并排旋转窗")
        self.chk_rot.setChecked(True)
        self.chk_rot.setToolTip("相机翻转安装时, 右侧同时显示旋转后的画面, 与左侧原始帧并排对照 "
                                "(同一帧源, 只是观察方向不同)")
        self.chk_rot.toggled.connect(self._apply_rot_vis)
        top.addWidget(self.chk_rot)
        self.cb_rot = QtWidgets.QComboBox()
        self.cb_rot.addItems(["180°", "90°", "270°"])
        self.cb_rot.setToolTip("旋转角度 (默认 180° = 相机上下颠倒安装)")
        self.cb_rot.currentIndexChanged.connect(lambda _i: self._apply_rot_vis())
        top.addWidget(self.cb_rot)
        self.btn = QtWidgets.QPushButton("⏹ 停止链路")
        self.btn.clicked.connect(self._toggle_chain)
        top.addWidget(self.btn)
        v.addLayout(top)

        # ── 第 2 行: 标定 ──
        ann = QtWidgets.QHBoxLayout()
        self.chk_annot = QtWidgets.QCheckBox("✏️ 标定模式")
        self.chk_annot.setToolTip("冻结当前帧 → 在画面上拖框圈住光模块 → 选类别 → 💾 保存标注\n"
                                  "(框按**原始帧坐标**存档, 在旋转窗上圈选会自动换算回来)")
        self.chk_annot.toggled.connect(self._toggle_annot)
        ann.addWidget(self.chk_annot)
        # ⚠️ 勾选框**永远可见** (它是标定的唯一入口); 下面这些只在标定模式打开时出现
        self.lbl_cls = QtWidgets.QLabel("类别:")
        ann.addWidget(self.lbl_cls)
        self.cb_cls = QtWidgets.QComboBox()
        self.cb_cls.setEditable(True)
        self.cb_cls.setMinimumWidth(150)
        self.cb_cls.setToolTip("目标类别 (可手输新类别名, 会追加进 classes.txt)")
        self.cb_cls.currentTextChanged.connect(self._on_cls_changed)
        ann.addWidget(self.cb_cls)
        self.btn_newcls = QtWidgets.QPushButton("＋新类别")
        self.btn_newcls.clicked.connect(self._add_class_dialog)
        ann.addWidget(self.btn_newcls)
        for txt, fn, tip in (("💾 保存标注", self._save_annot, "保存当前图片 + 框 (Enter)"),
                             ("⏭ 保存并下一帧", self._save_next, "保存后自动取下一帧继续标 (N)"),
                             ("🏷 改选中类别", self._relabel_selected, "把选中的框改成当前类别"),
                             ("↩ 撤销", lambda: self.w_orig.undo(), "撤销上一次改动 (Ctrl+Z)"),
                             ("🗑 删选中", lambda: self.w_orig.remove_selected(), "删除选中框 (Del)"),
                             ("✖ 清空框", lambda: self.w_orig.clear_boxes(), "清空本帧所有框"),
                             ("🧊 冻结/▶实时", self._toggle_freeze, "冻结当前帧 / 恢复跟随实时 (F)")):
            b = QtWidgets.QPushButton(txt)
            b.clicked.connect(fn)
            b.setToolTip(tip)
            ann.addWidget(b)
        ann.addWidget(QtWidgets.QLabel("标定员:"))
        self.ed_who = QtWidgets.QLineEdit(os.environ.get("USER", "engineer"))
        self.ed_who.setMaximumWidth(90)
        ann.addWidget(self.ed_who)
        self.lbl_annot_hint = QtWidgets.QLabel("")     # 常显提示 (自解释: 下一步该点哪)
        self.lbl_annot_hint.setObjectName("ph")
        self.lbl_annot_hint.setWordWrap(True)
        _sp = self.lbl_annot_hint.sizePolicy()
        _sp.setHorizontalPolicy(QtWidgets.QSizePolicy.Ignored)   # 长提示不许顶宽窗口 (实测: 窗口被撑到 2436px 出屏)
        self.lbl_annot_hint.setSizePolicy(_sp)
        ann.addWidget(self.lbl_annot_hint, 1)
        ann.addStretch(1)
        v.addLayout(ann)

        # ── 第 3 行: 数据 / 训练 ──
        drow = QtWidgets.QHBoxLayout()
        for txt, fn, tip in (("📦 构建数据集", self._build_dataset, "sessions → dataset/{images,labels}/{train,val} + data.yaml"),
                             ("🔍 数据体检", self._check_dataset, "标签格式/类别范围/配对/重复图 全检"),
                             ("🚀 训练 YOLO", self._train_dialog, "用标定好的数据微调 YOLO (后台跑, 给日志路径)"),
                             ("📂 数据目录", self._open_dir, "在文件管理器打开标定数据根目录")):
            b = QtWidgets.QPushButton(txt)
            b.clicked.connect(fn)
            b.setToolTip(tip)
            drow.addWidget(b)
        drow.addStretch(1)
        self.lbl_data = QtWidgets.QLabel("")
        self.lbl_data.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.lbl_data.setWordWrap(True)                          # 长路径/类别列表同理, 别撑宽
        _sp2 = self.lbl_data.sizePolicy()
        _sp2.setHorizontalPolicy(QtWidgets.QSizePolicy.Ignored)
        self.lbl_data.setSizePolicy(_sp2)
        drow.addWidget(self.lbl_data, 2)
        v.addLayout(drow)

        # ── 两个子窗口: 左 = 原始 (0°) / 右 = 旋转 (相机翻转) ──
        panes = QtWidgets.QHBoxLayout()
        self.w_orig = YoloLabelWidget(rot_deg=0, editable=False)
        self.w_rot = YoloLabelWidget(rot_deg=180, editable=False)
        self.w_rot.setVisible(False)
        self.w_orig.changed.connect(lambda: self._sync_boxes(self.w_orig, self.w_rot))
        self.w_rot.changed.connect(lambda: self._sync_boxes(self.w_rot, self.w_orig))
        self.w_orig.cursorMoved.connect(lambda *_a: None)
        self.img, self.img_rot = self.w_orig, self.w_rot       # 兼容旧调用/取证
        pane_titles = {0: "🖼 原始 (0°)", 1: "🔄 旋转 180° (相机翻转)"}
        self._pane_head = {}
        for key, wdg in (("orig", self.w_orig), ("rot", self.w_rot)):
            col = QtWidgets.QVBoxLayout()
            head = QtWidgets.QLabel(pane_titles[0] if key == "orig" else pane_titles[1].replace("180°", f"{wdg.rot_deg}°"))
            head.setObjectName("ph")
            col.addWidget(head)
            col.addWidget(wdg, 1)
            self._pane_head[key] = head
            panes.addLayout(col, 1)
        self._pane_img = {"orig": self.w_orig, "rot": self.w_rot}
        v.addLayout(panes, 1)
        self._apply_rot_vis()      # ⚠️ 必须显式调一次: chk_rot 在 connect 之前就 setChecked(True) 了,
                                   # 否则 toggled 不会触发 → 右窗永远隐藏 (构建期就隐藏了, 没人再显示它)

        self.st = QtWidgets.QLabel("—")
        self.st.setObjectName("st")
        self.st.setWordWrap(True)
        self.st.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        v.addWidget(self.st)

        self._reload_classes()
        # 快捷键 (Enter 保存 / N 保存并下一帧 / F 冻结) —— 输入框有焦点时不抢键 (见 _shortcut_guard)
        self._shortcuts = []
        for _key, _kind in ((QtCore.Qt.Key_Return, "save"), (QtCore.Qt.Key_Enter, "save"),
                            (QtCore.Qt.Key_N, "next"), (QtCore.Qt.Key_F, "freeze")):
            _sc = QtWidgets.QShortcut(QtGui.QKeySequence(_key), self)
            _sc.setContext(QtCore.Qt.WindowShortcut)
            _sc.activated.connect(self._shortcut_guard(_kind))
            self._shortcuts.append((_key, _kind, _sc))
        self._refresh_data_label()
        self._set_annot_visible(False)

        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(66)          # ~15Hz 刷新
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self._chain_state = ""
        self._chain_stopped = False      # 手动「⏹ 停止链路」后不自动重连
        self._recovering = False
        self._stale_since = None
        self._last_recover = time.time()  # 给首次拉起 20s 宽限, 别和启动线程抢
        self._last_show_ensure = time.time()
        self._closed = False
        QtCore.QTimer.singleShot(200, self._start_source)

    # ── 源管理 ──────────────────────────────────────────────────────────
    def _switch(self, _i):
        self._stop_source()
        self._start_source()

    def _start_source(self):
        if self.cb.currentIndex() == 0:
            self.source = "real"
            self._stale_since = None
            self._last_recover = time.time()
            self.btn.setEnabled(True)
            t = threading.Thread(target=self._ensure_chain_bg, daemon=True)
            t.start()
        else:
            self.source = "sim"
            self.btn.setEnabled(False)
            self._sim = _SimGrabber(self._q, self.chk.isChecked())
            self._sim.start()
            self._log_line("仿真源已启动 (metaworld corner2 原始渲染帧)")

    def _stop_source(self):
        if self._sim is not None:
            self._sim.stop_flag = True
            self._sim = None
        try:
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass

    def _ensure_chain_bg(self):
        s = _RemoteChain.ensure()
        self._chain_state = s
        self._log_line("链路: " + s)
        self._collect_if_closed()

    def _collect_if_closed(self):
        """⚠️ 竞态收口: ensure 是后台线程 (Orin 拉起 ~10s) —— 期间用户可能已关窗/点停止,
        若不管, ensure 会在关窗**之后**把 Docker 客户端拉起来 → 孤儿轮询进程 (实测踩过)。
        所以 ensure 返回后必须复查一次状态, 已关就立刻收口。"""
        if self._closed or self._chain_stopped:
            _RemoteChain.stop()
            self._log_line("窗口已关闭/已停止 → 收口: 停掉刚拉起的链路 (Orin 节点无调用自退)")

    def showEvent(self, ev):                                               # noqa: N802
        """窗口重新显示 (关窗复用) → 重新拉起链路; 30s 内不重复拉 (最小化/还原不折腾)"""
        super().showEvent(ev)
        self._clamp_to_screen()
        if self.source == "real" and not self._chain_stopped and time.time() - self._last_show_ensure > 30:
            self._last_show_ensure = time.time()
            self._stale_since = None
            self._last_recover = time.time()
            threading.Thread(target=self._ensure_chain_bg, daemon=True).start()

    def _clamp_to_screen(self, silent=True):
        """屏幕变了 (拔外接显示器/换分辨率) 就把窗口拉回可见范围 —— 实测: 拔屏后窗口 2436x797 落到 1920x1200 屏外,
        用户看到的现象就是"窗口跑到屏幕外面去了"。只在越界时才动 (不打断用户手动缩放)。"""
        try:
            scr = QtWidgets.QApplication.primaryScreen().availableGeometry()
            w = min(self.width(), max(700, scr.width() - 40))
            h = min(self.height(), max(460, scr.height() - 40))
            x = min(max(self.x(), scr.x()), scr.x() + max(0, scr.width() - w))
            y = min(max(self.y(), scr.y()), scr.y() + max(0, scr.height() - h))
            if (w, h, x, y) != (self.width(), self.height(), self.x(), self.y()):
                self.setGeometry(x, y, w, h)
                if not silent:
                    self._log_line(f"屏幕变化 → 窗口拉回屏内: ({x},{y}) {w}x{h} (屏 {scr.width()}x{scr.height()})")
                return True
        except Exception:                                                  # noqa: BLE001
            pass
        return False

    def _toggle_chain(self):
        if self._chain_stopped:                       # 已停 → 手动重连
            self._chain_stopped = False
            self.btn.setText("⏹ 停止链路")
            self._log_line("手动重连链路 …")
            threading.Thread(target=self._ensure_chain_bg, daemon=True).start()
            return
        self._chain_stopped = True
        self.btn.setText("▶ 重连链路")
        _RemoteChain.stop()
        self._log_line("已停止 Docker 客户端与 Orin srv 节点 (Orin 侧无调用也会自动退出)")

    def _maybe_recover(self):
        """断流自愈: Orin 节点 25s 无调用自退 / Docker 客户端被杀 → 自动重连 (节流 20s; 手动停止则不动)"""
        if self._chain_stopped or self._recovering:
            return
        now = time.time()
        if self._stale_since is None:
            self._stale_since = now
        if now - self._stale_since < 6.0 or now - self._last_recover < 20.0:
            return
        self._last_recover = now
        self._recovering = True
        self._log_line(f"⚠️ 无新帧 {now - self._stale_since:.0f}s → 自动重连链路 (Orin srv + Docker 客户端)")
        threading.Thread(target=self._recover_bg, daemon=True).start()

    def _recover_bg(self):
        try:
            s = _RemoteChain.ensure()
            self._chain_state = s
            _RemoteChain._log(f"自动重连完成: {s}")
            self._log_line("自动重连: " + s)
        except Exception as e:                                             # noqa: BLE001
            self._log_line(f"自动重连失败: {type(e).__name__}: {e}")
        finally:
            self._recovering = False
            self._collect_if_closed()

    def _log_line(self, s):
        if self.module is not None and hasattr(self.module, "_log"):
            try:
                self.module._log(f"📺 输入图像: {s}")
            except Exception:                                              # noqa: BLE001
                pass

    def _shortcut_guard(self, kind):
        """快捷键包装: 焦点在输入框 (QLineEdit / 可编辑 QComboBox) 时不触发, 免得打不出字"""
        def fn():
            fw = QtWidgets.QApplication.focusWidget()
            if isinstance(fw, QtWidgets.QLineEdit):
                return
            if isinstance(fw, QtWidgets.QComboBox) and fw.isEditable():
                return
            if kind == "save":
                self._save_annot()
            elif kind == "next":
                self._save_next()
            else:
                self._toggle_freeze()
        return fn

    # ── 显示 (原始 / 旋转 双窗) ──────────────────────────────────────────
    def _rot_deg(self) -> int:
        return {"180°": 180, "90°": 90, "270°": 270}.get(self.cb_rot.currentText(), 180)

    def _apply_rot_vis(self):
        """旋转开关/角度变化: 显隐右窗并按当前角度重画 (共用同一帧, 不产生第二路数据)"""
        on = self.chk_rot.isChecked()
        self.w_rot.set_rot_deg(self._rot_deg())
        for w in (self._pane_head["rot"], self.w_rot):
            w.setVisible(on)
        self._pane_head["rot"].setText(f"🔄 旋转 {self._rot_deg()}° (相机翻转)")
        if on:                                  # 右窗镜像左窗的框 (坐标同源, 都是原始帧坐标)
            self._sync_boxes(self.w_orig, self.w_rot, force=True)
        self._paint_frames()

    def _sync_boxes(self, src, dst, force=False):
        """两窗共享同一组框 (都存原始帧坐标 → 直接复制; 防止"旋转窗标的框看不见"的困惑)"""
        if self._syncing:
            return
        self._syncing = True
        try:
            if force or [(b["box"], b["cls"]) for b in dst.boxes()] != [(b["box"], b["cls"]) for b in src.boxes()]:
                dst.set_boxes(src.boxes_px())
                if src.selected() >= 0:
                    dst._sel = src.selected()
        finally:
            self._syncing = False

    def _paint_frames(self):
        """把当前帧同时推给两个子窗口 (各自按自己的 rot_deg 显示)"""
        if self._rgb is None:
            return
        self.w_orig.set_frame_rgb(self._rgb)
        if self.chk_rot.isChecked():
            self.w_rot.set_frame_rgb(self._rgb)
        self._pm = {"orig": self.w_orig.pixmap(),
                    "rot": self.w_rot.pixmap() if self.chk_rot.isChecked() else None}

    def _set_frames(self, pm_src):
        """兼容旧调用: 传 QPixmap → 转 RGB 后走 _paint_frames"""
        if pm_src is None or pm_src.isNull():
            return
        self._rgb = qimage_to_rgb(pm_src.toImage())
        self.w_orig.set_boxes(self.w_orig.boxes_px())
        self._paint_frames()

    # ── 刷新 ────────────────────────────────────────────────────────────
    def _tick(self):
        if time.time() - getattr(self, "_last_clamp", 0) > 5.0:      # 抜屏/换分辨率后 5s 内自动拉回
            self._last_clamp = time.time()
            self._clamp_to_screen(silent=False)
        if self.source == "real":
            self._tick_real()
        else:
            self._tick_sim()

    def _tick_real(self):
        meta = None
        if os.path.isfile(LIVE_META):
            try:
                meta = json.load(open(LIVE_META, encoding="utf-8"))
            except Exception:                                              # noqa: BLE001
                meta = None
        if not os.path.isfile(LIVE_JPG):
            self.st.setText("⚠️ 还没有帧文件 " + LIVE_JPG + "\n"
                            "   链路状态: " + (self._chain_state or "启动中…") +
                            "\n   (Orin 侧 srv 未起 / Docker 客户端未起 / D405 UVC 被占用 都可能)")
            self._maybe_recover()
            return
        try:
            st = os.stat(LIVE_JPG)
            sig = (int(st.st_mtime_ns), st.st_size)
            if sig != self._last_sig:
                self._last_sig = sig
                if not self._frozen:
                    rgb = rgb_from_file(LIVE_JPG)
                    if rgb is not None:
                        self._rgb = rgb
                        self._paint_frames()
                else:
                    self._pending_sig = sig
        except Exception:                                                  # noqa: BLE001
            pass
        if not meta:
            self.st.setText(f"⚠️ 有帧文件但缺 meta ({LIVE_META}) → 无法判定新鲜度")
            self._maybe_recover()
            return
        ok = bool(meta.get("ok"))
        age = meta.get("age_s")
        stale = bool(meta.get("stale")) or (age is not None and age > 5.0)
        head = "✅ 实时真机帧" if (ok and not stale) else ("⚠️ 无新帧 (显示的是最后一帧)" if ok else "❌ 链路无数据")
        if ok and not stale:
            self._stale_since = None                  # 有新鲜帧 → 复位自愈计时
        else:
            self._maybe_recover()
        self._frame_meta = {"device": meta.get("device"), "seq": meta.get("seq"), "age_s": age,
                            "src": meta.get("src"), "stale": stale, "ok": ok}
        self.st.setText(
            f"{head}{'  🧊 已冻结(标定中)' if self._frozen else ''}   ← 输入源: {meta.get('src')}   "
            f"({meta.get('w')}x{meta.get('h')})\n"
            f"设备: {meta.get('device')}\n"
            f"帧号 seq={meta.get('seq')} · 帧龄 age={age}s · JPEG { (meta.get('jpeg_bytes') or 0)/1024:.1f} KB "
            f"· 服务端压缩 {meta.get('encode_ms')} ms (q={meta.get('quality')}) · 服务端 {meta.get('server_fps')} Hz\n"
            f"双画面: 左=原始 (0°) · {('右=旋转 ' + str(self._rot_deg()) + '° (同一帧的 Qt 旋转, 观察用, 不改像素语义)') if self.chk_rot.isChecked() else '右窗已关 (勾「🔄 并排旋转窗」打开)'}\n"
            f"标定: 数据根 {self.annot_root} · 会话 {self._session} · 本窗已存 {self._n_saved} 张 · 当前帧框 {len(self.w_orig.boxes())} 个\n"
            f"服务端主机: {meta.get('server')} · 通道: Orin(取帧+JPEG) → ROS2 srv /zmax/live_frame → 本机 Docker → 本窗口\n"
            f"{'⚠️ ' + str(meta.get('reason')) if not ok else ''}")

    def _tick_sim(self):
        try:
            d = self._q.get_nowait()
        except queue.Empty:
            return
        if "err" in d:
            self.st.setText("⚠️ " + d["err"])
            return
        rgb = d["rgb"]
        h, w = rgb.shape[:2]
        if self._frozen:
            self._pending = rgb                    # 冻结: 攒着, 用户点「下一帧」再显示
        else:
            self._rgb = rgb
            self._paint_frames()
        self._sim_fps_n += 1
        if time.time() - self._sim_fps_t >= 1.0:
            self._sim_fps = self._sim_fps_n / (time.time() - self._sim_fps_t)
            self._sim_fps_n, self._sim_fps_t = 0, time.time()
        self._frame_meta = {"device": d["info"].get("device"), "src": d["info"].get("src"),
                            "seq": None, "age_s": 0.0, "ok": True, "stale": False}
        self.st.setText(f"🧪 仿真渲染帧 (metaworld corner2) · {w}x{h} · {self._sim_fps:.1f} FPS"
                        f"{'  🧊 已冻结(标定中)' if self._frozen else ''}\n"
                        f"设备: {d['info'].get('device')}\n"
                        f"双画面: 左=原始 (0°) · {('右=旋转 ' + str(self._rot_deg()) + '° (同一帧旋转)') if self.chk_rot.isChecked() else '右窗已关'}\n"
                        f"标定: 数据根 {self.annot_root} · 会话 {self._session} · 本窗已存 {self._n_saved} 张 · 当前帧框 {len(self.w_orig.boxes())} 个\n"
                        f"用途: 与真机帧做口径对照 (朝向 rot90 / 通道 / 内参 / 深度)")

    # ── 标定 ────────────────────────────────────────────────────────────
    _ANNOT_BTNS = ("💾 保存标注", "⏭ 保存并下一帧", "↩ 撤销", "🗑 删选中", "✖ 清空框",
                   "🧊 冻结/▶实时", "📦 构建数据集", "🔍 数据体检", "🚀 训练 YOLO", "🏷 改选中类别",
                   "📂 数据目录", "＋新类别")

    def _set_annot_visible(self, on):
        """⚠️ 血泪: 最初把「✏️ 标定模式」勾选框**自己也藏了** → 用户永远打不开标定, 界面上找不到任何标定按钮
        (我 offscreen 取证时是程序化 setChecked(True), 所以没暴露)。**入口控件必须常显** —— 隐的是它的下级控件。"""
        self.chk_annot.setVisible(True)
        for w in (self.lbl_cls, self.cb_cls, self.btn_newcls, self.ed_who, self.lbl_data):
            w.setVisible(on)
        for b in self.findChildren(QtWidgets.QPushButton):
            if b.text() in self._ANNOT_BTNS:
                b.setVisible(on)
        self.lbl_annot_hint.setVisible(True)
        self.lbl_annot_hint.setText(
            "标定工程: 勾左边的「✏️ 标定模式」→ 画面冻结 → 拖框圈住光模块 → 选/输类别 → 💾 保存标注" if not on
            else "拖框=圈目标 · 拖框内=移动 · 拖角=缩放 · 右键框内=删框 · Enter 保存 · N 下一帧 · Del 删选中 · Ctrl+Z 撤销")

    def _toggle_annot(self, on):
        self.chk_annot.setText("✏️ 标定模式 (开)" if on else "✏️ 标定模式")
        self._set_annot_visible(on)
        self.w_orig.set_editable(on)
        self.w_rot.set_editable(on)
        self.w_orig.set_classes(yad.load_classes(self.annot_root))
        self.w_rot.set_classes(yad.load_classes(self.annot_root))
        if on:
            self._frozen = True
            self.w_orig.setFocus()
            self._log_line(f"标定模式开: 已冻结当前帧; 数据根 {self.annot_root} · 会话 {self._session} "
                           f"· 类别 {yad.load_classes(self.annot_root)}")
        else:
            self._frozen = False
            self._log_line("标定模式关 (恢复跟随实时帧; 未保存的框已丢弃)")
            self.w_orig.clear_boxes()
            self.w_rot.clear_boxes()
        self._refresh_data_label()

    def _toggle_freeze(self):
        self._frozen = not self._frozen
        if not self._frozen:
            if self._pending is not None:
                self._rgb = self._pending
                self._pending = None
                self._paint_frames()
            self._log_line("恢复跟随实时帧")
        else:
            self._log_line("已冻结当前帧 (可安心画框)")

    def _next_frame(self):
        """取下一帧 (真机=最新 live_frame.jpg / 仿真=队列里最新的一帧), 保持冻结"""
        before = None if self._rgb is None else self._rgb.copy()
        if self.source == "sim":
            rgb = self._pending
            while True:
                try:
                    d = self._q.get_nowait()
                except queue.Empty:
                    break
                if "rgb" in d:
                    rgb = d["rgb"]
            if rgb is None:
                return False
            self._pending = None
            self._rgb = rgb
        else:
            rgb = rgb_from_file(LIVE_JPG) if os.path.isfile(LIVE_JPG) else None
            if rgb is None:
                return False
            self._rgb = rgb
        self._frozen = True
        self._paint_frames()
        return True

    def _reload_classes(self):
        names = yad.load_classes(self.annot_root)
        cur = self.cb_cls.currentText().strip()
        self.cb_cls.blockSignals(True)
        self.cb_cls.clear()
        self.cb_cls.addItems(names)
        self.cb_cls.setCurrentText(cur if cur in names else (names[0] if names else "optical_module"))
        self.cb_cls.blockSignals(False)
        self.w_orig.set_classes(names)
        self.w_rot.set_classes(names)
        self.w_orig.set_current_class(self.cb_cls.currentText().strip())
        self.w_rot.set_current_class(self.cb_cls.currentText().strip())

    def _on_cls_changed(self, txt):
        txt = (txt or "").strip()
        if not txt:
            return
        if txt not in yad.load_classes(self.annot_root):
            yad.add_class(self.annot_root, txt)      # 手输新类别 → 立即入库 (顺序=class id)
            self._reload_classes()
        self.w_orig.set_current_class(txt)
        self.w_rot.set_current_class(txt)
        self._refresh_data_label()

    def _relabel_selected(self):
        """显式改类别 (从 combo 打字不再顺手改选中框 —— 那会误改: 只想切"下一个框的类别"却改了当前框)"""
        txt = self.cb_cls.currentText().strip()
        if not txt:
            return
        if self.w_orig.selected() < 0:
            self._log_line("没有选中框 (先点一下框再改类别)")
            return
        self.w_orig.set_selected_class(txt)
        self._sync_boxes(self.w_orig, self.w_rot, force=True)
        self._log_line(f"选中框类别 → {txt}")

    def _add_class_dialog(self):
        name, ok = QtWidgets.QInputDialog.getText(self, "新增类别", "类别名 (英文/下划线, 别用空格):")
        if ok and name.strip():
            try:
                yad.add_class(self.annot_root, name.strip())
            except ValueError as e:
                QtWidgets.QMessageBox.warning(self, "类别非法", str(e))
                return
            self._reload_classes()
            self.cb_cls.setCurrentText(name.strip())
            self._log_line(f"新增类别 {name.strip()} → {os.path.join(self.annot_root, 'classes.txt')}")

    def _refresh_data_label(self):
        root = self.annot_root
        names = yad.load_classes(root)
        n_img = len(list(yad.iter_samples(root)))
        n_box = 0
        for s in yad.iter_samples(root):
            n_box += len(yad._read_lines(s["label"]))
        self.lbl_data.setText(f"数据集 {root} · {n_img} 张 / {n_box} 框 · 类别 {names}")

    def _save_annot(self, next_frame=False):
        if self._rgb is None:
            QtWidgets.QMessageBox.information(self, "还没有画面", "当前窗口没有可保存的帧 (链路未就绪?)")
            return None
        boxes = self.w_orig.boxes_px()
        cls0 = self.cb_cls.currentText().strip() or "optical_module"
        yad.add_class(self.annot_root, cls0)
        fm = self._frame_meta or {}
        try:
            rec = yad.save_sample(self.annot_root, self._rgb, boxes,
                                  device=fm.get("device") or "", seq=fm.get("seq"),
                                  ts=time.time(), src=f"{fm.get('src') or self.source}",
                                  session=self._session, annotator=self.ed_who.text().strip(),
                                  tag="d405" if self.source == "real" else "sim",
                                  extra={"frame_age_s": fm.get("age_s"), "ui": "yolo_input_viewer"})
        except Exception as e:                                             # noqa: BLE001
            QtWidgets.QMessageBox.warning(self, "保存失败", f"{type(e).__name__}: {e}")
            return None
        self._n_saved += 1
        msg = (f"已保存 {os.path.basename(rec['image'])} · {len(boxes)} 框 "
               f"({', '.join(b['cls'] for b in rec['boxes']) or '背景样本'}) → {rec['session']}")
        self._log_line(msg)
        self._refresh_data_label()
        if next_frame:
            self.w_orig.clear_boxes()
            self.w_rot.clear_boxes()
            if self._next_frame():
                self._log_line("已取下一帧 (继续标定)")
            else:
                self._log_line("⚠️ 取下一帧失败 (链路无新帧)")
        return rec

    def _save_next(self):
        self._save_annot(next_frame=True)

    def _build_dataset(self):
        def work():
            st = yad.build_dataset(self.annot_root)
            self._log_line(f"📦 数据集构建: train={st['n_train']} val={st['n_val']} 框={st['n_boxes']} "
                           f"类别={st['classes']} → {os.path.join(self.annot_root, 'dataset', 'data.yaml')}")
            self._refresh_data_label()
        self._log_line("📦 正在构建数据集 …")
        threading.Thread(target=work, daemon=True).start()

    def _check_dataset(self):
        def work():
            r = yad.check_dataset(self.annot_root, strict=True)
            line = (f"🔍 体检: 图片 {r['n_images']} · 标注 {r['n_labels']} · 框 {r['n_boxes']} · "
                    f"背景 {r['n_empty_label']} · 类别分布 {r['per_class']} · "
                    f"{'✅ 通过' if not r['errors'] else '❌ ' + str(len(r['errors'])) + ' 错'}")
            self._log_line(line)
            for e in r["errors"][:5]:
                self._log_line("   ❌ " + e)
            for w in r["warnings"][:3]:
                self._log_line("   ⚠️ " + w)
            self._last_check = r
        self._log_line("🔍 正在体检数据集 …")
        threading.Thread(target=work, daemon=True).start()

    def _train_dialog(self):
        n_img = len(list(yad.iter_samples(self.annot_root)))
        if n_img == 0:
            QtWidgets.QMessageBox.information(self, "还没有数据",
                                              f"{self.annot_root} 里还没有标定图片 → 先标定再训练")
            return
        epochs, ok = QtWidgets.QInputDialog.getInt(self, "训练 YOLO", f"用 {n_img} 张标定图片训练几轮?",
                                                   value=100, min=1, max=2000)
        if not ok:
            return
        log = os.path.join(self.annot_root, "train.log")
        cmd = (f"cd {REPO} && source {os.path.join('gui-venv311', 'bin', 'activate')} 2>/dev/null; "
               f"nohup gui-venv311/bin/python tools/yolo_annot_train.py "
               f"--data {os.path.join(self.annot_root, 'dataset')} --epochs {epochs} "
               f"--name annot_{time.strftime('%m%d_%H%M')} --base auto "
               f">{log} 2>&1 &")
        rc, out = _run(["bash", "-lc", cmd], timeout=20)
        self._log_line(f"🚀 训练已启动 (rc={rc}) · 轮数 {epochs} · 日志 {log}")
        QtWidgets.QMessageBox.information(self, "训练已启动",
                                          f"后台训练已启动 ({epochs} 轮)\n日志: {log}\n\n"
                                          "训练/评估说明见该日志; 权重落在 outputs/yolo_annot*/…/weights/best.pt")

    def _open_dir(self):
        os.makedirs(self.annot_root, exist_ok=True)
        _run(["xdg-open", self.annot_root], timeout=10)
        self._log_line(f"📂 已打开数据目录: {self.annot_root}")

    def closeEvent(self, ev):                                              # noqa: N802
        try:
            self.timer.stop()
            self._stop_source()
        except Exception:                                                  # noqa: BLE001
            pass
        # 窗口 = 链路的唯一客户端 ⇒ 关窗收口: 停 Docker 客户端 (Orin 节点 25s 无调用自退)
        # (后台线程做, 别阻塞关窗; ssh/docker 各自有超时)
        try:
            self._closed = True
            if self.source == "real":
                self._chain_stopped = True
                threading.Thread(target=_RemoteChain.stop, daemon=True).start()
        except Exception:                                                  # noqa: BLE001
            pass
        try:
            YoloInputViewer._instances = [w for w in YoloInputViewer._instances if w is not self]
        except Exception:                                                  # noqa: BLE001
            pass
        super().closeEvent(ev)


def open_input_viewer(parent=None, module=None, source: str = "real"):
    """给画布右键菜单用: 复用窗口, 打开即显示实时原始输入流"""
    win = getattr(YoloInputViewer, "_cur", None)
    if win is not None:
        try:
            if not win.isVisible():
                win.show()
            win.raise_()
            win.activateWindow()
            return win
        except Exception:                                                  # noqa: BLE001
            win = None
    win = YoloInputViewer(parent, module=module, source=source)
    YoloInputViewer._cur = win
    # 两个子窗口并排 ⇒ 默认宽度加倍; 屏幕放不下就按可用宽度收 (别出屏)
    w, h = 1320, 760
    try:
        scr = QtWidgets.QApplication.primaryScreen().availableGeometry()
        w = min(w, max(700, scr.width() - 80))
        h = min(h, max(480, scr.height() - 80))
    except Exception:                                                      # noqa: BLE001
        pass
    win.resize(w, h)
    win.show()
    return win
