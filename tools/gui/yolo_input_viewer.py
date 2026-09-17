#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""yolo_input_viewer.py — 「打开输入图像」实时视频流窗口 (节点右键菜单入口)

老倪 2026-09-17: 「yolo 目标检测节点, 增加右键打开输入图像的功能, 右键打开就能实时看到我
当前接入的输入原始视频流, 我要看到现在是否能看到 realsense 的相机图像」
+ 「4060 上的视频流窗口要从本地 docker 的 ros2 节点获取图像; orin 上传的视频流, 在 ROS2 srv
节点做视频压缩处理」

三条输入源 (同一窗口切换, 都显示**原始**帧):
  ① 🎥 真机 RealSense (Orin → ROS2 srv → 4060 Docker → 本地文件):
     链路 = `tools/orin_frame_srv.py` (Orin, UVC 取帧 + **JPEG 压缩在服务端**, 服务 /zmax/live_frame)
           → `tools/ss_frame_srv_client.py` (本机 Docker, srv 客户端, 落 live_frame.jpg + .json)
           → 本窗口轮询该文件显示 (GUI 无需 rclpy)。
     窗口顶部显示设备身份/分辨率/服务端 fps/帧龄/JPEG 字节 → 一眼看出"到底有没有拿到 D405 图像"。
  ② 🧪 仿真渲染 (metaworld corner2) — 与引擎同源, 用来对照"口径是否正确"。
  ③ 📁 回放目录 — 无相机环境下的离线核对。

纪律: 只显示原始帧 (不画框); 勾「叠加 YOLO 框」才跑检测 (默认关, 保持"原始视频流"语义)。
新鲜度: meta.age_s 超阈值即显示 "⚠️ 无新帧", 绝不拿旧图冒充实时 (老倪红线)。

双画面 (老倪 2026-09-17: 「相机总是翻转, 要同时显示两个窗口, 一个原始一个旋转180度, 方便观察」):
  同一帧**并排两个子窗口** —— 左 = 原始 (0°), 右 = 旋转 (默认 180°, 可选 90°/270°)。
  旋转用 Qt 原生 `QPixmap.transformed(QTransform().rotate(deg))` (不依赖 cv2, 也不改像素语义),
  两窗共用**同一帧源**, 分辨率/帧龄/设备身份完全一致 → 只是观察方向不同, 不产生第二路数据。
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets

ORIN = os.environ.get("ZMAX_ORIN_HOST", "tashan@192.168.23.66")
CONTAINER = os.environ.get("ZMAX_TAP_CONTAINER", "ss-remote-tap")
SHARED = os.environ.get("ZMAX_SS_REMOTE_DIR", "/home/ubuntu/zmax_ss_remote")
LIVE_JPG = os.path.join(SHARED, "live_frame.jpg")
LIVE_META = os.path.join(SHARED, "live_frame.json")
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SSH = ["ssh", "-o", "ConnectTimeout=6", "-o", "StrictHostKeyChecking=no", ORIN]

_CSS = ("QDialog{background:#0d1117;} QLabel{color:#e6edf3;font-size:12px;}"
        "QLabel#img{background:#161b22;border:1px solid #30363d;}"
        "QLabel#ph{color:#8b949e;font-size:11px;padding:1px 2px;}"
        "QLabel#st{background:#161b22;border:1px solid #30363d;padding:6px;}"
        "QPushButton{background:#21262d;color:#e6edf3;border:1px solid #30363d;padding:5px 10px;border-radius:4px;}"
        "QPushButton:hover{background:#30363d;} QCheckBox{color:#e6edf3;} QComboBox{background:#161b22;color:#e6edf3;}")


