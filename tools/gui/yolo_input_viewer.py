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
import re
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
import real_truth as rt                                   # noqa: E402  真机位姿真值 (单一来源)

ORIN = os.environ.get("ZMAX_ORIN_HOST", "tashan@192.168.23.66")
CONTAINER = os.environ.get("ZMAX_TAP_CONTAINER", "ss-remote-tap")
SHARED = os.environ.get("ZMAX_SS_REMOTE_DIR", "/home/ubuntu/zmax_ss_remote")
LIVE_JPG = os.path.join(SHARED, "live_frame.jpg")
LIVE_META = os.path.join(SHARED, "live_frame.json")
# 🩹 2026-09-18 老倪: 「运行L2功能, 怎么输入图像没有了?」—— 真机源原来**只认 srv 落盘 live_frame.jpg**
#   (Orin /zmax/live_frame → Docker 客户端), 该服务不可达时窗口就"永远无画面"; 而真机图像其实一直在流:
#   Docker tap 只读订阅落盘的 cam_rs.png 一直新鲜, **L2 侧吃的就是这条** (ss_yolo_on_real CAND)。
#   → 加候选链回退 (同一帧口径, 与 L2 同源), 仍守"只上新鲜帧、旧图不冒充"纪律。
REAL_FILE_CANDS = (
    ("cam_rs.png", "RealSense 彩色 (Docker tap 只读订阅落盘 · 与 L2 同源)"),
    ("cam_fp.png", "FoundationPose 调试图 (Docker tap 落盘 · 与 L2 同级)"),
    ("cam_latest.png", "最近图像帧 (Docker tap 落盘)"),
    ("srv_cam.png", "srv 落盘 PNG"),
    ("srv_cam.jpg", "srv 落盘 JPEG"),
)
REAL_FILE_FRESH_S = float(os.environ.get("ZMAX_VIEWER_FILE_FRESH_S", "10"))
# 💻 2026-09-17 老倪: 第三路输入源 = 本机内置摄像头 (UVC 直读, 不依赖 Orin/Docker)
USBCAM_DEV = os.environ.get("ZMAX_USBCAM_DEV", "/dev/video0")
USBCAM_FPS = int(os.environ.get("ZMAX_USBCAM_FPS", "15"))
_SRC_IDX = {"real": 0, "sim": 1, "usbcam": 2}
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


def _live_weights():
    """🎯 真机在役 YOLO 权重 = models/yolo_peg_live.pt (符号链接指针; 升级只需重指这一处)。"""
    p = os.path.join(REPO, "models", "yolo_peg_live.pt")
    return p if os.path.exists(p) else None


_DET_MODELS: dict = {}


def _detect_with(weights: str, rgb):
    """真推理检测 (按权重缓存模型) → [{cls, conf, xyxy}]。任何异常都返回 [] (绝不因检测崩窗口)。"""
    try:
        from ultralytics import YOLO
        if not weights:
            return []
        m = _DET_MODELS.get(weights)
        if m is None:
            m = YOLO(weights)
            _DET_MODELS[weights] = m
        r = m.predict(np.ascontiguousarray(rgb[:, :, ::-1]), imgsz=640, conf=0.25, verbose=False)[0]
        names = m.names
        return [{"cls": str(names.get(int(b.cls[0]), int(b.cls[0]))),
                 "conf": round(float(b.conf[0]), 3),
                 "xyxy": [float(v) for v in b.xyxy[0].tolist()]} for b in r.boxes]
    except Exception:                                                          # noqa: BLE001
        return []


def _live_detect(rgb):
    """真机帧检测 (权重 = models/yolo_peg_live.pt, 与 L2 旁路同域同口径)。"""
    return _detect_with(_live_weights(), rgb)


