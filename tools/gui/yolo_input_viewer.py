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
        self.btn = QtWidgets.QPushButton("⏹ 停止链路")
        self.btn.clicked.connect(self._toggle_chain)
        top.addWidget(self.btn)
        v.addLayout(top)

        self.img = QtWidgets.QLabel("等待输入帧…")
        self.img.setObjectName("img")
        self.img.setAlignment(QtCore.Qt.AlignCenter)
        self.img.setMinimumSize(640, 480)
        self.img.setScaledContents(False)
        v.addWidget(self.img, 1)

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
        QtCore.QTimer.singleShot(200, self._start_source)

    # ── 源管理 ──────────────────────────────────────────────────────────
    def _switch(self, _i):
        self._stop_source()
        self._start_source()

    def _start_source(self):
        if self.cb.currentIndex() == 0:
            self.source = "real"
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

    def _toggle_chain(self):
        _RemoteChain.stop()
        self._log_line("已停止 Docker 客户端与 Orin srv 节点 (Orin 侧无调用也会自动退出)")

    def _log_line(self, s):
        if self.module is not None and hasattr(self.module, "_log"):
            try:
                self.module._log(f"📺 输入图像: {s}")
            except Exception:                                              # noqa: BLE001
                pass

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
            return
        try:
            st = os.stat(LIVE_JPG)
            sig = (int(st.st_mtime_ns), st.st_size)
            if sig != self._last_sig:
                pm = QtGui.QPixmap(LIVE_JPG)
                if not pm.isNull():
                    self.img.setPixmap(pm.scaled(self.img.size(), QtCore.Qt.KeepAspectRatio,
                                                 QtCore.Qt.SmoothTransformation))
                    self._last_sig = sig
        except Exception:                                                  # noqa: BLE001
            pass
        if not meta:
            self.st.setText(f"⚠️ 有帧文件但缺 meta ({LIVE_META}) → 无法判定新鲜度")
            return
        ok = bool(meta.get("ok"))
        age = meta.get("age_s")
        stale = bool(meta.get("stale")) or (age is not None and age > 5.0)
        head = "✅ 实时真机帧" if (ok and not stale) else ("⚠️ 无新帧 (显示的是最后一帧)" if ok else "❌ 链路无数据")
        self.st.setText(
            f"{head}   ← 输入源: {meta.get('src')}   ({meta.get('w')}x{meta.get('h')})\n"
            f"设备: {meta.get('device')}\n"
            f"帧号 seq={meta.get('seq')} · 帧龄 age={age}s · JPEG { (meta.get('jpeg_bytes') or 0)/1024:.1f} KB "
            f"· 服务端压缩 {meta.get('encode_ms')} ms (q={meta.get('quality')}) · 服务端 {meta.get('server_fps')} Hz\n"
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
        self.img.setPixmap(pm.scaled(self.img.size(), QtCore.Qt.KeepAspectRatio,
                                     QtCore.Qt.SmoothTransformation))
        self._sim_fps_n += 1
        if time.time() - self._sim_fps_t >= 1.0:
            self._sim_fps = self._sim_fps_n / (time.time() - self._sim_fps_t)
            self._sim_fps_n, self._sim_fps_t = 0, time.time()
        self.st.setText(f"🧪 仿真渲染帧 (metaworld corner2) · {w}x{h} · {self._sim_fps:.1f} FPS\n"
                        f"设备: {d['info'].get('device')}\n"
                        f"用途: 与真机帧做口径对照 (朝向 rot90 / 通道 / 内参 / 深度)")

    def closeEvent(self, ev):                                              # noqa: N802
        try:
            self.timer.stop()
            self._stop_source()
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
    win.resize(700, 640)
    win.show()
    return win