def _run(cmd, timeout=15, shell=False):
    try:
        r = subprocess.run(cmd, shell=shell, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception as e:                                                 # noqa: BLE001
        return -1, f"{type(e).__name__}: {e}"


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
            import sys
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
    """实时输入图像窗口 (非模态, 可与其后窗口复用)"""

    _instances: list = []

    def __init__(self, parent=None, module=None, source: str = "real"):
        super().__init__(parent, QtCore.Qt.Window)
        self.setWindowTitle("📺 输入图像 · 实时视频流 (YOLO 目标检测 节点)")
        self.setStyleSheet(_CSS)
        self.setWindowFlag(QtCore.Qt.WindowMinimizeButtonHint, True)
        self.setWindowFlag(QtCore.Qt.WindowMaximizeButtonHint, True)
        self.module = module
        self.source = source
        self._q: queue.Queue = queue.Queue(maxsize=4)
        self._sim: _SimGrabber | None = None
        self._last_sig = None
        self._sim_fps_t, self._sim_fps_n = time.time(), 0
        self._sim_fps = 0.0

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
        # 双画面: 相机常被翻转安装 → 右侧并排显示旋转后的同一帧 (默认开, 180°)
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

        # ── 两个子窗口并排: 左 = 原始 (0°) / 右 = 旋转 (相机翻转) ──
        panes = QtWidgets.QHBoxLayout()
        self._pm = {"orig": None, "rot": None}
        self._painting = False
        pane_titles = {"orig": "🖼 原始 (0°)", "rot": "🔄 旋转 180° (相机翻转)"}
        self._pane_head = {}
        for key in ("orig", "rot"):
            col = QtWidgets.QVBoxLayout()
            head = QtWidgets.QLabel(pane_titles[key])
            head.setObjectName("ph")
            im = QtWidgets.QLabel("等待输入帧…")
            im.setObjectName("img")
            im.setAlignment(QtCore.Qt.AlignCenter)
            im.setMinimumSize(320, 240)
            im.setScaledContents(False)
            col.addWidget(head)
            col.addWidget(im, 1)
            self._pane_head[key] = head
            panes.addLayout(col, 1)
        self._pane_img = {"orig": panes.itemAt(0).layout().itemAt(1).widget(),
                          "rot": panes.itemAt(1).layout().itemAt(1).widget()}
        self.img = self._pane_img["orig"]           # 原始画面 (兼容旧调用/取证)
        self.img_rot = self._pane_img["rot"]        # 旋转画面
        v.addLayout(panes, 1)

        self.st = QtWidgets.QLabel("—")
        self.st.setObjectName("st")
        self.st.setWordWrap(True)
        self.st.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        v.addWidget(self.st)

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
        if self.source == "real" and not self._chain_stopped and time.time() - self._last_show_ensure > 30:
            self._last_show_ensure = time.time()
            self._stale_since = None
            self._last_recover = time.time()
            threading.Thread(target=self._ensure_chain_bg, daemon=True).start()

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

    # ── 双画面 (原始 / 旋转) ────────────────────────────────────────────
    def _rot_deg(self) -> int:
        return {"180°": 180, "90°": 90, "270°": 270}.get(self.cb_rot.currentText(), 180)

    def _apply_rot_vis(self):
        """旋转开关/角度变化: 显隐右窗并按当前角度重画 (共用同一帧, 不产生第二路数据)"""
        on = self.chk_rot.isChecked()
        for w in (self._pane_head["rot"], self.img_rot):
            w.setVisible(on)
        if not on:
            self._pm["rot"] = None
            self.img_rot.clear()
        if on:
            self._pane_head["rot"].setText(f"🔄 旋转 {self._rot_deg()}° (相机翻转)")
            if self._pm.get("orig") is not None:
                self._set_frames(self._pm["orig"])
        self._paint_frames()

    def _set_frames(self, pm_src):
        """同一帧 → 两个子窗口: 左=原始 / 右=旋转 (Qt 原生 transform, 无 cv2 依赖)"""
        self._pm["orig"] = pm_src
        if self.chk_rot.isChecked() and pm_src is not None and not pm_src.isNull():
            self._pm["rot"] = pm_src.transformed(QtGui.QTransform().rotate(self._rot_deg()),
                                                 QtCore.Qt.SmoothTransformation)
        else:
            self._pm["rot"] = None
        self._paint_frames()

    def _paint_frames(self):
        """把缓存的两帧按各自子窗口尺寸等比缩放显示 (resize 时重画, 不重新解码)"""
        if self._painting:
            return
        self._painting = True
        try:
            for key in ("orig", "rot"):
                im = self._pane_img[key]
                pm = self._pm.get(key)
                if pm is None or pm.isNull():
                    continue
                if im.width() < 10 or im.height() < 10:
                    continue
                im.setPixmap(pm.scaled(im.size(), QtCore.Qt.KeepAspectRatio,
                                       QtCore.Qt.SmoothTransformation))
        finally:
            self._painting = False

    def resizeEvent(self, ev):                                              # noqa: N802
        super().resizeEvent(ev)
        self._paint_frames()

    # ── 刷新 ────────────────────────────────────────────────────────────
    def _tick(self):
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
                pm = QtGui.QPixmap(LIVE_JPG)
                if not pm.isNull():
                    self._set_frames(pm)          # 同一帧 → 左原始 + 右旋转(180°)
                    self._last_sig = sig
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
        self.st.setText(
            f"{head}   ← 输入源: {meta.get('src')}   ({meta.get('w')}x{meta.get('h')})\n"
            f"设备: {meta.get('device')}\n"
            f"帧号 seq={meta.get('seq')} · 帧龄 age={age}s · JPEG { (meta.get('jpeg_bytes') or 0)/1024:.1f} KB "
            f"· 服务端压缩 {meta.get('encode_ms')} ms (q={meta.get('quality')}) · 服务端 {meta.get('server_fps')} Hz\n"
            f"双画面: 左=原始 (0°) · {('右=旋转 ' + str(self._rot_deg()) + '° (同一帧的 Qt 旋转, 观察用, 不改像素语义)') if self.chk_rot.isChecked() else '右窗已关 (勾「🔄 并排旋转窗」打开)'}\n"
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
        img = QtGui.QImage(bytes(rgb.data), w, h, 3 * w, QtGui.QImage.Format_RGB888)
        pm = QtGui.QPixmap.fromImage(img)
        self._set_frames(pm)
        self._sim_fps_n += 1
        if time.time() - self._sim_fps_t >= 1.0:
            self._sim_fps = self._sim_fps_n / (time.time() - self._sim_fps_t)
            self._sim_fps_n, self._sim_fps_t = 0, time.time()
        self.st.setText(f"🧪 仿真渲染帧 (metaworld corner2) · {w}x{h} · {self._sim_fps:.1f} FPS\n"
                        f"设备: {d['info'].get('device')}\n"
                        f"双画面: 左=原始 (0°) · {('右=旋转 ' + str(self._rot_deg()) + '° (同一帧旋转)') if self.chk_rot.isChecked() else '右窗已关'}\n"
                        f"用途: 与真机帧做口径对照 (朝向 rot90 / 通道 / 内参 / 深度)")

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
    w, h = 1320, 700
    try:
        scr = QtWidgets.QApplication.primaryScreen().availableGeometry()
        w = min(w, max(700, scr.width() - 80))
        h = min(h, max(480, scr.height() - 80))
    except Exception:                                                      # noqa: BLE001
        pass
    win.resize(w, h)
    win.show()
    return win