def _render_boxes(rgb, dets):
    """在**副本**上画框 (标定用的原始像素不动)。"""
    try:
        import cv2
        out = np.ascontiguousarray(rgb.copy())
        for d in dets:
            x1, y1, x2, y2 = [int(v) for v in d["xyxy"]]
            col = (0, 255, 128) if str(d["cls"]).lower() == "peg" else (0, 200, 255)
            cv2.rectangle(out, (x1, y1), (x2, y2), col, 2)
            cv2.putText(out, f"{d['cls']} {d['conf']:.2f}", (x1, max(14, y1 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 1, cv2.LINE_AA)
        return out
    except Exception:                                                          # noqa: BLE001
        return rgb


def rgb_from_file(path):
    """读图 → RGB uint8 (cv2 优先; 无 cv2 用 Qt 解码)

    🛠 2026-09-18: 改为**先整块读入内存再解码** + 失败一律返回 None (不抛)。
    原因: 落盘方 (Docker tap) 是 10Hz 覆盖写, 老实现 `cv2.imread(path)` 可能撞上
    半张 PNG (截断帧) → 解码路径不稳定; 现在读到内存再解 (截断 → 解码失败 → None),
    调用方按"这帧不可用"跳过, 绝不因读图失败崩窗口。
    """
    try:
        with open(path, "rb") as f:
            buf = f.read()
    except OSError:
        return None
    if not buf:
        return None
    # ① cv2 可用 → **它就是权威**: 解码失败 (含截断帧) 直接判"这帧不可用"返回 None,
    #    不再把坏数据交给 Qt 解码器 (实测: 截断 buffer 会走进 Qt 解码路径, 无 QApplication 时
    #    直接 `QPixmap: Must construct a QGuiApplication` → SIGABRT; 有 QApplication 也只是白解坏数据)。
    try:
        import cv2
    except ImportError:
        cv2 = None
    if cv2 is not None:
        try:
            bgr = cv2.imdecode(np.frombuffer(buf, np.uint8), cv2.IMREAD_COLOR)
            return None if bgr is None else np.ascontiguousarray(bgr[:, :, ::-1])
        except Exception:                                                  # noqa: BLE001
            return None
    # ② 只在没有 cv2 时才退回 Qt 解码 (且必须已有 QGuiApplication)
    try:
        pm = QtGui.QPixmap()
        if not pm.loadFromData(buf):
            return None
        return qimage_to_rgb(pm.toImage())
    except Exception:                                                      # noqa: BLE001
        return None


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


def _engine_live_frame(max_age=2.0):
    """▶运行 中, 引擎当前步的实况帧 (同进程共享槽, 见 state_space_sim_real.SS_LIVE_FRAME)

    → (rgb, step, age_s) | None。引擎没在跑 (或帧太旧) → None, 窗口回退到静态渲染并**如实标注**。
    🎥 2026-09-17 老倪: 「点了运行, 仿真图像不动」根因 —— 原来这个仿真源渲染的是
    node_logic._YOLO_ALIGNER.env (只 reset 过一次、从没 step 过) → 永远同一帧, 与运行无关。
    """
    try:
        import state_space_sim_real as _ssr
        return _ssr.ss_latest_live_frame(max_age)
    except Exception:                                                      # noqa: BLE001
        return None


def _engine_live_frame_consumed():
    """窗口真显示了一帧实况 → 计数 (外部核对 /tmp/ss_live_frame.json: viewer_consumed)"""
    try:
        import state_space_sim_real as _ssr
        _ssr.ss_mark_live_frame_consumed()
    except Exception:                                                      # noqa: BLE001
        pass


def _engine_viewer_wants(want):
    """告知引擎: 仿真实况窗口开/关 (关 → 非视觉档不再渲染, 零开销)"""
    try:
        import state_space_sim_real as _ssr
        _ssr.ss_set_viewer_wants(bool(want))
    except Exception:                                                      # noqa: BLE001
        pass


def _banner(rgb, text, color=(255, 140, 40)):
    """在画面上压一条提示横幅 (顶部深色底 + 橙字) — 让"这不是运行画面"一眼可见

    🎯 2026-09-17 老倪两次问「仿真渲染里光模块没插进槽/和插槽横向有偏差」——
    实际看到的是**引擎未运行时的静止初始帧**(metaworld 初始布局: 光模块平躺台面,
    离插槽水平 ~358mm)。只靠状态栏小字不够, 直接压在画面上。
    """
    try:
        import numpy as _np
        out = _np.ascontiguousarray(rgb).copy()
        h, w = out.shape[:2]
        band = max(20, int(h * 0.075))
        out[:band, :, :] = (out[:band, :, :] * 0.25).astype(out.dtype)     # 压暗
        try:
            import cv2 as _cv2
            _cv2.putText(out, text, (8, int(band * 0.72)), _cv2.FONT_HERSHEY_SIMPLEX,
                         max(0.32, w / 1600.0), color, 1, _cv2.LINE_AA)
        except Exception:                                                  # noqa: BLE001
            pass
        return out
    except Exception:                                                      # noqa: BLE001
        return rgb


class _SimGrabber(threading.Thread):
    """仿真渲染取帧 (worker 线程: 只做 mujoco render / 读实况槽, 不碰 Qt)

    🎥 两路来源 (2026-09-17):
      · ▶运行 中 → 用引擎**当前步**渲染的那一帧 (与 detect_3d 同一帧) = 与运行严格同步
      · 引擎 idle → 回退到对齐器 env 的静态渲染, 标注"引擎未运行 → 静态初始帧" (如实, 不假动)
    """

    def __init__(self, out_q: queue.Queue, yolo_overlay: bool):
        super().__init__(daemon=True)
        self.q = out_q
        self.overlay = yolo_overlay
        self.stop_flag = False

    def _grab_once(self, nl):
        """取一帧 → (img, info); nl 可为 None (仅当不需要叠加检测时)"""
        _live = _engine_live_frame()
        al = None
        if _live is not None:
            img, _step, _age = _live
            info = {"src": "engine:▶运行 实况 (metaworld corner2)",
                    "shape": f"{img.shape[1]}x{img.shape[0]}",
                    "device": f"引擎渲染帧 (与 detect_3d 同一帧) · step={_step} · 帧龄 {_age:.2f}s",
                    "step": _step, "age": _age, "engine": True}
        else:
            if nl is None:                                  # 只可能在"只用实况帧"的调用里
                return None, None
            al = nl._yolo_ensure_aligner(None)
            img = al.env.render()          # RGB 原始渲染帧 (与引擎同源; 但该 env 从不 step)
            info = {"src": "sim:metaworld corner2 (引擎未运行 → 静态初始帧)",
                    "shape": f"{img.shape[1]}x{img.shape[0]}",
                    "device": "mujoco 渲染 (非真机相机) · 引擎 idle",
                    "engine": False}
        if self.overlay:
            try:                       # 可选: 同时跑检测, 证明模型看到的就是这帧
                if al is None:
                    al = nl._yolo_ensure_aligner(None)
                _bgr = np.ascontiguousarray(img)[:, :, ::-1].copy()
                res = al.model.predict(_bgr, conf=0.4, verbose=False)[0]
                _plotted = res.plot()
                img = _plotted[:, :, ::-1] if _plotted is not None else img
                info["yolo"] = f"{len(res.boxes)} 框"
            except Exception as e:                                     # noqa: BLE001
                info["yolo"] = f"检测失败 {type(e).__name__}"
        if not info.get("engine"):
            img = _banner(img, "⚠️ 引擎未运行 · 静态初始帧 — 这幅画面没有在跑仿真 (点 ▶运行 看实况)")
        return img, info

    def run(self):
        nl = None
        if self.overlay:            # 只有要叠加检测时才需要 node_logic/对齐器 (否则零加载)
            try:
                sys.path.insert(0, os.path.join(REPO, "tools", "gui"))
                import node_logic as nl_   # noqa: F401
                nl = nl_
            except Exception as e:                                     # noqa: BLE001
                self.q.put({"err": f"node_logic 加载失败: {e}"})
                return
        while not self.stop_flag:
            t0 = time.time()
            try:
                img, info = self._grab_once(nl)
                if img is None:
                    time.sleep(0.1)
                    continue
                if info.get("engine"):
                    _engine_live_frame_consumed()
                self.q.put({"rgb": np.ascontiguousarray(img), "info": info})
            except Exception as e:                                     # noqa: BLE001
                self.q.put({"err": f"仿真取帧失败: {type(e).__name__}: {e}"})
                time.sleep(0.5)
            dt = 0.08 - (time.time() - t0)
            if dt > 0:
                time.sleep(dt)


class _CamGrabber(threading.Thread):
    """💻 本机内置摄像头取帧 (cv2/V4L2 直读; 只读设备, 不碰 Orin/Docker/Qt)

    ⚠️ cv2 在**主线程**先 import 好再传进来 (PyQt5 进程里后台线程首次 import cv2
    可能触发它自带的 Qt 插件路径, 与主程序 Qt 打架 — 老倪这台机器 08 月踩过同类坑)。
    """

    def __init__(self, out_q: queue.Queue, dev: str = USBCAM_DEV, fps: int = USBCAM_FPS, cv2=None):
        super().__init__(daemon=True)
        self.q = out_q
        self.dev = dev
        self.fps = max(1, int(fps))
        self.cv2 = cv2
        self.stop_flag = False

    def _open(self, cv2):
        """打开设备 —— ⚠️ cv2 V4L2 后端**不能按设备名(path)打开**
        (实测 cv2 5.0: "backend is generally available but can't be used to capture by name") →
        /dev/videoN 一律换算成索引 N 打开; 非标准路径才退回按名字 (默认后端)。"""
        dev = str(self.dev)
        m = re.match(r"^/dev/video(\d+)$", dev)
        cap = cv2.VideoCapture(int(m.group(1)), cv2.CAP_V4L2) if m else cv2.VideoCapture(dev)
        try:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        except Exception:                                                # noqa: BLE001
            pass
        return cap

    def run(self):
        cv2 = self.cv2
        if cv2 is None:
            try:
                import cv2 as _c2                                        # noqa: PLC0415
                cv2 = _c2
            except Exception as e:                                       # noqa: BLE001
                self.q.put({"err": f"cv2 不可用: {e}"})
                return
        cap = None
        while not self.stop_flag:
            if cap is None or not cap.isOpened():
                try:
                    cap = self._open(cv2)
                except Exception as e:                                   # noqa: BLE001
                    self.q.put({"err": f"打开摄像头失败 {self.dev}: {type(e).__name__}: {e}"})
                    time.sleep(1.0)
                    continue
                if not cap.isOpened():
                    self.q.put({"err": f"打不开摄像头 {self.dev} (被占用? 另一路摄像头源/其它程序正在读; "
                                       f"或设备号不对 → 可改 ZMAX_USBCAM_DEV=/dev/videoN)"})
                    time.sleep(1.0)
                    continue
            t0 = time.time()
            ok, fr = cap.read()
            if not ok or fr is None:
                self.q.put({"err": f"摄像头读帧失败 {self.dev} → 重连中"})
                try:
                    cap.release()
                except Exception:                                        # noqa: BLE001
                    pass
                cap = None
                time.sleep(0.5)
                continue
            rgb = np.ascontiguousarray(fr[:, :, ::-1])       # BGR→RGB (与真机/仿真同口径)
            self.q.put({"rgb": rgb, "info": {
                "src": f"usbcam:{self.dev}", "device": "本机内置 UVC 摄像头",
                "shape": f"{rgb.shape[1]}x{rgb.shape[0]}", "engine": False, "usbcam": True}})
            dt = (1.0 / self.fps) - (time.time() - t0)
            if dt > 0:
                time.sleep(dt)
        try:
            if cap is not None:
                cap.release()
        except Exception:                                                # noqa: BLE001
            pass


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
        self._cam: _CamGrabber | None = None           # 💻 本机摄像头取帧线程
        self._last_sig = None
        self._sim_fps_t, self._sim_fps_n = time.time(), 0
        self._sim_fps = 0.0
        self._rgb = None                      # 当前显示帧 (原始朝向 RGB)
        self._view_tag = ""                   # 🖼 当前画面来源: real / sim-engine / sim-idle / waiting-* / stale-real
        self._real_last_fresh = 0.0           # 🖼 最近一次"新鲜真机帧"上屏时间 (判旧图是否该换占位)
        self._frozen = False                  # 冻结 (标定用): 不再跟随实时帧
        self._pending = None                  # 冻结期间攒下的最新帧
        self._frame_meta = {}                 # 当前帧来源 (device/seq/age/src)
        self._session = yad.session_name("d405")
        self._n_saved = 0
        self._last_saved = None               # 最近一次保存的样本 {stem, session} — 供「🗑 丢弃当前帧」
        self._syncing = False

        # 数据根随**输入源**走 (真机/仿真/本机摄像头分开存: 口径不同, 混一起训练会让类别语义打结)
        self._annot_source = {"real": "real", "sim": "sim", "usbcam": "usbcam"}.get(source, "real")
        self.annot_root = yad.ensure_layout(yad.root_for(self._annot_source),
                                            yad.default_classes_for(self._annot_source))["root"]
        self._session = yad.session_name(yad.session_tag_for(self._annot_source))

        # ── 第 1 行: 输入源 / 显示 ──
        v = QtWidgets.QVBoxLayout(self)
        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel("输入源:"))
        self.cb = QtWidgets.QComboBox()
        self.cb.addItems(["🎥 真机 RealSense (Orin→ROS2 srv→Docker)",
                          "🧪 仿真渲染 (metaworld corner2)",
                          f"💻 本机摄像头 (内置 UVC {USBCAM_DEV})"])
        self.cb.setCurrentIndex(_SRC_IDX.get(str(source), 0))
        self.cb.currentIndexChanged.connect(self._switch)
        top.addWidget(self.cb, 1)
        # 🎯 2026-09-18 老倪: 「在 YOLO 目标检测节点的当前输入图像的基础之上, 增加一个感知模式,
        #   点击感知模式后, 即可在当前图像上叠加感知结果 bounding box」
        #   设计 = **单一开关** (取代原来语义含糊的「叠加 YOLO 框」): 点开即在**当前显示的这一帧**
        #   (实时/冻结 · 真机/仿真/本机摄像头 任一源) 上叠加真推理的检测框 + 右侧一行结果数值;
        #   只叠加**显示**, 存档/标定永远用原始像素 (框不会烧进训练图)。
        self.btn_percept = QtWidgets.QPushButton("🎯 感知模式")
        self.btn_percept.setCheckable(True)
        self.btn_percept.setToolTip("在当前输入图像上叠加**感知结果** (目标检测 bounding box)\n"
                                    "· 真机源 → models/yolo_peg_live.pt (与 L2 管线同一权重)\n"
                                    "· 仿真源 → 仿真域权重 (域不混, 只用于对照)\n"
                                    "· 只叠加显示: 标定存档仍用原始像素, 框不会烧进训练图")
        self.btn_percept.toggled.connect(self._on_percept)
        top.addWidget(self.btn_percept)
        self.lbl_percept = QtWidgets.QLabel("")
        self.lbl_percept.setObjectName("ph")
        _sp5 = self.lbl_percept.sizePolicy()
        _sp5.setHorizontalPolicy(QtWidgets.QSizePolicy.Ignored)
        self.lbl_percept.setSizePolicy(_sp5)
        top.addWidget(self.lbl_percept, 1)
        self.chk = QtWidgets.QCheckBox("叠加 YOLO 框")
        self.chk.setChecked(False)
        self.chk.setVisible(False)          # 由「🎯 感知模式」取代 (保留控件以便双向同步/兼容旧调用)
        self.chk.setToolTip("(旧开关) 与「🎯 感知模式」同一个语义: 勾它 = 打开感知模式")
        self.chk.toggled.connect(self._on_percept_alias)
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

        # ── 真值行 (老倪 2026-09-17: 「训练要有光模块距离/位置等信息…读出真值, 对齐 metaworld 数据」) ──
        #   真值 = 4060 侧 Docker 只读订阅 Orin /robot/tcp_pose 落盘的 state jsonl / status.json (单一来源
        #   tools/real_truth.py)。1Hz 刷新 (别跟着 15Hz 画面刷, 文件 IO 不值当); 保存标注时**同时**把真值写进样本。
        trow = QtWidgets.QHBoxLayout()
        self.lbl_truth = QtWidgets.QLabel("📌 真机真值: 读取中…")
        self.lbl_truth.setObjectName("ph")
        self.lbl_truth.setWordWrap(True)
        self.lbl_truth.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        _sp3 = self.lbl_truth.sizePolicy()
        _sp3.setHorizontalPolicy(QtWidgets.QSizePolicy.Ignored)
        self.lbl_truth.setSizePolicy(_sp3)
        trow.addWidget(self.lbl_truth, 1)
        v.addLayout(trow)

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
                             ("🏷 改选中类别", self._relabel_selected, "把选中的框改成当前类别 (哪个窗选中就改哪个)"),
                             ("↩ 撤销", lambda: self._active_pane().undo(), "撤销上一次改动 (Ctrl+Z)"),
                             ("🗑 删选中", lambda: self._active_pane().remove_selected(), "删除选中框 (Del)"),
                             ("✖ 清空框", lambda: self._active_pane().clear_boxes(), "清空本帧所有框"),
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
                             ("🗑 丢弃当前帧", self._discard_current,
                              "把**刚保存的这张**样本从会话里删掉 (图+标注成对删, 不留孤儿)"),
                             ("🗑 清空本会话", self._clear_session,
                              "删掉当前会话全部样本 (图+标注) — 会先弹确认, 不可恢复"),
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

        # ── 第 3.5 行: 本窗口**自己的结果回显** ──────────────────────────────
        #   老倪 2026-09-18: 「我点击 构建数据集 / 数据体检 / 训练YOLO, 也没有反应啊」
        #   实测这三个按钮**都在干活** (simulink_log 有实证: 07:17:59 构建 train=21/val=2/框=23、
        #   07:18:09 体检 ✅ 通过、07:18:13 训练 rc=0 起了 100 轮) —— 但结果只写进**画布底部日志**,
        #   本窗口里一个字都不显示 ⇒ 用户完全不知道点成功了没有。现在本窗口内直接回显每一步结果,
        #   并挂训练进度轮询 (从 results.csv 读真值, 不编造)。
        self.lbl_annot_result = QtWidgets.QLabel("")
        self.lbl_annot_result.setObjectName("st")
        self.lbl_annot_result.setWordWrap(True)
        self.lbl_annot_result.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        _sp4 = self.lbl_annot_result.sizePolicy()
        _sp4.setHorizontalPolicy(QtWidgets.QSizePolicy.Ignored)
        self.lbl_annot_result.setSizePolicy(_sp4)
        v.addWidget(self.lbl_annot_result)

        # ── 两个子窗口: 左 = 原始 (0°) / 右 = 旋转 (相机翻转) ──
        panes = QtWidgets.QHBoxLayout()
        self.w_orig = YoloLabelWidget(rot_deg=0, editable=False)
        self.w_rot = YoloLabelWidget(rot_deg=180, editable=False)
        self.w_rot.setVisible(False)
        self.w_orig.changed.connect(lambda: self._sync_boxes(self.w_orig, self.w_rot))
        self.w_rot.changed.connect(lambda: self._sync_boxes(self.w_rot, self.w_orig))
        # 🐛 2026-09-17 老倪「改选中的类别不好使」根因: 两窗只同步**框集合**, 不同步**选中项**
        #   —— _sync_boxes 在"框集合相同"时直接 return, 而在旋转窗里点选一个框只改 _sel 不改框集合
        #   ⇒ 左窗 _sel 仍是 -1, 而「🏷改选中类别 / 🗑删选中 / ↩撤销」当时全绑在 w_orig.selected() 上
        #   ⇒ 在右窗(旋转180°, 相机翻转时最常用)选中框后点这些键 = 取不到选中 → 看着像按钮坏了。
        #   修: ①两侧 selectionChanged 互相同步选中索引 ②这些按钮改走 _active_pane() (谁选中就作用于谁)。
        self.w_orig.selectionChanged.connect(lambda i: self._mirror_sel(self.w_orig, self.w_rot, i))
        self.w_rot.selectionChanged.connect(lambda i: self._mirror_sel(self.w_rot, self.w_orig, i))
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
        # ── 第 3 列: 📺 实时预览 + 📸 抓当前帧 ────────────────────────────────
        #   老倪 2026-09-18: 「保存并下一帧时我看不到当前实时画面, 怎么办?」
        #   标定必须在**冻结帧**上画框 (不能动), 但作业期间必须能看见现场实时画面,
        #   才能判断"画面到现在这个状态了、该抓下一帧了" (例: 光模块已被送到位)。
        #   故加这一列: 冻结时它持续显示**同一路新鲜帧** (与 L2 同源, 带帧龄),
        #   并给「📸 用当前实时帧标定」一键把标定画面换成此刻那一帧 (换帧即清框 —— 框属于旧帧坐标)。
        pipcol = QtWidgets.QVBoxLayout()
        self.lbl_pip_head = QtWidgets.QLabel("📺 实时预览 (冻结也能看)")
        self.lbl_pip_head.setObjectName("ph")
        pipcol.addWidget(self.lbl_pip_head)
        self.pip = QtWidgets.QLabel("(等待新鲜实时帧…)")
        self.pip.setMinimumSize(300, 225)
        self.pip.setAlignment(QtCore.Qt.AlignCenter)
        self.pip.setWordWrap(True)
        self.pip.setStyleSheet("background:#0d1117; color:#8b949e; border:1px solid #30363d;")
        pipcol.addWidget(self.pip, 1)
        self.btn_grab = QtWidgets.QPushButton("📸 用当前实时帧标定")
        self.btn_grab.setToolTip("把标定画面换成**此刻的实时帧** (会清掉当前框: 框属于旧帧坐标, 不能跨帧留)\n"
                                 "用途: 冻结作业时看到现场到位了 → 一键抓这一帧来标")
        self.btn_grab.clicked.connect(self._grab_live_frame)
        pipcol.addWidget(self.btn_grab)
        # 🔄 实时预览翻转 (老倪 2026-09-18: 「实时图像要能够调整翻转180度, 因为相机总是自己翻转」)
        #   相机倒装/翻转安装是常态 → 实时预览窗必须能独立转正 (只影响**显示**, 不改像素与标签语义:
        #   标定框始终按原始帧坐标存档, 抓帧也永远抓原始朝向那一帧)。
        _rotrow = QtWidgets.QHBoxLayout()
        _lbl = QtWidgets.QLabel("🔄 预览翻转:")
        _lbl.setObjectName("ph")
        _rotrow.addWidget(_lbl)
        self.cb_pip_rot = QtWidgets.QComboBox()
        self.cb_pip_rot.addItems(["180° (相机倒装转正)", "0° (原始朝向)", "90°", "270°"])
        self.cb_pip_rot.setCurrentIndex(0)                # 默认 180°: 相机总是自己翻转
        self.cb_pip_rot.setToolTip("只影响实时预览的**显示朝向** (相机倒装时转正看清现场)\n"
                                   "标定框仍按原始帧坐标存档; 「📸 抓当前实时帧」抓的也是原始朝向")
        self.cb_pip_rot.currentIndexChanged.connect(self._on_pip_rot_changed)
        _rotrow.addWidget(self.cb_pip_rot)
        pipcol.addLayout(_rotrow)
        self.lbl_pip_meta = QtWidgets.QLabel("")
        self.lbl_pip_meta.setObjectName("ph")
        self.lbl_pip_meta.setWordWrap(True)
        pipcol.addWidget(self.lbl_pip_meta)
        panes.addLayout(pipcol, 1)
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
        # 📌 真值 1Hz 刷新 (老倪 2026-09-17: 训练要有光模块位置/距离 → 面板要看得见)
        self._last_truth = None
        self._truth_timer = QtCore.QTimer(self)
        self._truth_timer.setInterval(1000)
        self._truth_timer.timeout.connect(self._refresh_truth)
        self._truth_timer.start()
        self._chain_state = ""
        self._chain_stopped = False      # 手动「⏹ 停止链路」后不自动重连
        self._recovering = False
        self._stale_since = None
        self._last_recover = time.monotonic()  # 给首次拉起 20s 宽限, 别和启动线程抢
        self._last_show_ensure = time.time()
        self._closed = False
        QtCore.QTimer.singleShot(200, self._start_source)

    # ── 源管理 ──────────────────────────────────────────────────────────
    def _placeholder_rgb(self, lines, w=640, h=480):
        """合成"无帧/占位"画面 (深底 + 文字)

        ⚠️ 2026-09-17 老倪: 「没连真机, 选了真机还是放 metaworld 视频」—— 原因是切源时
        **上一路画面残留在控件里** (真机路径只在帧文件签名变化时才重画; 没新帧就一直是旧图)。
        占位画面让"当前源没数据"一眼可见, 不再靠旧画面冒充 (老倪红线: 不拿旧图冒充实时)。
        """
        img = QtGui.QImage(w, h, QtGui.QImage.Format_RGB888)
        img.fill(QtGui.QColor("#0d1117"))
        p = QtGui.QPainter(img)
        try:
            y = 52
            for i, ln in enumerate(lines):
                f = p.font()
                f.setPointSize(13 if i == 0 else 10)
                f.setBold(i == 0)
                p.setFont(f)
                p.setPen(QtGui.QColor("#f0883e") if i == 0 else QtGui.QColor("#c9d1d9"))
                p.drawText(QtCore.QRect(24, y, w - 48, 320),
                           QtCore.Qt.TextWordWrap | QtCore.Qt.AlignTop, ln)
                y += 34 + 17 * int(len(ln) / 58)
                if y > h - 50:
                    break
        finally:
            p.end()
        stride = img.bytesPerLine()
        buf = img.constBits()
        buf.setsize(stride * h)
        arr = np.frombuffer(bytes(buf), np.uint8).reshape(h, stride)[:, : w * 3].reshape(h, w, 3)
        return np.ascontiguousarray(arr)

    def _show_placeholder(self, lines, tag="waiting"):
        """显示占位画面 (清框: 上一路的框属于上一路的帧坐标系, 不能跨源残留)"""
        try:
            self._rgb = self._placeholder_rgb(lines)
            self._view_tag = tag
            for _wdg in (self.w_orig, self.w_rot):
                _wdg.set_boxes([])
            self._paint_frames()
        except Exception:                                                  # noqa: BLE001
            pass

    def _reset_view_for_source(self, source):
        """切换输入源 → 清掉上一路画面/签名/框, 并立刻给出新源占位提示

        (原来只切链路不切画面: 从仿真切到真机, 屏上还挂着 metaworld 的画面,
         正好被误读成"选了真机却在放仿真视频")
        """
        self._last_sig = None
        self._pending_sig = None
        self._real_last_fresh = 0.0
        self._stale_since = None
        if source == "real":
            self._show_placeholder([
                "🎥 真机源 · 等 Orin 帧 …",
                "通道: Orin 取帧 + JPEG → ROS2 srv /zmax/live_frame → 本机 Docker 客户端 → 本窗口",
                "真机未连接 / Orin srv 未起 / D405 被占用时, 这里会一直显示本提示,"
                " 既不显示旧帧也不显示仿真画面",
            ], tag="waiting-real")
        elif source == "usbcam":
            self._show_placeholder([
                "💻 本机摄像头 · 等第一帧 …",
                f"设备 {USBCAM_DEV} (内置 UVC, 可改 ZMAX_USBCAM_DEV=/dev/videoN)",
                "这一路直读本机摄像头, 不经 Orin/Docker — 没连真机也能采真像素做标定/YOLO",
            ], tag="waiting-usbcam")
        else:
            self._show_placeholder([
                "🧪 仿真源 · 等 metaworld 渲染帧 …",
                "点 ▶运行 后本窗口自动跟随引擎实况帧 (与 detect_3d 同一帧)",
                "引擎没在跑时给的是静止初始帧, 状态栏会如实标注 (不假动)",
            ], tag="waiting-sim")

    def _switch(self, _i):
        self._stop_source()
        self._start_source()

    def _start_source(self):
        # ⚠️ 幂等: 先收掉可能在跑/被孤立的采集线程。
        #   实测踩坑: __init__ 的 singleShot(200ms) 与用户手切下拉可能各触发一次 _start_source
        #   → 旧 _CamGrabber 被覆盖成孤儿, 线程不停 → **UVC 设备被永久占用**, 之后任何一路都"打不开摄像头"。
        if self._sim is not None:
            self._sim.stop_flag = True
            self._sim = None
        if self._cam is not None:
            _old = self._cam
            _old.stop_flag = True
            self._cam = None
            try:
                _old.join(timeout=1.5)          # 等它 release 设备
            except Exception:                                                # noqa: BLE001
                pass
        _idx = self.cb.currentIndex()
        if _idx == 0:
            self.source = "real"
            self._set_annot_root("real")
            self._reset_view_for_source("real")     # 🖼 清掉上一路画面 (不残留仿真帧)
            self._stale_since = None
            self._last_recover = time.monotonic()
            self.btn.setEnabled(True)
            t = threading.Thread(target=self._ensure_chain_bg, daemon=True)
            t.start()
        elif _idx == 1:
            self.source = "sim"
            self._set_annot_root("sim")
            self._reset_view_for_source("sim")      # 🖼 清掉上一路画面 (不残留真机帧)
            self.btn.setEnabled(False)
            self._sim = _SimGrabber(self._q, self.chk.isChecked())
            self._sim.start()
            _engine_viewer_wants(True)      # 🎥 告诉引擎"有窗口在看实况" (非视觉档也节流渲染)
            self._log_line("仿真源已启动 (metaworld corner2; ▶运行 中自动跟随引擎实况帧)")
        else:
            # 💻 本机内置摄像头 (UVC 直读) — 无 Orin/Docker 也能出真像素, 用于标定/YOLO 域适应
            self.source = "usbcam"
            self._set_annot_root("usbcam")
            self._reset_view_for_source("usbcam")
            self.btn.setEnabled(False)
            _cv2 = None
            try:                            # ⚠️ 主线程 import cv2 (不在 worker 线程首导)
                import cv2 as _cv2m                                          # noqa: PLC0415
                _cv2 = _cv2m
            except Exception as e:                                           # noqa: BLE001
                self._log_line(f"⚠️ cv2 不可用 ({type(e).__name__}: {e}) → 摄像头源起不来")
            self._cam = _CamGrabber(self._q, USBCAM_DEV, USBCAM_FPS, cv2=_cv2)
            self._cam.start()
            self._log_line(f"💻 本机摄像头源已启动 ({USBCAM_DEV}, MJPG 1280x720 @{USBCAM_FPS}fps; "
                           f"数据根 {self.annot_root})")

    def _set_annot_root(self, source):
        """输入源切换 → 数据根/会话/类别表跟着切 (仿真 peg·hole·hand ‖ 真机 optical_module 分开存)"""
        root = yad.ensure_layout(yad.root_for(source), yad.default_classes_for(source))["root"]
        self._annot_source = source
        if root != self.annot_root:
            self.annot_root = root
            self._session = yad.session_name(yad.session_tag_for(source))
            self._reload_classes()
            self._log_line(f"数据根随输入源切换 → {root} · 会话 {self._session} · 类别 {yad.load_classes(root)}")
        self._refresh_data_label()

    def _stop_source(self):
        if self._sim is not None:
            self._sim.stop_flag = True
            self._sim = None
            _engine_viewer_wants(False)     # 🎥 窗口不看了 → 引擎恢复零开销 (非视觉档不再渲染)
        if self._cam is not None:                                       # 💻 摄像头线程收口
            self._cam.stop_flag = True
            _ct = self._cam
            self._cam = None
            try:
                _ct.join(timeout=1.5)      # 等它把设备 release 掉 (UVC 独占: 不等会导致切回时"打不开")
            except Exception:                                            # noqa: BLE001
                pass
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
            self._last_recover = time.monotonic()
            threading.Thread(target=self._ensure_chain_bg, daemon=True).start()

    def _screens(self):
        """当前**所有**屏幕的可用区域 (多屏=虚拟桌面)。
        ⚠️ 判越界必须遍历全部屏 —— 只看 primaryScreen 会把副屏当成"屏幕外"。"""
        out = []
        try:
            for s in QtWidgets.QApplication.screens():
                ag = s.availableGeometry()
                if ag.width() > 0 and ag.height() > 0:
                    out.append(ag)
        except Exception:                                                  # noqa: BLE001
            pass
        return out

    @staticmethod
    def _visible_ratio(r, screens):
        """窗口矩形落在所有可用屏幕内的面积占比"""
        area = max(1, r.width() * r.height())
        vis = 0
        for ag in screens:
            i = r.intersected(ag)
            if i.width() > 0 and i.height() > 0:
                vis += i.width() * i.height()
        return vis / area

    def _clamp_to_screen(self, silent=True):
        """窗口真跑到**所有屏幕之外** (拔外接屏 / 换分辨率) 才拉回可见范围。

        ⚠️ 2026-09-17 老倪: 「窗口拖到扩展屏就自己跳回笔记本屏」的根因 —— 原实现拿
        primaryScreen() (eDP-1 1920x1200) 当唯一边界, 而 _tick 每 5s 会调它一次
        (见 _tick: `if time.time() - self._last_clamp > 5.0`), 于是窗口被拖到 HDMI
        (x≥1920) 就被判"越界"→ setGeometry 拽回主屏, 实测 t=5s 跳回 (x=2332→586)。
        修法: ①按全部屏幕判可见性 —— 在任一屏可见 ≥40% 就完全不动 (拖到副屏=完全可见, 不干预)
              ②真越界时拉回**离窗口中心最近的屏** (拔掉 HDMI 后该屏区域消失 → 回 eDP, 原功能不丢)
        """
        try:
            screens = self._screens()
            if not screens:
                return False
            r = QtCore.QRect(self.x(), self.y(), self.width(), self.height())
            if self._visible_ratio(r, screens) >= 0.4:
                return False                     # 在多屏桌面上可见 → 用户放哪就是哪
            c = r.center()
            target = min(screens, key=lambda ag: (ag.center().x() - c.x()) ** 2
                         + (ag.center().y() - c.y()) ** 2)
            w = min(self.width(), max(700, target.width() - 40))
            h = min(self.height(), max(460, target.height() - 40))
            x = min(max(self.x(), target.x()), target.x() + max(0, target.width() - w))
            y = min(max(self.y(), target.y()), target.y() + max(0, target.height() - h))
            if (w, h, x, y) != (self.width(), self.height(), self.x(), self.y()):
                self.setGeometry(x, y, w, h)
                if not silent:
                    self._log_line(f"窗口在所有屏之外 → 拉回最近屏: ({x},{y}) {w}x{h} "
                                   f"(屏 {target.width()}x{target.height()} @{target.x()},{target.y()})")
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
        """断流自愈: Orin 节点 25s 无调用自退 / Docker 客户端被杀 → 自动重连 (节流 20s; 手动停止则不动)

        🩹 2026-09-18 时钟回拨事故: 全部用单调钟 —— 原来 time.time() 差值在 NTP 回拨 8h 后
        变负, 于是"无新帧 6s → 自动重连"永远不触发 (画面冻住且无人救), 正是这次真机图像
        不是实时的第二重原因。
        """
        if self._chain_stopped or self._recovering:
            return
        now = time.monotonic()
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

    def _mirror_sel(self, src, dst, idx):
        """选中项跨窗同步 (只同步索引: 框集合本来就共享, 重建反而会打断拖拽/递归)"""
        if getattr(self, "_mirroring", False):
            return
        self._mirroring = True
        try:
            if dst.selected() != idx:
                dst._sel = idx
                dst.update()
        finally:
            self._mirroring = False

    def _active_pane(self):
        """当前操作目标窗: 谁有选中框就作用于谁 (都没选中 → 左窗, 保持旧行为)"""
        for w in (self.w_rot, self.w_orig):
            if w.selected() >= 0:
                return w
        return self.w_orig

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
        """把当前帧同时推给两个子窗口 (各自按自己的 rot_deg 显示)

        🎯 感知模式开 → **显示副本**上叠加检测框 (self._dets); 存档/标定永远用 self._rgb_raw 原始像素
        (框不会烧进训练图 —— 这是加感知叠加时必须守的纪律)。
        """
        if self._rgb is None:
            return
        _disp = self._rgb
        if (getattr(self, "btn_percept", None) is not None and self.btn_percept.isChecked()
                and getattr(self, "_dets", None)):
            _disp = _render_boxes(self._rgb, self._dets)
        self.w_orig.set_frame_rgb(_disp)
        if self.chk_rot.isChecked():
            self.w_rot.set_frame_rgb(_disp)
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
        # 🛡 2026-09-18 槽体总兜底 (同 studio.py「点一下就崩」通式: Qt 定时器/槽里未捕获异常
        #   → qFatal → 整个控制台进程中止, 且无弹窗)。刷新异常只记日志, 绝不冒泡。
        try:
            self._tick_inner()
        except Exception as _e:                                  # noqa: BLE001
            try:
                self._log_line(f"⚠️ 刷新异常 (已兜住, 窗口继续): {type(_e).__name__}: {_e}")
            except Exception:                                     # noqa: BLE001
                pass

    def _tick_inner(self):
        if time.monotonic() - getattr(self, "_last_clamp", 0) > 5.0:      # 抜屏/换分辨率后 5s 内自动拉回
            self._last_clamp = time.monotonic()
            self._clamp_to_screen(silent=False)
        if self.source == "real":
            self._tick_real()
        elif self.source == "usbcam":
            self._tick_cam()                        # 💻 本机摄像头 (队列帧)
        else:
            self._tick_sim()
        # 🎯 感知模式看门狗 (冻结帧/静止场景兜底; 实时性由"新帧即推理"那条路保证, 见各 _tick_*)
        #   ⚠️ 两个纪律: ①叠加在 paint 阶段 (换帧/冻结/标定都不会丢框) ②新帧到达时**先推理再画** (框与帧同拍)
        self._percept_refresh()
        # 📺 实时预览列: 冻结(标定)作业时持续显示现场; 未冻结时主画面本身就是实时 → 该列显式置空 (不摆旧图)
        if self._frozen:
            self._pip_update()
        else:
            _pip = getattr(self, "pip", None)
            if _pip is not None and getattr(self, "_pip_state", "") != "idle":
                self._pip_state = "idle"
                _pip.clear()
                _pip.setText("(未冻结: 主画面本身即实时)")
                if getattr(self, "lbl_pip_meta", None) is not None:
                    self.lbl_pip_meta.setText("冻结(标定)时才需要这一列")

    def _tick_cam(self):
        """💻 本机摄像头帧刷新 (UVC 队列帧; 与仿真同一条取帧路径, 只是来源不同)"""
        try:
            d = self._q.get_nowait()
        except queue.Empty:
            return
        if "err" in d:
            self.st.setText("⚠️ " + d["err"] + f"\n设备: {USBCAM_DEV} (可用 ZMAX_USBCAM_DEV 换)")
            return
        rgb = d["rgb"]
        h, w = rgb.shape[:2]
        if self._frozen:
            self._pending = rgb                    # 冻结(标定中): 攒着, 点「下一帧」再显示
        else:
            self._rgb_raw = rgb
            self._rgb = rgb
            self._view_tag = "usbcam"
            self._percept_refresh(force=True)          # 🎯 本帧先推理再画
            self._paint_frames()
        self._sim_fps_n += 1
        if time.time() - self._sim_fps_t >= 1.0:
            self._sim_fps = self._sim_fps_n / max(1e-6, time.time() - self._sim_fps_t)
            self._sim_fps_n, self._sim_fps_t = 0, time.time()
        info = d.get("info") or {}
        self._frame_meta = {"device": info.get("device"), "src": info.get("src"),
                            "seq": None, "age_s": 0.0, "ok": True, "stale": False}
        self.st.setText(f"💻 本机摄像头 (UVC 直读) · {w}x{h} · {self._sim_fps:.1f} FPS"
                        f"{'  🧊 已冻结(标定中)' if self._frozen else ''}\n"
                        f"设备: {info.get('device')} · {info.get('src')} (V4L2 只读, 不碰 Orin/Docker)\n"
                        f"口径: 与真机/仿真同路 (BGR→RGB), 可直接拖框标定 → 构建数据集 → 训 YOLO\n"
                        f"数据根: {self.annot_root} · 会话 {self._session} · 本窗已存 {self._n_saved} 张"
                        f" · 当前帧框 {len(self.w_orig.boxes())} 个\n"
                        f"双画面: 左=原始 (0°) · {('右=旋转 ' + str(self._rot_deg()) + '° (同一帧旋转)') if self.chk_rot.isChecked() else '右窗已关'}")

    # ── 🎯 感知模式 (老倪 2026-09-18) ───────────────────────────────────
    def _on_percept(self, on):
        """点「🎯 感知模式」→ 在当前输入图像上叠加感知结果 (bounding box)。"""
        self.chk.blockSignals(True)                 # 双向同步别名, 防递归
        try:
            self.chk.setChecked(bool(on))
        finally:
            self.chk.blockSignals(False)
        self._dets, self._percept_txt, self._dets_ts = [], "", 0.0
        self._percept_refresh(force=True)
        self._paint_frames()
        self._log_line(("🎯 感知模式开: 在当前输入图像上叠加感知结果 (真推理 bounding box)"
                        if on else "🎯 感知模式关: 恢复纯原始图像"))

    def _on_percept_alias(self, on):
        """旧「叠加 YOLO 框」勾选框 → 同步到感知模式按钮。"""
        if self.btn_percept.isChecked() != bool(on):
            self.btn_percept.blockSignals(True)
            try:
                self.btn_percept.setChecked(bool(on))
            finally:
                self.btn_percept.blockSignals(False)
            self._on_percept(bool(on))

    def _percept_weights(self):
        """按当前输入源选权重 (域不混): 真机 → 真机在役权重; 仿真/本机摄像头 → 仿真域权重。"""
        if self.source == "real":
            return _live_weights()
        p = os.path.join(REPO, "runs/detect/outputs/yolo_peg/peg_v1/weights/best.pt")
        return p if os.path.exists(p) else None

    def _percept_refresh(self, force: bool = False):
        """在当前**显示帧**上跑一次感知 (2.5Hz 节流) → self._dets / self._percept_txt。"""
        if getattr(self, "btn_percept", None) is None or not self.btn_percept.isChecked():
            self._dets, self._percept_txt = [], ""
            if getattr(self, "lbl_percept", None) is not None:
                self.lbl_percept.setText("")
            return
        now = time.time()
        # 硬地板上限: 即使 force (新帧立即推理, 保证"框跟帧同拍") 也最多 12Hz, 防 30fps 源把 GPU 打满
        if now - getattr(self, "_dets_ts", 0.0) < (0.08 if force else 0.4):
            return
        src = getattr(self, "_rgb_raw", None)
        if src is None:
            src = self._rgb
        if src is None:
            return
        self._dets_ts = now
        w = self._percept_weights()
        dets = _detect_with(w or "", src)
        self._dets = dets
        wid = os.path.basename(w) if w else "?"
        if not dets:
            self._percept_txt = f"🎯 感知({wid}): 无检出"
        else:
            top = max(dets, key=lambda d: d["conf"])
            self._percept_txt = (f"🎯 感知({wid}): {len(dets)} 框 · 最高 {top['cls']} "
                                 f"conf={top['conf']:.2f} · box={[round(v) for v in top['xyxy']]}")
        if getattr(self, "lbl_percept", None) is not None:
            self.lbl_percept.setText(self._percept_txt)

    def _live_real_frame(self):
        """🎯 真机源「当前新鲜帧」的**单一入口** (实时刷新 / 实时预览 / 保存并下一帧 共用同一口径)。

        ① srv 落盘新鲜 (meta.ok ∧ 非 stale ∧ age ≤ 5s) → live_frame.jpg (带 seq/编码耗时)
        ② 否则 Docker tap 落盘新鲜帧 (cam_rs → cam_fp → cam_latest, **L2 吃的就是这条**)
        ③ 都不新鲜 → 返回 (None, 原因, None) —— **绝不回退历史帧** (红线: 不用旧图冒充实时)
        返回: (rgb, 来源标签, 帧龄秒) 或 (None, 原因字符串, None)
        """
        meta = None
        if os.path.isfile(LIVE_META):
            try:
                meta = json.load(open(LIVE_META, encoding="utf-8"))
            except Exception:                                              # noqa: BLE001
                meta = None
        _age_s = meta.get("age_s") if isinstance(meta, dict) else None
        # 🩹 2026-09-18: age_s 必须落在 [0, 5]s —— 负龄 = 时钟回拨 (mtime/戳在未来), 不是新鲜
        _age_ok = (_age_s is None) or (0.0 <= float(_age_s) <= 5.0)
        if (os.path.isfile(LIVE_JPG) and isinstance(meta, dict) and meta.get("ok")
                and not meta.get("stale") and _age_ok):
            rgb = rgb_from_file(LIVE_JPG)
            if rgb is not None:
                return rgb, "srv 落盘 live_frame.jpg (Orin /zmax/live_frame)", (float(_age_s) if _age_s is not None else 0.0)
        pick = self._pick_real_file()
        if pick is not None:
            rgb = rgb_from_file(pick[0])
            if rgb is not None:
                return rgb, os.path.basename(pick[0]) + " (Docker tap · 与 L2 同源)", pick[2]
        _why = "srv 不可达"
        if isinstance(meta, dict) and meta.get("reason"):
            _why = f"srv: {meta.get('reason')}"
        return None, _why + f" 且无新鲜落盘帧 (候选: " + " · ".join(
            getattr(self, "_real_cand_status", []) or ["(未扫描)"]) + ")", None

    def _live_frame_any(self):
        """当前源可选用的「最新实时帧」—— PiP 实时预览与「📸 抓当前实时帧」共用。

        真机 → `_live_real_frame()` (文件链); 仿真/本机摄像头 → 冻结期间 `_tick_*` 攒下的
        `self._pending` (最新队列帧, 不额外消费队列)。返回 (rgb, 来源标签, 帧龄秒) | (None, 原因, None)。
        """
        if self.source == "real":
            return self._live_real_frame()
        if self._pending is not None:
            return self._pending, ("metaworld 引擎实况帧" if self.source == "sim" else "本机摄像头 UVC"), 0.0
        return None, ("仿真源暂无新帧 (引擎/采集线程未产出)" if self.source == "sim"
                      else "本机摄像头暂无新帧"), None

    def _pip_rot_deg(self) -> int:
        """实时预览的显示翻转角 (只影响显示; 相机倒装时用来转正)。"""
        cb = getattr(self, "cb_pip_rot", None)
        if cb is None:
            return 180
        return {"0° (原始朝向)": 0, "90°": 90, "180° (相机倒装转正)": 180, "270°": 270}.get(
            cb.currentText(), 180)

    @staticmethod
    def _rot_rgb(rgb, deg: int):
        """按角度旋转 RGB 数组 —— 与 YoloLabelWidget 的 Qt 旋转同向 (顺时针为正)。"""
        if not deg:
            return rgb
        k = (-int(deg) // 90) % 4          # Qt QTransform().rotate(deg) 是顺时针 → np.rot90 逆时针, 取反
        return np.ascontiguousarray(np.rot90(rgb, k))

    def _on_pip_rot_changed(self, *_a):
        """翻转角变了 → 立刻重画实时预览 (不等下一节流窗)。"""
        self._pip_ts = 0.0
        self._pip_update()

    def _pip_update(self):
        """📺 冻结(标定)时把**最新实时帧**画进实时预览小窗 —— 标定作业时也能看见现场。

        老倪 2026-09-18: 「保存并下一帧时看不到当前实时画面, 怎么办?」标定必须在冻结帧上画框,
        但作业期间必须能看见现场, 才能判断"这一帧值不值得标"。刷新 ~5Hz (节流, 不抢标定流畅度)。
        """
        pip = getattr(self, "pip", None)
        if pip is None:
            return
        now = time.time()
        if now - getattr(self, "_pip_ts", 0.0) < 0.2:
            return
        self._pip_ts = now
        self._pip_state = "live"
        rgb, label, age = self._live_frame_any()
        if rgb is None:
            pip.setText("⚠️ 无实时帧\n" + str(label)[:120])
            self._pip_meta = None
        else:
            _deg = self._pip_rot_deg()
            rgb = self._rot_rgb(rgb, _deg)          # 🔄 相机倒装 → 显示转正 (只影响显示)
            qimg = QtGui.QImage(np.ascontiguousarray(rgb).data, rgb.shape[1], rgb.shape[0],
                                rgb.shape[1] * 3, QtGui.QImage.Format_RGB888)
            pm = QtGui.QPixmap.fromImage(qimg).scaled(pip.width(), pip.height(),
                                                      QtCore.Qt.KeepAspectRatio,
                                                      QtCore.Qt.SmoothTransformation)
            pip.setPixmap(pm)
            self._pip_meta = {"label": label, "age": age, "rot": _deg}
            pip.setToolTip(f"来源: {label} · 帧龄 {age:.1f}s · 显示翻转 {_deg}° (相机倒装转正用)")
        if getattr(self, "lbl_pip_meta", None) is not None:
            self.lbl_pip_meta.setText(
                "(无实时帧)" if self._pip_meta is None
                else f"{self._pip_meta['label']} · 帧龄 {self._pip_meta['age']:.1f}s"
                     f" · 翻转 {self._pip_meta.get('rot', 0)}°")

    def _grab_live_frame(self):
        """📸 用**当前实时帧**替换标定画面 (老倪: 冻结作业时也想直接抓现场那一帧来标)。

        口径: 与实时预览同一入口; 换帧 → 清掉旧框 (框属于旧帧的像素坐标, 不能跨帧留);
        抓不到新鲜帧就**明说原因不换** (不给旧图)。
        """
        rgb, label, age = self._live_frame_any()
        if rgb is None:
            self._log_line("⚠️ 抓当前实时帧失败: " + str(label) + " → 保持当前帧不动")
            return False
        self.w_orig.clear_boxes()
        self.w_rot.clear_boxes()
        self._rgb_raw = rgb
        self._rgb = rgb
        self._pending = None
        self._frozen = True
        self._paint_frames()
        self._log_line(f"📸 已用当前实时帧替换标定画面: {label} · 帧龄 {age:.1f}s (旧框已清, 请重新圈选)")
        return True

    def _pick_real_file(self, fresh_s: float | None = None):
        """真机图像候选链挑帧: 返回 (path, label, age_s) 中最新鲜的**新鲜**帧; 无 → None。

        与 L2 侧同源 (ss_yolo_on_real.py CAND: cam_rs → cam_fp → cam_latest),
        新鲜度 = 文件 mtime 年龄 ≤ fresh_s (默认 ZMAX_VIEWER_FILE_FRESH_S=10s)。
        另: 所有候选的逐条状态 (缺文件/不新鲜) 记进 self._real_cand_status, 供占位画面如实列出。
        """
        fresh_s = REAL_FILE_FRESH_S if fresh_s is None else fresh_s
        now = time.time()
        best, status = None, []
        for name, label in REAL_FILE_CANDS:
            p = os.path.join(SHARED, name)
            if not os.path.isfile(p):
                status.append(f"{name}: 缺文件")
                continue
            try:
                age = now - os.path.getmtime(p)
            except OSError:
                status.append(f"{name}: 读不到时间戳")
                continue
            if age < -1.0:
                # 🩹 2026-09-18 时钟回拨事故: 本机 NTP 把钟回拨 8h 后, 旧帧文件 mtime 落在
                #   未来 → age 为负. 任何 `age <= 阈值` 判据都会把**静止旧帧**判成实时帧
                #   (正是"画面不实时了但窗口还说新鲜"的根因) → 负龄一律拒用, 如实标注。
                status.append(f"{name}: ⏰ 时钟异常 (mtime 在未来 {abs(age):.0f}s) → 拒用")
                continue
            if age <= fresh_s:
                status.append(f"{name}: ✅ 新鲜 {age:.1f}s")
                if best is None or age < best[2]:
                    best = (p, label, age)
            else:
                status.append(f"{name}: ⚠️ 旧帧 {age:.0f}s")
        self._real_cand_status = status
        return best

    def _tick_real_fallback(self, stale_gap_s: float, meta: dict | None) -> bool:
        """srv 真机帧不可用/不新鲜时的**同源回退**: 用 Docker tap 落盘帧 (L2 吃的那一条)。

        返回 True = 已上屏 (调用方直接 return); False = 无可用新鲜帧 (调用方走占位/自愈)。
        纪律不变: 只上新鲜帧 (文件 mtime 年龄 ≤ REAL_FILE_FRESH_S), 旧帧绝不冒充实时。
        """
        pick = self._pick_real_file()
        if pick is None:
            return False
        p, label, age = pick
        try:
            st = os.stat(p)
            sig = (st.st_mtime_ns, st.st_size)
        except OSError:
            return False
        if sig != self._last_sig:
            self._last_sig = sig
            if not self._frozen:
                rgb = rgb_from_file(p)
                if rgb is None:
                    return False
                self._rgb_raw = rgb
                self._rgb = rgb
                self._view_tag = "real"
                self._percept_refresh(force=True)      # 🎯 本帧先推理再画 (实时跟随)
                self._paint_frames()
            else:
                self._pending_sig = sig
        self._real_last_fresh = time.monotonic()
        self._stale_since = None
        self._frame_meta = {"device": "D405 (Docker tap 只读订阅)", "seq": None,
                            "age_s": round(age, 1), "src": label, "stale": False, "ok": True}
        self.st.setText(
            f"✅ 实时真机帧 (与 L2 同源 · Docker tap 落盘){'  🧊 已冻结(标定中)' if self._frozen else ''}\n"
            f"来源: {label}\n"
            f"文件: {os.path.basename(p)} · 帧龄 {age:.1f}s (新鲜阈值 {REAL_FILE_FRESH_S:.0f}s)\n"
            f"srv 通道 (/zmax/live_frame): {str((meta or {}).get('reason') or '不可达/无 meta')}"
            f" → 已自动回退到话题落盘帧 (不拿旧图冒充)\n"
            f"标定: 数据根 {self.annot_root} · 会话 {self._session} · 本窗已存 {self._n_saved} 张"
            f" · 当前帧框 {len(self.w_orig.boxes())} 个\n"
            f"通道: Orin 相机 → ROS2 话题 → 本机 Docker tap 落盘 → 本窗口 (L2 读同一文件)")
        return True

    def _tick_real(self):
        meta = None
        if os.path.isfile(LIVE_META):
            try:
                meta = json.load(open(LIVE_META, encoding="utf-8"))
            except Exception:                                              # noqa: BLE001
                meta = None
        _stale_gap_s = 10.0        # 超过这么久没有新鲜真机帧 → 换占位画面 (不拿旧图冒充实时)
        # 🩹 2026-09-18: 单调钟 —— 回拨后 time.time() 差值变负会让"久无新鲜帧"永不成立
        _since_fresh = time.monotonic() - getattr(self, "_real_last_fresh", 0.0)
        if not os.path.isfile(LIVE_JPG):
            # 🩹 2026-09-18: srv 落盘文件都没有 → 先试 Docker tap 落盘帧 (与 L2 同源), 有就上屏
            if self._tick_real_fallback(_stale_gap_s, meta):
                return
            self.st.setText("⚠️ 还没有帧文件 " + LIVE_JPG + "\n"
                            "   链路状态: " + (self._chain_state or "启动中…") +
                            "\n   (Orin 侧 srv 未起 / Docker 客户端未起 / D405 UVC 被占用 都可能)\n"
                            "   同源回退帧: " + " · ".join(getattr(self, "_real_cand_status", []) or ["(未扫描)"]))
            if not self._frozen and _since_fresh > _stale_gap_s:
                self._show_placeholder([
                    "🎥 真机源 · 无帧 (真机未连接)",
                    "srv 帧文件: " + LIVE_JPG + " 不存在",
                    "链路状态: " + (self._chain_state or "启动中…"),
                    "同源回退帧 (Docker tap): " + (" · ".join(getattr(self, "_real_cand_status", []) or ["(未扫描)"])),
                    "排查: Orin 侧 srv 未起 / Docker 客户端未起 / D405 UVC 被占用",
                    "本窗口不会用旧帧或仿真帧占位",
                ], tag="no-frame-real")
            self._maybe_recover()
            return
        # 新鲜度判决先做 (决定"能不能拿这个文件画面")
        ok = bool(meta and meta.get("ok"))
        age = meta.get("age_s") if meta else None
        stale = bool(meta and meta.get("stale")) or (age is not None and age > 5.0)
        _fresh = ok and not stale
        if not _fresh:
            # 🩹 srv 不新鲜/不可达 → 走 Docker tap 落盘帧 (真机图像流没断, L2 一直在吃这条)
            if self._tick_real_fallback(_stale_gap_s, meta):
                return
        try:
            st = os.stat(LIVE_JPG)
            sig = (st.st_mtime_ns, st.st_size)
            if _fresh and sig != self._last_sig:       # ⚠️ 只有新鲜帧才允许上屏
                self._last_sig = sig
                if not self._frozen:
                    rgb = rgb_from_file(LIVE_JPG)
                    if rgb is not None:
                        self._rgb_raw = rgb
                        self._rgb = rgb
                        self._view_tag = "real"
                        # 🎯 先对**这一帧**跑感知再画 → 框与帧同拍 (老倪 08:2x: 「移动光模块, 框要跟着走」)
                        self._percept_refresh(force=True)
                        self._paint_frames()
                else:
                    self._pending_sig = sig
        except Exception:                                                  # noqa: BLE001
            pass
        if _fresh:
            self._real_last_fresh = time.monotonic()
            self._stale_since = None
        else:
            self._maybe_recover()
            if not self._frozen and _since_fresh > _stale_gap_s:
                _last = ""
                try:
                    _last = time.strftime("%H:%M:%S", time.localtime(os.stat(LIVE_JPG).st_mtime))
                except Exception:                                          # noqa: BLE001
                    pass
                self._show_placeholder([
                    "🎥 真机源 · 无新帧 (真机未连接 / 链路不通)",
                    "原因: " + str((meta or {}).get("reason") or ("缺 meta 文件 " + LIVE_META)),
                    f"最后真机帧: {_last} ({int(_since_fresh)}s 前, {int((meta or {}).get('age_s') or 0)}s 龄)"
                    if _last else "本地帧文件没有可用时间戳",
                    "同源回退帧 (Docker tap, L2 读同一文件): "
                    + (" · ".join(getattr(self, "_real_cand_status", []) or ["(未扫描)"] )),
                    "通道: Orin 取帧 + JPEG → /zmax/live_frame → 本机 Docker → 本窗口",
                    "本窗口只显示新鲜真机帧; 旧帧/仿真帧都不会拿来顶替",
                ], tag="stale-real")
        if not meta:
            self.st.setText(f"⚠️ 有帧文件但缺 meta ({LIVE_META}) → 无法判定新鲜度")
            self._maybe_recover()
            return
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
            self._rgb_raw = rgb
            self._rgb = rgb
            self._percept_refresh(force=True)          # 🎯 本帧先推理再画
            self._paint_frames()
        self._sim_fps_n += 1
        if time.time() - self._sim_fps_t >= 1.0:
            self._sim_fps = self._sim_fps_n / (time.time() - self._sim_fps_t)
            self._sim_fps_n, self._sim_fps_t = 0, time.time()
        self._frame_meta = {"device": d["info"].get("device"), "src": d["info"].get("src"),
                            "seq": None, "age_s": 0.0, "ok": True, "stale": False}
        self._view_tag = "sim-engine" if d["info"].get("engine") else "sim-idle"
        _eng = bool(d["info"].get("engine"))
        if _eng:
            self.st.setText(f"🎥 引擎实况帧 · 与 ▶运行 同步 (metaworld corner2) · {w}x{h}"
                            f" · step={d['info'].get('step')} · 帧龄 {d['info'].get('age', 0):.2f}s"
                            f"{'  🧊 已冻结(标定中)' if self._frozen else ''}\n"
                            f"来源: {d['info'].get('src')} · {d['info'].get('device')}\n"
                            f"口径: 与引擎 detect_3d 同一帧 (引擎每步 ~0.5-1s, 窗口 15Hz 取最新)\n"
                            f"标定: 数据根 {self.annot_root} · 会话 {self._session} · 本窗已存 {self._n_saved} 张"
                            f" · 当前帧框 {len(self.w_orig.boxes())} 个\n"
                            f"双画面: 左=原始 (0°) · {('右=旋转 ' + str(self._rot_deg()) + '° (同一帧旋转)') if self.chk_rot.isChecked() else '右窗已关'}")
            return
        self.st.setText(f"🧪 仿真渲染帧 (metaworld corner2) · {w}x{h} · {self._sim_fps:.1f} FPS"
                        f"{'  🧊 已冻结(标定中)' if self._frozen else ''}\n"
                        f"设备: {d['info'].get('device')}\n"
                        f"⚠️ 引擎未在跑 → 这是**静止的初始帧** (对齐器 env 只 reset 不 step); "
                        f"点 ▶运行 后本窗口自动切到引擎实况\n"
                        f"双画面: 左=原始 (0°) · {('右=旋转 ' + str(self._rot_deg()) + '° (同一帧旋转)') if self.chk_rot.isChecked() else '右窗已关'}\n"
                        f"标定: 数据根 {self.annot_root} · 会话 {self._session} · 本窗已存 {self._n_saved} 张 · 当前帧框 {len(self.w_orig.boxes())} 个\n"
                        f"用途: 与真机帧做口径对照 (朝向 rot90 / 通道 / 内参 / 深度)")

    # ── 标定 ────────────────────────────────────────────────────────────
    _ANNOT_BTNS = ("💾 保存标注", "⏭ 保存并下一帧", "↩ 撤销", "🗑 删选中", "✖ 清空框",
                   "🧊 冻结/▶实时", "📦 构建数据集", "🔍 数据体检", "🚀 训练 YOLO", "🏷 改选中类别",
                   "📂 数据目录", "＋新类别", "🗑 丢弃当前帧", "🗑 清空本会话")

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
            self._rgb_raw = rgb
            self._rgb = rgb
        else:
            # 🐛 2026-09-18 老倪: 「点『保存并下一帧』怎么显示以前的历史图像?」
            #   根因: 这里原来**无条件读 LIVE_JPG** (srv 落盘 live_frame.jpg), 而该通道不可达时
            #   那是一张 17 小时前的历史帧 → 标定时把昨天的旧图当"下一帧"标 = 直接污染训练数据。
            #   现改为走**真机当前新鲜帧的单一入口** `_live_real_frame()` (与实时预览/实时刷新同口径)。
            rgb, _src, _age = self._live_real_frame()
            if rgb is None:
                self._log_line("⚠️ 取下一帧失败: " + str(_src) + " → 保持当前帧; **不回退历史帧** "
                               "(旧图会污染标定数据)。候选状态: "
                               + " · ".join(getattr(self, "_real_cand_status", []) or ["(未扫描)"]))
                return False
            self._rgb_raw = rgb
            self._rgb = rgb
            self._percept_refresh(force=True)          # 🎯 新帧立刻推理 → 框跟着换
            self._log_line(f"取下一帧: {_src} · 帧龄 {_age:.1f}s (只取新鲜帧, 旧帧不顶替)")
        self._frozen = True
        self._paint_frames()
        return True

    def _reload_classes(self):
        names = yad.load_classes(self.annot_root)
        cur = self.cb_cls.currentText().strip()
        self.cb_cls.blockSignals(True)
        self.cb_cls.clear()
        self.cb_cls.addItems(names)
        self.cb_cls.setCurrentText(cur if cur in names else (names[0] if names else "peg"))
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
        w = self._active_pane()
        if w.selected() < 0:
            self._log_line("没有选中框 (先在框内点一下选中, 再点这个按钮)")
            return
        w.set_selected_class(txt)
        self._sync_boxes(w, self.w_orig if w is self.w_rot else self.w_rot, force=True)
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
        kind = "🧪仿真" if getattr(self, "_annot_source", "real") == "sim" else "🎥真机"
        self.lbl_data.setText(f"{kind}数据根 {root} · {n_img} 张 / {n_box} 框 · 类别 {names}")

    def _save_annot(self, next_frame=False):
        if self._rgb is None:
            QtWidgets.QMessageBox.information(self, "还没有画面", "当前窗口没有可保存的帧 (链路未就绪?)")
            return None
        boxes = self.w_orig.boxes_px()
        cls0 = self.cb_cls.currentText().strip() or "optical_module"
        yad.add_class(self.annot_root, cls0)
        fm = self._frame_meta or {}
        try:
            # ⚠️ 存档必须用**原始帧** (self._rgb_raw): 勾了「叠加 YOLO 框」时 self._rgb 上画过绿框,
            #   存进训练集会变成"框烧进像素"的脏数据 (标签本来就存坐标) —— 2026-09-18 加叠加时同步修。
            _save_rgb = getattr(self, "_rgb_raw", None)
            if _save_rgb is None or getattr(_save_rgb, "shape", None) != getattr(self._rgb, "shape", None):
                _save_rgb = self._rgb
            rec = yad.save_sample(self.annot_root, _save_rgb, boxes,
                                  device=fm.get("device") or "", seq=fm.get("seq"),
                                  ts=time.time(), src=f"{fm.get('src') or self.source}",
                                  session=self._session, annotator=self.ed_who.text().strip(),
                                  tag="d405" if self.source == "real" else "sim",
                                  extra={"frame_age_s": fm.get("age_s"), "ui": "yolo_input_viewer",
                                         "truth": self._truth_snapshot()})
        except Exception as e:                                             # noqa: BLE001
            QtWidgets.QMessageBox.warning(self, "保存失败", f"{type(e).__name__}: {e}")
            return None
        self._n_saved += 1
        self._last_saved = {"stem": rec.get("stem"), "session": rec.get("session")}   # 供「🗑 丢弃当前帧」定位
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

    def _truth_snapshot(self):
        """📌 真机位姿真值快照 (仿真源 → None)。保存样本与面板显示**共用这一个入口** —
        真值只有一个来源 (Orin /robot/tcp_pose → 采集容器落盘 → tools/real_truth.py), 不许各写一套。"""
        if self.source != "real":
            return None
        try:
            return rt.snapshot()
        except Exception as e:                                             # noqa: BLE001
            self._log_line(f"⚠️ 真值读取失败: {type(e).__name__}: {e}")
            return None

    def _refresh_truth(self):
        """📌 真值行 1Hz 刷新 —— 末端(手/头)/光模块 的 x y z · 距孔口 · 新鲜度。
        自解释: 每个数都带物理含义与坐标系; 拿不到的一律显示"— + 原因", 不拿旧值/默认值冒充 (老倪红线)。"""
        if self.source != "real":
            self.lbl_truth.setText("📌 真值: 当前是 "
                                   + ("💻 本机摄像头源" if self.source == "usbcam" else "仿真源")
                                   + " — 切到「🎥 真机 RealSense」才会读 Orin 位姿真值")
            return
        t = self._truth_snapshot()
        if not t or not t.get("tcp"):
            self.lbl_truth.setText("📌 真机真值: 读不到 (采集容器 ss-remote-tap 没在跑? 见 ~/zmax_ss_remote)")
            return
        self._last_truth = t
        seg, dist, notes = t.get("obs39_segments", {}), t.get("dist", {}), t.get("notes", {})

        def _v(a):
            return "—" if a is None else f"{float(a):+.4f}"

        fresh = "✅" if t.get("fresh") else "⚠️旧"
        txt = (f"📌 真机真值 base_link · 新鲜度 {t.get('age_s')}s{fresh}: "
               f"末端(手/头) x={_v(t['tcp'][0])} y={_v(t['tcp'][1])} z={_v(t['tcp'][2])} m")
        peg = seg.get("peg")
        txt += (f" · 光模块中心 x={_v(peg[0])} y={_v(peg[1])} z={_v(peg[2])}" if peg
                else f" · 光模块中心 —({notes.get('peg', '未标定')})")
        if dist.get("tcp_to_goal_m") is not None:
            txt += f" · 距孔口 {dist['tcp_to_goal_m'] * 1000:.1f} mm"
        else:
            txt += f" · 距孔口 —({notes.get('hole', '未示教几何')})"
        txt += f" · 关节{'✓' if t.get('joints') else '—'} · 姿态{'✓' if t.get('tcp_quat') else '—'}"
        self.lbl_truth.setText(txt)

    def _discard_current(self):
        """🗑 丢弃当前帧 — 把**刚保存的这张**样本从会话里删掉 (图+标注成对删, 不留孤儿)

        (2026-09-17 老倪: 「窗口上加 🗑 丢弃当前帧」— 以前删只能走命令行/文件管理器,
         只删图不删标注就留下孤儿标注, 之后 --build/训练/体检全报错。)
        """
        rec = getattr(self, "_last_saved", None)
        if not rec or not rec.get("stem"):
            self._log_line("🗑 丢弃当前帧: 这张还没保存过 — 先「💾 保存标注」再丢弃")
            QtWidgets.QMessageBox.information(self, "丢弃当前帧", "当前帧还没有保存过 (先「💾 保存标注」)。")
            return
        r = yad.delete_sample(self.annot_root, rec.get("session"), rec.get("stem"))
        self._n_saved = max(0, self._n_saved - 1)
        self._last_saved = None
        self.w_orig.clear_boxes()
        self.w_rot.clear_boxes()
        self._log_line(f"🗑 已丢弃 {rec['stem']}: 删除 {len(r['deleted'])} 个文件 {r['deleted']} (会话 {rec.get('session')})")
        self._refresh_data_label()

    def _clear_session(self):
        """🗑 清空本会话 — 删掉当前会话全部样本 (图+标注成对删), 弹确认后执行"""
        n = yad._session_n(self.annot_root, self._session)
        if n == 0:
            self._log_line(f"🗑 清空本会话: {self._session} 里没有样本")
            QtWidgets.QMessageBox.information(self, "清空本会话", f"会话 {self._session} 里没有样本。")
            return
        if QtWidgets.QMessageBox.question(
                self, "清空本会话",
                f"将删除会话「{self._session}」下全部 {n} 张样本 (图片 + 标注成对删), 不可恢复。\n\n继续?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No) != QtWidgets.QMessageBox.Yes:
            self._log_line("🗑 清空本会话: 已取消")
            return
        r = yad.clear_session(self.annot_root, self._session)
        self._last_saved = None
        self.w_orig.clear_boxes()
        self.w_rot.clear_boxes()
        self._log_line(f"🗑 已清空会话 {self._session}: 删除 {r['removed']} 个文件 (类别表未动)")
        self._refresh_data_label()

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
    """给画布右键菜单用: 复用窗口, 打开即显示实时原始输入流

    ⚠️ 2026-09-17 老倪: 复用旧窗口时必须把**输入源**也对齐 —— 窗口是单例 (_cur),
    原来只 raise_() 不管源, 于是"上次开的是真机窗口 → 这次画布在仿真也给你放现场视频"。
    """
    win = getattr(YoloInputViewer, "_cur", None)
    if win is not None:
        try:
            if not win.isVisible():
                win.show()
            # 源对齐: 0=真机 RealSense / 1=仿真 metaworld (setCurrentIndex 会触发 _switch 换源)
            # 💻 用户在窗口里手动选了「本机摄像头」→ 尊重手动选择, 菜单打开时不动它
            try:
                _want = _SRC_IDX.get(str(source), 0)
                _cur_is_cam = (getattr(win, "source", "") == "usbcam")
                if (not _cur_is_cam) and getattr(win, "cb", None) is not None \
                        and win.cb.currentIndex() != _want:
                    win.cb.setCurrentIndex(_want)
            except Exception:                                              # noqa: BLE001
                pass
            win.raise_()
            win.activateWindow()
            return win
        except Exception:                                                  # noqa: BLE001
            win = None
    win = YoloInputViewer(parent, module=module, source=source)
    YoloInputViewer._cur = win
    # 两个子窗口并排 ⇒ 默认宽度加倍; 屏幕放不下就按可用宽度收 (别出屏)
    w, h = 1320, 760
    ag = None
    try:
        _app = QtWidgets.QApplication
        # 🖥 2026-09-17 老倪: 子窗开在**主窗所在那块屏** (原按 primaryScreen → 主窗已拖到 HDMI,
        #   子窗还是永远弹在笔记本屏, 每次都要手拖)
        scr = None
        try:
            if parent is not None:
                c = parent.window().frameGeometry().center()
                scr = _app.screenAt(c) if hasattr(_app, "screenAt") else None
        except Exception:                                                  # noqa: BLE001
            scr = None
        if scr is None:
            scr = _app.primaryScreen()
        if scr is not None:
            ag = scr.availableGeometry()
            w = min(w, max(700, ag.width() - 80))
            h = min(h, max(480, ag.height() - 80))
    except Exception:                                                      # noqa: BLE001
        ag = None
    win.resize(w, h)
    if ag is not None:
        win.move(ag.x() + max(0, (ag.width() - w) // 2), ag.y() + max(0, (ag.height() - h) // 2))
    win.show()
    return win
