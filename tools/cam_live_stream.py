#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Z-MAX 旁路调试 · 实时视频流（压缩版）
──────────────────────────────────────────────────────────────
老倪需求 (2026-09-26):
  「把实时视频流发过来；旁路调试时模型跑在 4060，笔记本内置相机走笔记本驱动，
    手臂相机从 Orin 过来；要提高实时性，视频流要压缩。」

架构:
  ① 手臂相机 (Orin → 4060): 读 ss_remote_tap 落盘的 cam_rs.png (由 ROS raw 话题解码)
     → JPEG 压缩 (默认 q70) → 体积 420KB → ~29KB (14.5x) → MJPEG 推流
  ② 笔记本内置相机 (本机驱动): /dev/videoN → JPEG → MJPEG 推流
  ③ 两路合并到一张页面 (并排)，供手机/PC 直接看

为什么这样压:
  · 原始 ROS Image 640x480x3 = 921KB/帧；tap 写 PNG = 420KB/帧 @10Hz = 4.2MB/s
  · JPEG q70 = 29KB/帧 → 同样 10Hz 只要 0.29MB/s (~10-15x 降)
  · MJPEG 天然免解码缓冲 → 低延迟；服务端只推"最新帧"，旧帧丢弃 (不积压)

接口:
  /                 两路并排看板 (自动刷新)
  /arm.mjpg         手臂相机 MJPEG (来自 Orin)
  /local.mjpg       笔记本内置相机 MJPEG
  /snapshot/arm.jpg 单帧 JPEG (给飞书/证据用)
  /snapshot/local.jpg
  /stats            JSON: fps / 每帧字节 / 压缩比 / 帧龄 (证据口径)

用法:
  gui-venv311/bin/python tools/cam_live_stream.py --port 8791 --quality 70
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse

# 🔐 真动授权的**单一真源**(文件 ctl_auth.py): 原来授权只活在本进程内存里 ⇒ ①GUI/脚本/自动流程
#   直接写 l2_cmd.fifo 完全绕过它 ②执行器下发前也不校验 ⇒ 撤销前排队的动作照样下发。
#   老倪 2026-09-29: 「我都取消授权了，手臂怎么还在动；点1 技能也要服从手动控制台的授权」
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import ctl_auth as CA
except Exception as _e:                                                 # noqa: BLE001
    CA = None
    print("!! ctl_auth 导入失败: %s ⇒ 真动授权将无法工作(运动侧一律拒发)" % _e, flush=True)
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np

# ── 场景叠加（老倪 2026-09-27：把仿真场景边界框嵌进真实视频流）────────
# 独立渲染线程 + 独立帧槽: 只在开启时才付出「解码→画→重编码」开销,
# 原 arm/local 的"JPEG 直转"最快路径一字未改。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import scene_overlay as _SO
except Exception:                    # 叠加是可选能力，导入失败不拖累推流
    _SO = None
_OVERLAY_FPS = 12.0

# ── 全局：各路相机的最新 JPEG 帧 ───────────────────────────────
# 🎥 2026-09-27 老倪: 三路相机并存 —— arm(机器人臂上 D405, 走 Orin 网络) /
#   local(笔记本内置 /dev/video2) / local2(MAXHUB 电视顶摄 /dev/video0 或网络流)
#   叠加帧统一命名 ov_<源名>; 新源只需往 _FRAMES 注册 + 起一个 worker。
_LOCK = threading.Lock()
# 🔴 2026-09-28 老倪: 「帧龄标的是你这端合成帧的年龄, 源卡死了它照样显示 0.01s, 这是骗人」
#   所以帧槽除本端时间外, 还要留**源端新鲜度**的取证位:
#     _hdr_age_s    源端自报的帧龄 (响应头 X-Frame-Age-S; 没有就是 None)
#     _sig/_stall_since  帧字节签名 + 连续返回同一张图的起点 ⇒ 源卡死 ⇒ 「源已静止 Ns」
_FRAME_TPL = {"jpg": None, "ts": 0.0, "seq": 0, "src_ts": 0.0, "raw_kb": 0.0,
              "_sig": None, "_stall_since": 0.0, "_hdr_age_s": None}
_SRC_STALL_S = 2.0          # 源连续这么多秒返回同一张图 ⇒ 判「源已静止」(不再是实时)
_DEPTH_DEAD_S = 10.0        # 深度源文件龄 >10s ⇒ 判「深度源已断」(与位姿文件同一口径)
_FRAMES = {k: dict(_FRAME_TPL) for k in
           ("arm", "local", "local2", "depth", "aoi_gold", "aoi_surface",
            "ov_arm", "ov_local", "ov_local2")}
_OV_INFO = {}                        # 每路最近一次的叠加统计（画了多少框/跳过原因）
_CAM_LABEL = {}                      # 🎥 源名 → 真实相机名 (页面/画布直显"这是哪个摄像头")
_STOP = threading.Event()


def _put(name: str, jpg: bytes, src_ts: float, raw_kb: float,
         src_age_s: float | None = None) -> None:
    """登记一路最新帧 (可带**源端自报**的帧龄 `src_age_s`, 如工控机响应头 X-Frame-Age-S)。

    🔴 帧龄口径 (2026-09-28 老倪: 「源卡死了帧龄还显示 0.01s, 这是骗人」):
      · `src_age_s` 有值 = 源端自己说的"这一帧有多旧" ⇒ 页面优先用它 (最可信)。
      · 同时按**帧字节签名**判源是否卡死: 源连续返回同一张图 ⇒ 记住起点, /stats 据此
        如实报「源已静止 Ns」。没有这个位, 源一卡死本端时间照样归零 = 假新鲜值。
    """
    now = time.time()
    with _LOCK:
        f = _FRAMES.setdefault(name, dict(_FRAME_TPL))   # 新源自动注册
        f["jpg"] = jpg
        f["ts"] = now
        f["seq"] += 1
        f["src_ts"] = src_ts or now
        f["raw_kb"] = raw_kb
        if jpg:
            sig = (len(jpg), hashlib.md5(jpg).digest())
            if sig != f.get("_sig"):
                f["_sig"] = sig
                f["_stall_since"] = now                 # 图变了 ⇒ 源在推进, 静止计时归零
            elif not f.get("_stall_since"):
                f["_stall_since"] = now
        else:
            f["_sig"] = None
            f["_stall_since"] = now
        if src_age_s is not None:
            f["_hdr_age_s"] = float(src_age_s)
        else:
            # 没有源端自报 ⇒ 清掉上一帧的旧值(否则会让这一帧"继承"上一个源的年龄 = 新的假口径)
            f["_hdr_age_s"] = None


def _hdr_age(headers) -> float | None:
    """从 HTTP 响应头取**源端自报的帧龄(秒)**; 源没给这类头就返回 None。

    实测(2026-09-28): 工控机 10082 `GET /picture?kind=crop` 返回
      `X-Frame-Source: memory` + `X-Frame-Age-S: 418.018`
    —— 那格画面其实取的是它内存里 418s 前那张图。原先页面只报本端"取回来的那一刻",
    显示成 0.87s, 完全是假的新鲜值。这里把源端口径原样带上来。

    ⚠️ 只认 X-Frame-Age-S / X-Frame-Age 这种**明确是帧龄**的头; 不碰标准 `Age`
    (那是代理缓存年龄, 语义不同, 拿来当帧龄又会造一个新的假口径)。
    """
    for k in ("X-Frame-Age-S", "X-Frame-Age"):
        try:
            v = headers.get(k)
        except Exception:                                                        # noqa: BLE001
            return None
        if v is None:
            continue
        try:
            return max(0.0, float(str(v).split(",")[0].strip()))
        except (TypeError, ValueError):
            continue
    return None


def _get(name: str):
    with _LOCK:
        f = _FRAMES.get(name)
        if f is None:
            return None, 0, 0.0, 0.0, 0.0
        return f["jpg"], f["seq"], f["ts"], f["src_ts"], f["raw_kb"]


# ── 动作同步：读 L2 执行器日志的最近一条运动（与相机同一时钟）──────────
_L2_LOG = os.path.expanduser("~/zmax_data/l2_daemon.log")
_DIRMAP = {"lift": "抬升(+Z)", "lower": "下降(-Z)", "left": "向左(+Y)",
           "right": "向右(-Y)", "forward": "前进(+X)", "backward": "后退(-X)"}


def _motion_state():
    """最近一次运动下发（含方向/目标/时刻），供看板与画面同步显示。"""
    out = {"ok": False, "skill": "", "dir": "", "pos": "", "delta": "",
           "age_s": -1.0, "line": ""}
    try:
        # 只读末尾 64KB，避免大日志全读
        sz = os.path.getsize(_L2_LOG)
        with open(_L2_LOG, "rb") as f:
            f.seek(max(0, sz - 65536))
            tail = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return out
    now = time.time()
    for ln in reversed(tail):
        if "目标 L2." not in ln:
            continue
        out["line"] = ln.strip()
        # 形如: [18:10:04] 目标 L2.lift: pos=(...) · Δ=(...)mm ↑上升(+Z) · 位姿来源 direct
        try:
            tstr = ln.split("]")[0].strip("[ ")
            hh, mm, ss = [int(x) for x in tstr.split(":")]
            lt = time.localtime(now)
            when = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, hh, mm, ss, 0, 0, -1))
            out["age_s"] = round(max(0.0, now - when), 1)
        except Exception:
            pass
        try:
            out["skill"] = ln.split("目标 ")[1].split(":")[0].strip()
        except Exception:
            pass
        try:
            out["pos"] = ln.split("pos=")[1].split("·")[0].strip()
        except Exception:
            pass
        try:
            out["delta"] = ln.split("Δ=")[1].split("mm")[0].strip()
        except Exception:
            pass
        for k, v in _DIRMAP.items():
            if f"L2.{k}" in ln:
                out["dir"] = v
                break
        out["ok"] = True
        break
    return out


# ── ① 手臂相机：读 tap 落盘帧（Orin 那一路）────────────────────
def arm_worker(src_path: str, quality: int, fps_cap: float) -> None:
    """监视 tap 写的 cam_rs.png（mtime 变化即新帧），压成 JPEG。"""
    params = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
    last_mtime = 0.0
    misses = 0
    while not _STOP.is_set():
        t0 = time.time()
        try:
            st = os.stat(src_path)
        except OSError:
            misses += 1
            if misses % 50 == 1:
                print(f"[arm] 等帧中… {src_path} 不存在", flush=True)
            _STOP.wait(0.2)
            continue
        if st.st_mtime <= last_mtime:
            _STOP.wait(0.005)
            continue
        # 原子写保护：文件可能在写中；反复读直到大小稳定
        size_a = st.st_size
        _STOP.wait(0.004)
        try:
            size_b = os.stat(src_path).st_size
        except OSError:
            continue
        if size_a != size_b:
            continue
        img = cv2.imread(src_path, cv2.IMREAD_COLOR)
        if img is None:
            _STOP.wait(0.02)
            continue
        last_mtime = st.st_mtime
        ok, buf = cv2.imencode(".jpg", img, params)
        if not ok:
            continue
        _put("arm", buf.tobytes(), st.st_mtime, st.st_size / 1024.0)
        dt = time.time() - t0
        if fps_cap > 0 and dt < 1.0 / fps_cap:
            _STOP.wait(1.0 / fps_cap - dt)


# ── ①b 手臂相机（全速模式）：读容器落共享内存的原始帧 ──────────
# 背景: ss_remote_tap.py 是「raw 订阅, 1Hz 解码」→ 手臂流被节流到 ~0.5fps。
# 本模式改读 ros_arm_tap_raw.py（容器内，按相机原生 1.92Hz 落 /dev/shm），
# 本机 cv2 负责 JPEG 编码 → 帧龄从 ~1.8s 降到接近相机自身周期。
def arm_raw_worker(raw_path: str, meta_path: str, quality: int,
                   fps_cap: float) -> None:
    params = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
    last_seq = -1
    misses = 0
    while not _STOP.is_set():
        t0 = time.time()
        try:
            with open(meta_path, "r") as f:
                meta = json.load(f)
        except (OSError, ValueError):
            misses += 1
            if misses % 30 == 1:
                print(f"[arm-raw] 等 {meta_path} …（容器 ros_arm_tap_raw.py 是否在跑？）",
                      flush=True)
            _STOP.wait(0.1)
            continue
        seq = int(meta.get("seq", 0))
        if seq == last_seq:
            _STOP.wait(0.004)
            continue
        w, h, nc = int(meta["w"]), int(meta["h"]), int(meta.get("nmask", 3))
        try:
            with open(raw_path, "rb") as f:
                buf = f.read(w * h * nc)
        except OSError:
            _STOP.wait(0.02)
            continue
        if len(buf) < w * h * nc:
            _STOP.wait(0.01)
            continue
        arr = np.frombuffer(buf, np.uint8).reshape(h, w, nc)
        img = arr if nc == 3 else cv2.cvtColor(arr[:, :, 0], cv2.COLOR_GRAY2BGR)
        ok, out = cv2.imencode(".jpg", img, params)
        if not ok:
            continue
        last_seq = seq
        _put("arm", out.tobytes(), float(meta.get("ts") or time.time()),
             float(meta.get("bytes", 0)) / 1024.0)
        dt = time.time() - t0
        if fps_cap > 0 and dt < 1.0 / fps_cap:
            _STOP.wait(1.0 / fps_cap - dt)


# ── ①b 手臂相机：从 Orin 高速 JPEG 通道取帧（D405 直驱 30fps，旁路 DDS）──
def arm_http_worker(url: str, fps_cap: float) -> None:
    """Orin 侧已压好 JPEG(640x480 q72, ~32KB)，这里原样转发不再重压 → 最快"""
    import urllib.request
    misses = 0
    last_len = 0
    while not _STOP.is_set():
        t0 = time.time()
        _src_age = None
        try:
            with urllib.request.urlopen(url, timeout=2.0) as r:
                _src_age = _hdr_age(r.headers)          # 源端自报帧龄(有就给, 没有=None)
                data = r.read()
        except Exception as e:
            misses += 1
            if misses % 20 == 1:
                print(f"[arm-http] 取 {url} 失败: {str(e)[:60]}（Orin rs_fast_node 在跑么？）",
                      flush=True)
            _STOP.wait(0.15)
            continue
        if not data or len(data) < 500:
            _STOP.wait(0.05)
            continue
        misses = 0
        last_len = len(data)
        _put("arm", data, time.time(), last_len / 1024.0, src_age_s=_src_age)
        dt = time.time() - t0
        if fps_cap > 0 and dt < 1.0 / fps_cap:
            _STOP.wait(1.0 / fps_cap - dt)


# ── ② 本机 V4L2 相机：驱动直读 (笔记本内置 / MAXHUB 电视顶摄 都是走这里) ────
def local_worker(dev_index: int, quality: int, width: int, height: int,
                 fps_cap: float, frame_name: str = "local") -> None:
    cap = cv2.VideoCapture(dev_index)
    if not cap.isOpened():
        print(f"[{frame_name}] /dev/video{dev_index} 打不开", flush=True)
        return
    # 低延迟三件套：MJPG 采集 + 缓冲=1 + 固定分辨率
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    if width:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    if height:
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    params = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
    fails = 0
    while not _STOP.is_set():
        t0 = time.time()
        ok, frame = cap.read()
        if not ok or frame is None:
            fails += 1
            if fails % 30 == 1:
                print(f"[{frame_name}] 读帧失败 x{fails}", flush=True)
            _STOP.wait(0.05)
            continue
        ok, buf = cv2.imencode(".jpg", frame, params)
        if ok:
            _put(frame_name, buf.tobytes(), time.time(),
                 float(frame.nbytes) / 1024.0)
        dt = time.time() - t0
        if fps_cap > 0 and dt < 1.0 / fps_cap:
            _STOP.wait(1.0 / fps_cap - dt)
    cap.release()


# ── ②b 网络相机：MAXHUB 等可联网相机 (HTTP-JPEG/MJPEG 直转 · RTSP 解码重压) ──
def url_cam_worker(url: str, fps_cap: float, frame_name: str = "local2",
                   quality: int = 70) -> None:
    """把一路网络相机接成 frame_name (默认 local2)。
    · http(s)://…jpg|mjpg  → 原样转发(不重压, 最快, 和手臂高速通道同款)
    · rtsp:// / rtmp://    → OpenCV 解码 → 重压 JPEG (相机若走 RTSP 用这条)
    """
    import urllib.request
    params = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
    misses = 0
    if url.lower().startswith(("rtsp://", "rtmp://")):
        cap = cv2.VideoCapture(url)
        if not cap.isOpened():
            print(f"[{frame_name}] 打不开网络流 {url}", flush=True)
            return
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        while not _STOP.is_set():
            t0 = time.time()
            ok, frame = cap.read()
            if not ok or frame is None:
                misses += 1
                if misses % 30 == 1:
                    print(f"[{frame_name}] 读流失败 x{misses} ({url[:60]})", flush=True)
                _STOP.wait(0.2)
                continue
            misses = 0
            ok, buf = cv2.imencode(".jpg", frame, params)
            if ok:
                _put(frame_name, buf.tobytes(), time.time(),
                     float(frame.nbytes) / 1024.0)
            dt = time.time() - t0
            if fps_cap > 0 and dt < 1.0 / fps_cap:
                _STOP.wait(1.0 / fps_cap - dt)
        cap.release()
        return
    while not _STOP.is_set():
        t0 = time.time()
        _src_age = None
        try:
            with urllib.request.urlopen(url, timeout=2.0) as r:
                _src_age = _hdr_age(r.headers)          # 源端自报帧龄(有就给, 没有=None)
                data = r.read()
        except Exception as e:
            misses += 1
            if misses % 20 == 1:
                print(f"[{frame_name}] 取 {url[:60]} 失败: {str(e)[:50]}", flush=True)
            _STOP.wait(0.2)
            continue
        if not data or len(data) < 500:
            _STOP.wait(0.05)
            continue
        misses = 0
        _put(frame_name, data, time.time(), len(data) / 1024.0, src_age_s=_src_age)
        dt = time.time() - t0
        if fps_cap > 0 and dt < 1.0 / fps_cap:
            _STOP.wait(1.0 / fps_cap - dt)


# ── ③ 场景叠加渲染线程（解码 → 画仿真/大模型/检测框 → 重编码）──────────
# ══════════════════════════════════════════════════════════════════════════════
# 🌈 深度源 + 🏭 工控机 OPT 检测源 + 🕹 手动控制后端
#   (2026-09-27 老倪: 「6 个窗口同时显示 + 留出控制区, 手动控制机器人 X Y Z 平动 / A B C 绕轴旋转」)
# ══════════════════════════════════════════════════════════════════════════════
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # 同目录工具互导 (tools/*.py)
SCENE_DIR = "/home/ubuntu/zmax_ss_remote/zmax_scene"
DEPTH_NPY = SCENE_DIR + "/depth_raw.npy"
DEPTH_META = SCENE_DIR + "/depth_meta.json"
TCP_JSON = SCENE_DIR + "/tcp_pose.json"          # 容器 ros_tcp_cache 20Hz 落盘
ROBOT_STATUS_JSON = SCENE_DIR + "/robot_status.json"   # 同上的 /robot_status 三查缓存
# 🦾 位姿真值口径 (2026-09-28 现场修):
#   `/robot/tcp_pose` 的 DDS 端点已死(机器人栈时钟重同步后不再通告) ⇒ 老的
#   tcp_pose.json 停了 15h+, 页面却照读它 ⇒ 显示的是 1 号位的旧位姿(骗人)。
#   现改读 **ROKAE SDK 直采文件**(常驻采样器容器 rokae_tcp_sampler, 5Hz, 口径 endInRef)。
#   文件龄 >10s 判失效(与 tools/l2_daemon.py 直读位姿同一门槛), 页面必须如实标「源已静止 Ns」。
ROKAE_TCP_JSON = os.path.expanduser("~/zmax_data/rokae_sdk/tcp_out/latest.json")
ROKAE_TCP_MAX_AGE_S = 10.0
_AOI_INFO = {}            # port → {ok, err, http, t, kb, verdict, kind, src}
_AOI_LOCK = threading.Lock()
_DEPTH_INFO = {}
_JSON_WARNED = set()


def _json_safe(o):
    """json.dumps 兜底: numpy 标量/数组 → 原生类型。

    🐛 2026-09-28 现场: `/station/status`(页面**唯一**那条状态请求) 与 /ctl/status /aoi/status
       都在 json.dumps 里抛 `TypeError: Object of type ndarray is not JSON serializable`
       ⇒ HTTP 处理器整个崩掉(实测 curl 返回 **000 空回复**) ⇒ 控制台面板永远「读取中…」、
       位姿/三查/授权全部看不到(老倪:「金手指和表面检测怎么没有图像」那轮一起暴露的)。
    这里兜底转换 **并且** 打一行带类型的告警(第一次遇到才打), 便于回头把源头改干净。
    """
    t = type(o).__name__
    try:
        import numpy as np
        if isinstance(o, np.ndarray):
            _warn_json_once(t, o)
            return o.tolist()
        if isinstance(o, np.generic):
            _warn_json_once(t, o)
            return o.item()
    except Exception:                                                             # noqa: BLE001
        pass
    _warn_json_once(t, o)
    return str(o)


def _warn_json_once(t, o):
    if t in _JSON_WARNED:
        return
    _JSON_WARNED.add(t)
    try:
        print("⚠️ [json] payload 里出现非原生类型 %s → 已自动转换; 源头该改成原生类型 (repr=%r)"
              % (t, str(o)[:80]), flush=True)
    except Exception:                                                             # noqa: BLE001
        pass


def _jbytes(obj) -> bytes:
    """统一出口: 任何响应体都走这里 ⇒ 不会再因为一个 numpy 值整条请求崩掉。"""
    return json.dumps(obj, ensure_ascii=False, default=_json_safe).encode("utf-8")

# 🕹 手动控制: **服务级开关** —— 不加 --ctl-motion 时本进程只演练(dry), 真动需要
#   ①启动参数 --ctl-motion ②页面勾「授权真动」, 双重闸门(防止推流服务被当成遥控器)。
_CTL = {"motion": False, "min_gap": 1.5, "last_real": 0.0,
        "last": {"t": 0.0, "skill": "", "dry": True, "ok": False, "msg": "", "lines": []}}
_CTL_LOG = "/tmp/zmax_ctl.log"
# 🔐 真动授权 (2026-09-27 老倪: 「页面的授权真动 / 现场安全 / 授权」)
#   设计原则: **默认未授权**(现场有人时最安全), 真动必须由人**显式两步确认**授权;
#   授权**有时限**(默认 5 分钟, 到期自动失效, 不需要记得撤); 每次授权/撤销都记 IP+时刻(审计)。
#   ⚠️ 这个闸门在**服务端**强制, 不是页面上的样子货 —— 别的程序直接 POST {"arm":1} 一样被拒(403)。
_CTL_AUTH = {"until": 0.0, "since": 0.0, "ip": "", "window": 300.0, "events": []}


def _auth_info() -> dict:
    """真动授权状态 —— 读**单一真源**(ctl_auth.py 的文件), 执行器/GUI/脚本共用同一份。"""
    if CA is None:
        return {"armed": False, "left_s": 0.0, "window_s": 0.0, "ip": "", "since": 0.0,
                "epoch": 0, "events": [], "err": "ctl_auth 不可用"}
    st = CA.info()
    try:                                        # 🛑 撤销时由 ctl_revoke_stop 写的"在途叫停"实况
        _ls = json.loads(open(os.path.expanduser("~/zmax_data/ctl_last_stop.json"), encoding="utf-8").read())
    except Exception:                                                   # noqa: BLE001
        _ls = None
    return {"armed": bool(st["armed"]), "left_s": st["left_s"], "window_s": st["window"],
            "ip": st["ip"], "since": st["since"], "epoch": st["epoch"],
            "revoked_at": st["revoked_at"], "events": st["events"][-6:], "last_stop": _ls}


def _auth_set(on: bool, ip: str = "", note: str = "") -> dict:
    """授权/撤销真动。on=True 重新计时(epoch+1); on=False 立刻失效**且 epoch+1** ⇒ 已签发未下发的
    命令(带旧 epoch)在 L2 执行器里一律作废 —— 这样"等慢层 300s 期间人点了撤销"也不会再动。"""
    t = time.time()
    if CA is None:
        return _auth_info()
    if on:
        CA.grant(ip=ip, note=note)
    else:
        CA.revoke(ip=ip, note=note)
    print("[授权] %s %s ip=%s %s" % ("🔓 真动已授权" if on else "🔒 真动已撤销",
          time.strftime("%H:%M:%S", time.localtime(t)), ip, note), flush=True)
    try:
        with open(_CTL_LOG, "a", encoding="utf-8") as f:      # 审计: 与动作日志同一条时间线
            f.write(json.dumps({"t": t, "auth": bool(on), "ip": ip, "note": note},
                               ensure_ascii=False) + "\n")
    except OSError:
        pass
    return _auth_info()

_L2_FIFO = os.path.expanduser("~/zmax_data/l2_cmd.fifo")
# 允许的指令白名单: 技能 → (参数名, 最小, 最大)。**只认这些**, 别的技能(含点位/多阶段技能)
# 一律拒绝 —— 手动控制区是给"点动"用的, 不是通用技能下发口。
_CTL_SKILLS = {
    # ⚠️ 2026-09-30 老倪: 「增加平动 1mm 的按钮, 现在的最小分辨率 5mm 有点大」⇒ 平动/升降最小步进 5 → 1mm。
    #    只放开**下界**(细调分辨率), 上界不动(lift/left/right/forward 300mm, lower 100mm/次不变)。
    "L2.forward": ("d_mm", 1, 300), "L2.backward": ("d_mm", 1, 300),
    "L2.left": ("d_mm", 1, 300), "L2.right": ("d_mm", 1, 300),
    "L2.lift": ("d_mm", 1, 300), "L2.lower": ("d_mm", 1, 100),
    "L2.rot_a_pos": ("deg", 1, 30), "L2.rot_a_neg": ("deg", 1, 30),
    "L2.rot_b_pos": ("deg", 1, 30), "L2.rot_b_neg": ("deg", 1, 30),
    "L2.rot_c_pos": ("deg", 1, 30), "L2.rot_c_neg": ("deg", 1, 30),
    # 🔩 2026-09-30 老倪: 「手动控制台增加让 6 轴独立旋转的按钮, 分成逆时针旋转和顺时针旋转」
    #   关节 J6(末端自转轴)单独转 —— 与 A/B/C 同一套闸门(白名单+授权+限流+FIFO+执行器+安全裁决);
    #   2026-09-30 老倪「放开到 30°/90°」⇒ 单次角度上限 10 → 90。要多转就一次 30/90 或连点。
    "L2.j6_ccw": ("deg", 1, 90), "L2.j6_cw": ("deg", 1, 90),
}

# 🎯 绝对点位技能(无数字参数): 只发 {skill, speed}, 目标点位由技能定义 point_locked 锁死(执行器侧)。
# 2026-09-29 老倪: 「把这个技能放到工位总览 金手指检测窗口 整板原图 按钮旁边, 添加一个『点1』按钮,
#   点击后即返回点一」。白名单里加的是**技能 id**(不是坐标) ⇒ 点位真值仍由示教点文件 + 执行器收口,
# 页面/接口都无法改点位; 仍走同一条 授权真动 + 限流 + FIFO + 回执 的路。
# 🔁 热读白名单覆盖层 (2026-10-01): 「加一个回点按钮就得重启推流服务」这件事去掉 ——
#    白名单 = 代码常量 ∪ data/skills/l2_atomic/ctl_abs_skills.json ({"skills": {"L2.xxx": "标签"}})。
#    严格校验: 只认 L2. 开头 + 字母数字下划线点 + 值是非空字符串 ⇒ 手误也塞不进危险 id。
#    注意: 点位真值仍只在示教点库 + 执行器 point_locked 收口, 覆盖层只放行**技能 id**, 放不进坐标。
_CTL_ABS_REL = "data/skills/l2_atomic/ctl_abs_skills.json"
_CTL_ABS_CACHE = {"mtime": None, "map": {}}


def _abs_skills() -> dict:
    # 注意: _REPO_ROOT 在本文件更下方才定义 ⇒ 路径必须**调用时**再拼(模块级拼会在导入期 NameError)
    extra = os.path.join(_REPO_ROOT, _CTL_ABS_REL)
    try:
        mt = os.path.getmtime(extra)
    except OSError:
        mt = None
    if mt != _CTL_ABS_CACHE["mtime"]:
        mp = {}
        if mt is not None:
            try:
                _j = json.load(open(extra, encoding="utf-8"))
                for _k, _v in dict((_j or {}).get("skills") or {}).items():
                    if (isinstance(_k, str) and _k.startswith("L2.") and len(_k) <= 48
                            and all(ch.isalnum() or ch in "._" for ch in _k)
                            and isinstance(_v, str) and _v.strip()):
                        mp[_k] = _v.strip()
            except Exception as _e:
                print("[ctl] 热读白名单解析失败(忽略覆盖层): %s" % str(_e)[:100], flush=True)
        _CTL_ABS_CACHE.update({"mtime": mt, "map": mp})
    out = dict(_CTL_ABS_SKILLS)
    out.update(_CTL_ABS_CACHE["map"])
    return out


_CTL_ABS_SKILLS = {
    "L2.goto_gold_pt1": "🎯 回到金手指点1",
    # 🎯 2026-09-30 老倪: 「在侧面检测, 增加一个技能 侧面点1 的按钮, 放在侧面检测窗口的下面,
    #    类似 技能 返回 金手指点1 的技能」 —— 与 goto_gold_pt1 同规格: 只送技能 id,
    #    目标点『侧面点1』的真值在示教点库 + 执行器 point_locked 收口, 页面/接口都改不了点位。
    "L2.goto_surface_pt1": "🎯 回到侧面点1",
    # 🎯 2026-10-01 老倪: 「记录现在的表面检测的位姿, 侧面点2, 并增加侧面点2的技能,
    #    在表面检测窗口下面的侧面点1旁边增加 侧面点2 按钮」 —— 与 侧面点1 同规格:
    #    只送技能 id, 目标点『侧面点2』真值在示教点库 + 执行器 point_locked 收口。
    "L2.goto_surface_pt2": "🎯 回到侧面点2",
    "L2.goto_aoi_gold": "🎯 进入金手指检测区",
    # 🤏 2026-09-29 老倪: 「在手动控制台 增加 关闭夹抓 和 打开夹抓 两个技能」
    #    无页面可调参数(夹持力/行程由技能定义 registry 固定) ⇒ 只送技能 id, 仍走同一条授权+收口路
    "L2.grip_close": "🤏 关闭夹爪(夹紧)",
    "L2.grip_open": "🤏 打开夹爪(松开)",
    # 📍 2026-09-30 老倪: 「页面左下角…增加技能点: 1号位 … 一直到7号位; 有记录的点就是绿色按钮,
    #    没有记录的点就是灰色按钮」 —— 白名单按**技能 id** 放行(不是坐标), 点位真值仍在示教点库
    #    taught_points.json + 执行器 point_locked 收口; 未示教的号位会被执行器干净拒发
    #    「点位 slotN 不在点位库」; 页面灰按钮根本不下发, 这里只是给绿按钮留通道。
    "L2.slot1": "🅰️ 1号位", "L2.slot2": "🅰️ 2号位", "L2.slot3": "🅰️ 3号位", "L2.slot4": "🅰️ 4号位",
    "L2.slot5": "🅰️ 5号位", "L2.slot6": "🅰️ 6号位", "L2.slot7": "🅰️ 7号位",
}


# 📍 号位 1~7 (2026-09-30 老倪): 页面「有记录=绿 / 没记录=灰」的判据**只能在服务端算** ——
#   页面自己判会出现"以为自己能发"的假绿(点位真值在执行器侧的示教点库, 页面读不到)。
_POINT_SLOTS = {1: "slot1", 2: "slot2", 3: "slot3", 4: "slot4", 5: "slot5", 6: "slot6", 7: "slot7"}
# 📝 允许"记住此点"写入的点位名(白名单): 只号位 —— 防手误把别的点名写坏/写歪。
_POINT_RECORD_ALLOW = set(_POINT_SLOTS.values())
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _taught_points() -> dict:
    """示教点库(与执行器 _load_points 同一口径: 演示学习轨迹点 + L2 传授点库, 同名以传授点库为准)。"""
    pts: dict = {}
    for _pf in ("data/skills/l2_muscle/光模块_抓放_演示学习_v1.json",
                "data/skills/l2_atomic/taught_points.json"):
        try:
            with open(os.path.join(_REPO_ROOT, _pf), encoding="utf-8") as _f:
                pts.update(json.load(_f).get("points", {}))
        except Exception:                                                     # noqa: BLE001
            pass
    return pts


def _registry_skill_ids() -> set:
    try:
        with open(os.path.join(_REPO_ROOT, "data/skills/l2_atomic/registry.json"), encoding="utf-8") as _f:
            return {str(_s.get("id")) for _s in json.load(_f).get("skills", [])}
    except Exception:                                                         # noqa: BLE001
        return set()


def _ctl_points() -> dict:
    """📍 1~7 号位状态 —— 供页面画按钮:
       recorded = 示教点库里有 slotN(老倪口径: **有记录的点就是绿色**);
       has_skill = 注册表里有 L2.slotN(有下发壳才能真的按);
       ready = 两者都齐 ⇒ 绿+可点, 否则灰+不可点(点了也不下发, 服务端白名单同样拦)。"""
    pts, ids = _taught_points(), _registry_skill_ids()
    out = []
    for _no, _p in sorted(_POINT_SLOTS.items()):
        _sid = "L2." + _p
        _rec = _p in pts
        _pd = pts.get(_p) or {}
        _pos = _pd.get("pos") or _pd.get("position")
        out.append({
            "no": _no, "name": "%d号位" % _no, "point": _p, "skill": _sid,
            "recorded": bool(_rec), "has_skill": _sid in ids, "ready": bool(_rec and _sid in ids),
            "pos": [round(float(v), 4) for v in _pos] if (_rec and _pos) else None,
            "quat_taught": bool(_pd.get("quat")),
            "at": str(_pd.get("at") or _pd.get("ts_str") or _pd.get("updated_at") or "") if _rec else "",
            "whitelisted": _sid in _abs_skills(),
        })
    return {"ok": True, "slots": out, "green": sum(1 for _s in out if _s["ready"]), "n": len(out),
            "points_file": "data/skills/l2_atomic/taught_points.json"}


def _ctl_record_point(body: dict) -> dict:
    """📝 把**当前** TCP 真值记成号位示教点 (2026-09-30 老倪: 「4 5 6 号位, 你能自己实现记录么？」)。

    零运动 —— 记录只是"读真值 + 落盘", 所以不需要真动授权; 但仍然:
      · 只允许号位名 ``slot1..slot7``(防手误写坏别名的点);
      · 由 ``tools/record_l2_point.py`` 连采 6 帧判静止(极差 >1e-4m ⇒ 拒记), 并校验四元数自洽(4 分量);
      · 写前自动备份, 覆盖已有记录时回执里带 ``overwrote`` 让页面二次确认。
    页面路径: 点动到位 → 号位面板「📝 记住此点」→ POST /ctl/record_point → 按钮变绿。
    """
    name = str((body or {}).get("name") or "").strip()
    if name not in _POINT_RECORD_ALLOW:
        return {"ok": False, "code": 400,
                "msg": "只允许号位点位 %s (收到 %r)" % ("/".join(sorted(_POINT_RECORD_ALLOW)), name)}
    dry = bool((body or {}).get("dry"))
    try:
        _ns = max(4, min(12, int((body or {}).get("samples") or 6)))
    except (TypeError, ValueError):
        _ns = 6
    cmd = [sys.executable or "python3", os.path.join(_REPO_ROOT, "tools", "record_l2_point.py"),
           "--name", name, "--samples", str(_ns), "--json"]
    _note = str((body or {}).get("note") or "").strip()
    if _note:
        cmd += ["--desc", _note]
    if dry:
        cmd.append("--dry")
    try:
        _r = subprocess.run(cmd, capture_output=True, text=True, timeout=150)
    except Exception as _e:                                                   # noqa: BLE001
        return {"ok": False, "msg": "记录脚本执行失败: %s" % str(_e)[:160]}
    _out = None
    for _l in reversed((_r.stdout or "").splitlines()):
        _l = _l.strip()
        if _l.startswith("{") and _l.endswith("}"):
            try:
                _out = json.loads(_l)
                break
            except ValueError:
                continue
    if _out is None:
        return {"ok": False, "msg": "记录脚本无 JSON 回执: %s" % ((_r.stdout or _r.stderr or "")[-240:])}
    _out["dry"] = dry
    _out["tail"] = "\n".join([_x for _x in (_r.stdout or "").splitlines() if not _x.strip().startswith("{")][-6:])
    if _out.get("ok") and not dry:
        log_line = ("[记录点] %s ← (%.4f, %.4f, %.4f) · n=%s · 极差 %.1e m%s"
                    % (name, _out["pos"][0], _out["pos"][1], _out["pos"][2], _out.get("n_samples"),
                       _out.get("spread_pos_m") or 0.0, " · 覆盖" if _out.get("overwrote") else ""))
        print(log_line, flush=True)
        try:
            with open(_CTL_LOG, "a", encoding="utf-8") as _f:
                _f.write(json.dumps({"t": time.time(), "record_point": name, "pos": _out["pos"],
                                     "by": str((body or {}).get("by") or ""),
                                     "client": "8793"}, ensure_ascii=False) + "\n")
        except OSError:
            pass
    return _out


def _read_json(path: str, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                         # noqa: BLE001
        return default


def _age(t) -> float:
    return round(time.time() - float(t), 2) if t else -1.0


def _depth_worker(npy_path: str, meta_path: str, fps_cap: float) -> None:
    """🌈 深度源: 读容器落的 depth_raw.npy(+meta) → 伪彩 JPEG → 帧槽 "depth"。

    为什么不在容器里上色: 容器(ros:humble-ros-base)没 cv2, 装了重启即失。彩色化口径在
    tools/depth_colorize.py(两边共用), 宿主这里负责真正画。
    帧龄取「拍照时刻」= meta.t − src_stamp_age_s (容器写盘时贴的新鲜度), 不是读盘时刻。
    """
    try:
        from depth_colorize import colorize as _colorize
    except Exception as e:                                                    # noqa: BLE001
        print("   ⚠ 深度源: depth_colorize 导入失败(%s) ⇒ 深度窗口不可用" % e, flush=True)
        return
    last_mtime = -1.0
    while not _STOP.is_set():
        t0 = time.time()
        try:
            mt = os.path.getmtime(meta_path)
            if mt != last_mtime:
                last_mtime = mt
                meta = _read_json(meta_path, {}) or {}
                raw = np.load(npy_path)                       # uint16 HxW (原子替换, 不会读半截)
                d = raw.astype(np.float32) * float(meta.get("depth_scale", 0.0001))
                jpg = _colorize(d, meta)
                if jpg:
                    src_ts = float(meta.get("t", time.time())) - float(meta.get("src_stamp_age_s", 0.0))
                    _put("depth", jpg, src_ts, raw.nbytes / 1024.0)
                    with _LOCK:
                        _DEPTH_INFO.clear()
                        _DEPTH_INFO.update(meta)
                        _DEPTH_INFO["file_age_s"] = _age(mt)
        except Exception as e:                                                    # noqa: BLE001
            with _LOCK:
                _DEPTH_INFO["err"] = str(e)[:140]
        time.sleep(max(0.05, 1.0 / max(0.5, fps_cap)) - (time.time() - t0))


_AOI_GOLD_ANGLE = {"deg": 2.75, "t": 0.0, "src": "默认值(还没从服务读到)"}


def _aoi_gold_angle(port: int = 10082, ttl: float = 60.0) -> float:
    """金手指条的倾角(度), 用于反向旋转去倾角。从工控机 /region 读 angle, 缓存 ttl 秒。

    读不到就用上一次的值(初始 2.75°) —— 倾角是机械安装量, 变化极慢; 宁可沿用也不要 0
    (传 0 = 不去倾角, 画面就是斜的, 那正是老倪要修的现象)。
    """
    now = time.time()
    if now - float(_AOI_GOLD_ANGLE.get("t") or 0) < ttl:
        return float(_AOI_GOLD_ANGLE.get("deg") or 0.0)
    try:
        import json as _json
        import urllib.request as _ur
        with _ur.urlopen("http://192.168.23.23:%d/region?grab=0" % port, timeout=4) as r:
            d = _json.loads(r.read().decode("utf-8", "ignore"))
        a = d.get("angle")
        if a is None and isinstance(d.get("region"), dict):
            a = d["region"].get("angle")
        if a is not None and abs(float(a)) < 45.0:
            _AOI_GOLD_ANGLE.update({"deg": float(a), "t": now, "src": "服务 /region 实测"})
    except Exception as e:                                                    # noqa: BLE001
        _AOI_GOLD_ANGLE["t"] = now      # 失败也记时间, 避免每帧都去试
        _AOI_GOLD_ANGLE["src"] = "读失败(%s) ⇒ 沿用上次 %.3f°" % (str(e)[:40],
                                                                float(_AOI_GOLD_ANGLE.get("deg") or 0))
    return float(_AOI_GOLD_ANGLE.get("deg") or 0.0)


def _aoi_frame(bgr, clean: bool = True, out: int = 900, quality: int = 78, natural: bool = False,
               deskew_deg: float = 0.0, vstretch: float = 1.0, fix_hw=None):
    """工控机原图(BGR) → 判据图 JPEG。

    ⚠️ 色彩顺序坑: `aoi_exposure_fix.clean_judge_frame` 内部按 **RGB** 加权算灰度(过曝/边缘),
    喂它 BGR 会把红的过曝带判成别的 ⇒ **进出各转一次**; 传错的表现是"判据图偏色/裁错行"。

    2026-09-28 老倪: 「金手指区域不是标准的长方体, 你的图像显示歪斜了, 要调整成矩形, 不能有角度」
      · 根因1: clean_judge_frame 默认把细长条 **归一化到 out×out(正方形)** ⇒ 长宽比被破坏、
               只有 2.75° 的机械倾角被竖向放大成肉眼很明显的斜纹。
               ⇒ `natural=True` 走它的**原比例版** (return_natural), 保住长宽比。
      · 根因2: 相机视角本身让金手指条在画面里带 ~2.75° 倾角 (服务 /region 的 angle)。
               ⇒ `deskew_deg` 传实测角度, 这里按 -角度 反向旋转 ⇒ 裁出的区域**上下沿水平、左右边竖直**。
               旋转用白底填充(金手指区背景是亮底), 避免黑角干扰判据。
    """
    img, meta = bgr, {}
    # 2026-09-28 老倪: 「工控机拍摄的照片与你的金手指判据图不一样, 要跟判据图保持一致」
    #   工控机 kind=crop 取回来的**就是它自己的判据图**(crop_goldfinger_regular: 模板法规整裁剪 +
    #   去倾斜居中, 960×960 画布; method=template, 残余倾角实测 -0.25°), 与它存盘/送检同一张。
    #   这种"服务端已裁好"的情形必须**原样透传** —— 本地再 clean、再 resize 到 out 都会把它变成
    #   另一张图(960→900 方图), 那就又是"两边不一致"。所以这里直接编码返回, 不碰尺寸/比例。
    if not clean and not natural and fix_hw is None and abs(float(vstretch) - 1.0) < 0.01:
        ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
        return (buf.tobytes() if ok else b""), {
            "passthrough": True, "src": "工控机判据图(kind=crop, 未本地二次处理)",
            "size": [int(bgr.shape[1]), int(bgr.shape[0])]}
    if clean:
        try:
            from aoi_exposure_fix import clean_judge_frame
            _kw = {"out": out}
            if natural:
                _kw["return_natural"] = True
            clean_rgb, meta = clean_judge_frame(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), **_kw)
            if clean_rgb is not None:
                # 2026-09-28: return_natural 不改主返回值(它永远 resize 成 out×out 正方形),
                #   而是把**原比例条带**放进 meta["natural"] ⇒ 要真比例就得用它。
                if natural and isinstance(meta, dict) and meta.get("natural") is not None:
                    clean_rgb = meta["natural"]
                img = cv2.cvtColor(clean_rgb, cv2.COLOR_RGB2BGR)
                if abs(float(deskew_deg)) > 0.05:
                    h0, w0 = img.shape[:2]
                    M = cv2.getRotationMatrix2D((w0 / 2.0, h0 / 2.0), -float(deskew_deg), 1.0)
                    img = cv2.warpAffine(img, M, (w0, h0), flags=cv2.INTER_LINEAR,
                                         borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))
                    meta = dict(meta or {})
                    meta["deskew_deg"] = round(float(deskew_deg), 3)
                # 2026-09-28 老倪: 「能再纵向拉伸成 3 倍长度么」—— 判据图是细长条(≈8:1),
                #   纵向放大便于肉眼分辨金手指间距/缺陷; 只拉高不拉宽(横向比例不动)。
                # 2026-09-28 老倪: 「判据图为什么总是一会儿大一会儿小？不要跳动」
                #   根因: 去死白自动裁的条带每帧高度不同(相机/曝光/白带判定都在动) ⇒ 输出高度逐帧变。
                #   修: 金手指这格**输出尺寸定死**(fix_hw), 内容按比例适配 ⇒ 画面不再跳动。
                if fix_hw:
                    img = cv2.resize(img, (int(fix_hw[0]), int(fix_hw[1])),
                                     interpolation=cv2.INTER_LINEAR)
                    meta = dict(meta or {})
                    meta["fix_hw"] = [int(fix_hw[0]), int(fix_hw[1])]
                elif abs(float(vstretch) - 1.0) > 0.01:
                    _h1, _w1 = img.shape[:2]
                    img = cv2.resize(img, (_w1, max(1, int(round(_h1 * float(vstretch))))),
                                     interpolation=cv2.INTER_LINEAR)
                    meta = dict(meta or {})
                    meta["vstretch"] = float(vstretch)
            else:
                meta = dict(meta or {})
                meta["fallback"] = "自裁失败 → 退回原图(如实标注, 不硬裁一张错的)"
        except Exception as e:                                                    # noqa: BLE001
            meta = {"ok": False, "err": str(e)[:120]}
    h, w = img.shape[:2]
    if max(h, w) > out:
        k = out / float(max(h, w))
        img = cv2.resize(img, (int(w * k), int(h * k)))
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    return (buf.tobytes() if ok else b""), meta


_AOI_AUTO = {10082: True, 10083: False}   # 自动取景: 工控机内存里没照片时, 由本服务现拍一张
_AOI_AUTO_AT = {10082: 0.0, 10083: 0.0}   # 上次自动现拍的时刻(限流: 最快 30s 一次)
_AOI_AUTO_MIN_S = 60.0

# 🔴 2026-09-27 老倪: 「工位总览 10082 10083 通道不是实时的推流, 改成实时视频流」
#   实测事实(先量后改):
#     · OPT 相机**只在被触发拍照时**才更新内存里的图 —— 不触发时连读 3 次(隔 3s)指纹完全一样;
#     · 单张耗时: 10082 `GET /picture?kind=origin&grab=1` 实测 0.67~0.73s;
#       10083 `GET /picture?kind=crop&grab=1` ≈0.6s(class); 只读 /picture 是 8~11ms(拿旧图)。
#     ⇒ **硬件上限 ≈1.4~1.7 帧/秒**, 这是 OPT 相机取一张图的时间, 不是网络/代码的锅; 不可能到 25fps。
#   做法: 有人正在看这一格(MJPEG 客户端在取帧)时, 采集线程**每轮都带 grab 触发一帧并立刻取回**
#        = 顶到设备上限的连续流; 没人看就退回"只读不触发"的慢速 —— 不长时间占着产线相机。
#   心跳(时刻)而不用引用计数: 客户端被强杀也不会泄漏计数 ⇒ 不会永久顶着重拍相机。
_AOI_VIEW_TS = {}          # 帧槽名 → 最后一次被 MJPEG 客户端取帧的时刻
_AOI_LIVE_WIN_S = 8.0      # 心跳在这么多秒内 ⇒ 认为"有人在看", 走实时触发模式


def _aoi_detect(port: int = 10082, wait_s: float = 2.5) -> dict:
    """触发工控机产线正常检测命令 POST /capture_detect, 并把判决取回来。

    2026-09-28 老倪: 「增加一个请求按钮, 发出正常的检测命令, 工控机本地也可以保存图片」
      · `/capture_detect` = 产线**正常检测那条命令**(相机拍照 + 后台 YOLO), 不是我们自造的接口;
      · 工控机自己会落盘 incoming 原图(回执/判决里的 saved_incoming, 实测
        `D:\AOI_images\gf\incoming\20260928_090231_003.png`) ⇒ "本地保存图片"这一条由它保证;
      · 拍照+推理约 1.5~2s, 这里等 wait_s 再读 /last_result(读不到也如实说, 不编判决)。
    """
    import json as _json
    import urllib.request as _ur
    # 🆕 2026-09-30: 表面(housing)单帧推理实测 ~7.8s, 金手指 ~1.6s ⇒ 等待时间分开, 免得一上来就报"还没出结果"
    if float(wait_s) == 2.5 and int(port) == 10083:
        wait_s = 13.0
    out = {"ok": False, "port": port, "cmd": "POST /capture_detect"}
    # 🆕 2026-09-30 修「点了请求检测却报上一帧」: 先记下**点之前**的检测序号, POST 之后必须等到序号变了,
    #   才算"这一次"的结果。否则表面推理 8.9s、等待到点没等到 ⇒ 页面把上一次(可能几分钟前)的判决当本次报出来。
    _n0 = None
    try:
        with _ur.urlopen("http://192.168.23.23:%d/last_result" % int(port), timeout=8) as _r0:
            _n0 = _json.loads(_r0.read().decode("utf-8", "ignore")).get("n")
    except Exception:                                                             # noqa: BLE001
        _n0 = None
    out["n_before"] = _n0
    try:
        req = _ur.Request("http://192.168.23.23:%d/capture_detect" % port, data=b"", method="POST")
        with _ur.urlopen(req, timeout=60) as r:
            out["capture"] = _json.loads(r.read().decode("utf-8", "ignore"))
        out["ok"] = True
    except Exception as e:                                                        # noqa: BLE001
        out["err"] = "触发检测失败: %s" % str(e)[:180]
        return out
    try:
        _dl = time.monotonic() + max(0.0, float(wait_s))
        d, _fresh = None, False
        _slept = False
        _last_code = None
        while True:
            if _slept:
                time.sleep(0.6)
            _slept = True
            try:
                with _ur.urlopen("http://192.168.23.23:%d/last_result" % port, timeout=20) as r:
                    d = _json.loads(r.read().decode("utf-8", "ignore"))
                _last_code = 200
            except Exception as _e1:                                              # noqa: BLE001
                _last_code = getattr(_e1, "code", None)
                if _last_code not in (404, 500, 502, 503):
                    raise
                d = None        # 工控机还没有任何结果(冷启后第一次) ⇒ 继续等, 不当失败
            if d and d.get("n") is not None and (out["n_before"] is None or d.get("n") != out["n_before"]):
                _fresh = True
                break
            if time.monotonic() >= _dl:
                break
        if d:
            out["last_result"] = d
            out["fresh"] = bool(_fresh)
            out["saved_locally"] = d.get("saved_incoming") or ""
            if _fresh:
                out["msg"] = ("✅ 检测完成: 判决 %s · 缺陷 %s 处 · 用时 %sms · 工控机本地存图 %s"
                              % (d.get("verdict"), d.get("count"), d.get("ms"),
                                 d.get("saved_incoming") or "(未返回路径)"))
            else:
                out["msg"] = ("⚠️ 这一次还没出结果(检测仍在跑, 过几秒点「🧾 最后结果」) —— 下面是**上一次**(序号 %s): "
                              "判决 %s · 缺陷 %s 处 · 用时 %sms"
                              % (d.get("n"), d.get("verdict"), d.get("count"), d.get("ms")))
        else:
            out["fresh"] = False
            out["msg"] = ("⚠️ 工控机还没出结果(HTTP %s, 冷启动第一次检测要等模型加载完): 过几秒点「🧾 最后结果」"
                          % (_last_code or "?"))
    except Exception as e:                                                        # noqa: BLE001
        out["err2"] = "取判决失败(检测可能仍在跑, 稍后看判决格): %s" % str(e)[:150]
    return out


def _aoi_last_result(port: int = 10082) -> dict:
    """🔎 读工控机 GET /last_result(最近一次检测的判决) —— **只读, 不拍照、不检测**。

    2026-09-30 老倪: 「在请求检测按钮旁边, 增加 最后结果 按钮, 实现 /last_result 功能, 最终得有结果啊」
      · 与 /api/aoi/detect 的区别: detect 要 POST 触发产线相机拍照; 这个只 GET 把结果取回来;
      · 结果里带工控机那一帧的时间 t, 这里再算一个 age_s(帧龄) —— 页面必须显示"照片是什么时候拍的";
      · 工控机说"尚无检测结果"(404) 时如实回报(不编判决), 并提示先点「请求检测」。
    """
    import json as _json
    import urllib.request as _ur
    out = {"ok": False, "port": int(port), "cmd": "GET /last_result", "fetched_at": time.time()}
    try:
        with _ur.urlopen("http://192.168.23.23:%d/last_result" % int(port), timeout=12) as r:
            d = _json.loads(r.read().decode("utf-8", "ignore"))
        out["ok"] = True
        out["last_result"] = d
        if isinstance(d.get("t"), (int, float)) and d.get("t"):
            out["age_s"] = round(time.time() - float(d["t"]), 1)
        out["msg"] = ("最近一次检测: 判决 %s · 缺陷 %s 处 · 耗时 %sms · 检测序号 %s"
                      % (d.get("verdict"), d.get("count"), d.get("ms"), d.get("n")))
    except Exception as e:                                                        # noqa: BLE001
        _code = getattr(e, "code", None)
        if _code == 404:
            out["msg"] = "工控机还没有出过结果(HTTP 404 尚无检测结果) —— 先点「🔍 请求检测」, 等 2 秒再点这个"
        elif _code:
            out["msg"] = "工控机 /last_result 返回 HTTP %s" % _code
        else:
            out["msg"] = ("连不上工控机 192.168.23.23:%d (这路的程序在跑吗? 看 %s 上「%s」进程): %s"
                          % (int(port), "工控机", ("cam_finger_10082_work_v6.py" if int(port) == 10082
                                                 else "cam_surface_10083_work_v12.py"), str(e)[:120]))
    return out


def _aoi_auto_status() -> dict:
    return {str(p): bool(_AOI_AUTO.get(p)) for p in (10082, 10083)}


# ────────────────── 🎚 判据口径开关 (canonical / same) ──────────────────
# 老倪 2026-09-28: 「改成一样的, 产线可以切换」
#   canonical(默认) = 工控机用模板法规整裁剪 960x960 送检; 页面按老口径本地渲染(origin→原比例+去倾角+3×→900x332)
#   same            = 工控机**直接吃**与页面同一口径的那张(原比例+去倾斜+定尺 900x332), 这张同时是送检输入 +
#                     落盘判据图 + kind=crop 内存帧 ⇒ 本页**取回来就用**(零本地加工), 页面显示 == 模型吃的那张。
_AOI_CAL = {"mode": None, "t": 0.0, "port": 0, "src": "还没读", "raw": {}}


def _aoi_modelin_get(suffix: str = "", port: int = 10082):
    """🆕 v11: 从工控机取**模型实际吃的那张图**(`GET /picture?kind=modelin`)。

    为什么需要: 页面上那格显示的是「判据图」(人看的), 而模型吃的是同帧派生的 960x960 方图
    (在工控机 %TEMP%, 检测完即删)。老倪问「实际输入给模型的图片长什么样」⇒ 这个口把
    **喂给 detector.detect() 的同一份像素**无损取回来, 并且 /last_result.model_input_md5
    与它的像素 md5 逐位对得上(同源硬证据, 不是"看起来像")。
    """
    url = "http://192.168.23.23:%d/picture?kind=modelin%s" % (int(port), suffix)
    req = urllib.request.Request(url, headers={"User-Agent": "zmax-station"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, r.read(), dict(r.headers)


def _aoi_caliber(port: int = 10082, ttl: float = 8.0) -> dict:
    """读工控机的判据口径 (GET /caliber)。读不到就沿用上次值, 并在 src 里如实写"读失败"。"""
    now = time.time()
    if _AOI_CAL.get("mode") and (now - float(_AOI_CAL.get("t") or 0.0)) < ttl:
        return dict(_AOI_CAL)
    try:
        with urllib.request.urlopen("http://192.168.23.23:%d/caliber" % int(port), timeout=4) as r:
            d = json.loads(r.read().decode("utf-8", "ignore"))
        c = d.get("caliber") or {}
        _AOI_CAL.update({"mode": str(c.get("mode") or "canonical"), "t": now, "port": int(port),
                         "raw": c, "err": "",
                         "src": "工控机 GET /caliber 实测 @%s" % time.strftime("%H:%M:%S")})
    except Exception as e:                                                        # noqa: BLE001
        _AOI_CAL["t"] = now                      # 失败也记时间, 别每轮都去试
        _AOI_CAL["err"] = str(e)[:80]
        _AOI_CAL["src"] = "读失败(%s) ⇒ 沿用 %s" % (str(e)[:50], _AOI_CAL.get("mode") or "canonical(默认)")
        if not _AOI_CAL.get("mode"):
            _AOI_CAL["mode"] = "canonical"
    return dict(_AOI_CAL)


def _aoi_set_caliber(port: int = 10082, mode: str = "canonical") -> dict:
    """页面「判据口径」开关 → 转发工控机 POST /caliber?mode=... (回执带 mode/切换时刻/累计次数)。"""
    m = str(mode or "").strip().lower()
    if m not in ("canonical", "same"):
        return {"ok": False, "code": 400, "msg": "mode 只能是 canonical(规范) 或 same(同一口径)"}
    url = "http://192.168.23.23:%d/caliber?mode=%s" % (int(port), m)
    t0 = time.time()
    try:
        req = urllib.request.Request(url, data=b"", method="POST",
                                     headers={"User-Agent": "zmax-station",
                                              "Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=15) as r:
            code = r.status
            d = json.loads(r.read().decode("utf-8", "ignore"))
    except urllib.error.HTTPError as e:                                           # noqa: BLE001
        try:
            d = json.loads(e.read().decode("utf-8", "ignore"))
        except Exception:                                                         # noqa: BLE001
            d = {}
        d.setdefault("ok", False)
        d.setdefault("msg", "HTTP %s" % e.code)
        code = e.code
    except Exception as e:                                                        # noqa: BLE001
        return {"ok": False, "code": 0, "mode": m, "ms": round((time.time() - t0) * 1000),
                "msg": "切不了: 工控机 /caliber 打不通(%s)" % str(e)[:120]}
    c = d.get("caliber") or {}
    _AOI_CAL.update({"mode": str(c.get("mode") or m), "t": time.time(), "port": int(port),
                     "raw": c, "err": "", "src": "页面切换 %s @%s" % (m, time.strftime("%H:%M:%S"))})
    out = {"ok": bool(d.get("ok", code == 200)), "code": int(d.get("code") or code), "mode": c.get("mode") or m,
           "switched_at": c.get("t"), "switched_at_str": (time.strftime("%H:%M:%S", time.localtime(float(c["t"])))
                                                          if c.get("t") else ""),
           "switches": c.get("switches"), "by": c.get("by"), "changed": d.get("changed"),
           "input": d.get("input"), "ms": round((time.time() - t0) * 1000),
           "msg": d.get("msg") or ("口径=%s" % m)}
    _aoi_note(port, caliber_out=out)
    return out


def _slim(o, max_items: int = 64, max_depth: int = 6):
    """状态响应瘦身: 绝不让"整张图的像素数组"进 JSON。

    为什么(2026-09-28 实测): 工控机 /last_result 的 caliber_meta.natural 是 2448×2048×3 的整图
    列表 = 5.16MB; 页面每 1.5s 轮询 /station/status ⇒ 一轮 10MB+, 页面直接拖死/假无图。
    只替换"超长数组"为摘要, 标量/短列表/字典原样保留 ⇒ 页面字段名不变, 改动对前端透明。
    """
    if isinstance(o, dict):
        return {k: (_slim(v, max_items, max_depth - 1) if max_depth > 0 else v) for k, v in o.items()}
    if hasattr(o, "shape") and hasattr(o, "size"):          # numpy ndarray(会被 default= 序列化成巨list)
        try:
            if int(o.size) > max_items:
                return {"_omitted": True, "_shape": [int(x) for x in o.shape], "_dtype": str(o.dtype),
                        "_why": "超长数组(疑似图像像素), 状态响应不带"}
        except Exception:                                                                   # noqa: BLE001
            return {"_omitted": True, "_why": "不可摘要数组"}
        return o
    if isinstance(o, (list, tuple)):
        if len(o) > max_items:
            return {"_omitted": True, "_len": len(o), "_why": "超长数组(疑似图像像素), 状态响应不带",
                    "_head": [_slim(v, max_items, max_depth - 1) for v in list(o)[:8]] if max_depth > 0 else []}
        return [_slim(v, max_items, max_depth - 1) if max_depth > 0 else v for v in o]
    return o


def _aoi_note(port: int, **kw) -> None:
    with _AOI_LOCK:
        d = _AOI_INFO.setdefault(port, {})
        d.update({k: _slim(v) for k, v in kw.items()})       # ⚠️ 一律瘦身后再进状态(页面轮询很轻)
        d["t"] = time.time()


def _aoi_full_frame(bgr, max_side: int = 1400) -> bytes:
    """整板原图 → 缩到长边 ≤max_side 的 JPEG (给「判据图 / 整板原图」切换用)。

    为什么要原图: 金手指那路取回来的 origin 是 2448×2048 整板(6MB PNG), 判据图只留了其中
    一条区域(900×900 拉正) —— 老倪目检时要能看**整板**对着看, 只有一条区域像"没图"。
    """
    try:
        h, w = bgr.shape[:2]
        s = max_side / float(max(h, w)) if max(h, w) > max_side else 1.0
        if s < 1.0:
            bgr = cv2.resize(bgr, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        return buf.tobytes() if ok else b""
    except Exception:                                                             # noqa: BLE001
        return b""


def _put_aoi_pair(port: int, name: str, bgr) -> None:
    """一张工控机图 → 两路帧槽: 判据/显示图 (`name`) + 整板缩图 (`name_raw`, 仅 10082 金手指)。

    判据图口径 = `_aoi_frame(clean=...)`: 10082 去死白 + 拉正; 10083 原样缩。
    """
    jpg, _m = _aoi_frame(bgr, clean=(port != 10083))
    if jpg:
        # 这张是**刚真拍的**(人点「拍一帧」触发的 _aoi_capture) ⇒ 源帧龄就是 0
        _put(name, jpg, time.time(), 0.0, src_age_s=0.0)
    if port == 10082:
        fj = _aoi_full_frame(bgr)
        if fj:
            _put(name + "_raw", fj, time.time(), 0.0, src_age_s=0.0)


def _aoi_worker(port: int, name: str, fps: float, kind: str = "origin",
                clean: bool = True, verdict: bool = True, full_name: str = "",
                full_kind: str = "", full_every: int = 0) -> None:
    """🏭 工控机 OPT 检测图 → 帧槽。**只 GET, 不带 grab** ⇒ 取服务端内存里最近一张, 不触发拍照。

    · 10082 金手指: `/picture?kind=origin`(实测 6.07MB PNG/0.07s) → 去死白 → 判据图
      (`name`), 另存一张**整板缩图** (`full_name`); 顺带每轮读 `/last_result`。
    · 10083 表面: v2 无取图路由(只有 POST /capture_detect) ⇒ 如实报「取图失败/无路由」;
      **升级到 v4 后**本 worker 零改动就有图: v4 增加了 GET /picture?kind=crop(规范图 1280, 喂模型的图)/
      kind=origin(原图)/ last_result / crop_info。这里取 kind=crop(=模型真正看到的那张) + 读 /last_result。
    """
    url = "http://192.168.23.23:%d/picture?kind=%s" % (port, kind)
    vurl = "http://192.168.23.23:%d/last_result" % port
    n = 0
    while not _STOP.is_set():
        t0 = time.time()
        n += 1
        # 🔴 2026-09-27 老倪: 有人看这一格 ⇒ 每轮都带 grab 触发一帧(顶到 OPT 上限 ~1.4/1.7fps);
        #   没人看 ⇒ 保持只读(不触发拍照, 不长时间占产线相机)。
        _watching = ((time.time() - _AOI_VIEW_TS.get(name, 0.0)) < _AOI_LIVE_WIN_S
                     or (full_name and (time.time() - _AOI_VIEW_TS.get(full_name, 0.0)) < _AOI_LIVE_WIN_S))
        _url_live = url + ("&grab=1" if "?" in url else "?grab=1")
        _req_url = _url_live if _watching else url
        code, raw, err = 0, b"", ""
        _src_age = None
        try:
            req = urllib.request.Request(_req_url, headers={"User-Agent": "zmax-station"})
            with urllib.request.urlopen(req, timeout=10) as r:
                code = r.status
                # 🕒 源端自报帧龄: 工控机 10082 会给 X-Frame-Age-S(memory 里那帧多旧) ——
                #    不拿它, 页面就会把一张 400s 前的图显示成"刚取到, 0.9s"。
                _src_age = _hdr_age(r.headers)
                raw = r.read()
        except urllib.error.HTTPError as e:
            code, err = e.code, (e.read()[:200].decode("utf-8", "ignore") if hasattr(e, "read") else "")
        except Exception as e:                                                    # noqa: BLE001
            err = str(e)[:140]
        if code == 200 and raw:
            bgr = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
            if bgr is not None:
                # 2026-09-28: 金手指那格走"原比例 + 去倾角"(老倪: 要矩形、不能有角度)
                # 2026-09-28 老倪: 「工控机拍摄的照片与你的金手指判据图不一样, 要跟判据图保持一致」
                #   金手指已改为直接取工控机自己的判据图(kind=crop) ⇒ 本地**一律不再加工**
                #   (服务端已完成 template 规整裁剪 + 去倾角, 残余倾角实测 -0.25°)。本地再 natural/
                #   deskew/3×/定尺 都会把它变成另一张图 ⇒ 那又回到"两边不一致"。故 kind=crop 时全停。
                _nat = (name == "aoi_gold")
                _ds = _aoi_gold_angle() if _nat else 0.0
                jpg, _meta = _aoi_frame(bgr, clean=clean, natural=_nat, deskew_deg=_ds,
                                        vstretch=(3.0 if _nat else 1.0),
                                        fix_hw=((900, 332) if _nat else None))
                if jpg:
                    _put(name, jpg, time.time(), len(raw) / 1024.0, src_age_s=_src_age)
                if full_name and not full_kind:            # 整板缩图 (面板上可切换到这一张)
                    fj = _aoi_full_frame(bgr)
                    if fj:
                        _put(full_name, fj, time.time(), len(raw) / 1024.0, src_age_s=_src_age)
                _aoi_note(port, ok=True, src=name, url=_req_url, http=code, kb=round(len(raw) / 1024.0, 1),
                          shape=[int(bgr.shape[0]), int(bgr.shape[1])], err="", live=bool(_watching),
                          src_frame_age_s=(round(_src_age, 1) if _src_age is not None else None))
            else:
                _aoi_note(port, ok=False, src=name, url=url, http=code,
                          err="取到 %d 字节但解不出图(不是图片?)" % len(raw))
        else:
            # 🔁 自动取景: 工控机**只在检测/拍照时留图**, 闲着的时候 GET 就是 404「尚无照片」
            #    —— 这就是老倪看到"这一格没图像"的原因。开了自动取景就替它现拍一张(最快 30s 一次)。
            #    拍过之后的 90s 内: 面板按**在线**报(画面确实是新的), 不要让"取图失败"这句话
            #    把一格里明明是新拍的图说成坏的 —— 老倪会照着字面理解。
            _no_photo = (code == 404 and ("grab=1" in err or "尚无" in err))
            _did_grab = False
            if (_no_photo and _AOI_AUTO.get(port)
                    and (time.time() - _AOI_AUTO_AT.get(port, 0.0)) >= _AOI_AUTO_MIN_S):
                _AOI_AUTO_AT[port] = time.time()
                g = _aoi_capture(port, name, timeout=60.0)
                _did_grab = bool(g.get("ok"))
            _fresh_grab = _no_photo and (time.time() - _AOI_AUTO_AT.get(port, 0.0)) < 90.0
            if _did_grab or _fresh_grab:
                _aoi_note(port, ok=True, src=name, url=url, http=200, err="",
                          auto_grab=True,
                          # 源帧龄如实标: 刚替它现拍 = 0.0; 显示 90s 内那次现拍的图 = 距那次多久
                          src_frame_age_s=(0.0 if _did_grab else
                                           round(time.time() - _AOI_AUTO_AT.get(port, 0.0), 1)),
                          note=("自动取景: 刚替它现拍了一张" if _did_grab else
                                "自动取景: 工控机里没照片, 显示的是最近现拍的那张"))
            else:
                _aoi_note(port, ok=False, src=name, url=url, http=code,
                          err=("HTTP %d %s" % (code, err)).strip() or "取图失败")
        # 🐢 整板原图(体积大: 10082 origin 实测 4.9MB) 单独按更低频率取: 每 full_every 轮一次, 不拖累主流
        if full_name and full_kind and full_every and (n % int(full_every) == 0):
            try:
                fu = "http://192.168.23.23:%d/picture?kind=%s" % (port, full_kind)
                with urllib.request.urlopen(
                        urllib.request.Request(fu, headers={"User-Agent": "zmax-station"}),
                        timeout=20) as r:
                    if r.status == 200:
                        fb = cv2.imdecode(np.frombuffer(r.read(), np.uint8), cv2.IMREAD_COLOR)
                        if fb is not None:
                            fj = _aoi_full_frame(fb)
                            if fj:
                                _put(full_name, fj, time.time(), 0.0)
            except Exception:                                                     # noqa: BLE001
                pass
        if verdict:
            try:
                with urllib.request.urlopen(vurl, timeout=6) as r:
                    v = json.loads(r.read().decode("utf-8", "ignore"))
                _aoi_note(port, verdict=v)
            except Exception as e:                                                # noqa: BLE001
                _aoi_note(port, verdict_err=str(e)[:100])
        if _watching:
            _STOP.wait(0.01)          # 🔴 实时模式: 不等, 立刻下一轮(节奏 = OPT 取图耗时 0.6~0.7s/帧)
        else:
            time.sleep(max(0.05, max(0.2, 1.0 / max(0.1, fps)) - (time.time() - t0)))


def _aoi_gold_worker(port: int = 10082, name: str = "aoi_gold", fps: float = 1.0,
                     full_name: str = "aoi_gold_raw", anno_name: str = "aoi_gold_anno") -> None:
    """🔍 金手指格 —— **口径感知**: 让"页面显示的那张"必然等于"检测吃的那张"。

      口径 canonical (默认, 产线现状):
        取 kind=origin 原图 → **本地**原比例(不压方)+去倾角+纵向3× → 定死 900x332 (老口径, 一字未改)
      口径 same (同一口径):
        取 kind=crop 的**内存帧** —— 工控机那张已经做完"原比例+去倾斜+定尺 900x332"并**送检/落盘的同一张**
        ⇒ 本服务**零本地加工**直接上屏 ⇒ 页面 == 模型输入 (不是"看起来像", 是同一张)
      另外: kind=anno (判据图 + YOLO 框 + 判决文字, 工控机端画好) 走 /aoi_gold_anno.mjpg 给现场看结果。
    """
    raw_every = 3          # same 口径下, "整板原图"这格低频单独取(省带宽, 不拖累判据图)
    vurl = "http://192.168.23.23:%d/last_result" % port
    n = 0
    while not _STOP.is_set():
        t0 = time.time()
        n += 1
        cal = _aoi_caliber(port)
        mode = cal["mode"]
        kind = "crop" if mode == "same" else "origin"
        url = "http://192.168.23.23:%d/picture?kind=%s" % (port, kind)
        # 有人在看这一格 ⇒ 每轮带 grab 顶到 OPT 上限 (~1.4/1.7fps); 没人看就只读内存帧(不占产线相机)
        _watching = any((time.time() - _AOI_VIEW_TS.get(k, 0.0)) < _AOI_LIVE_WIN_S
                        for k in (name, full_name, anno_name))
        _req_url = url + ("&grab=1" if _watching else "")
        code, raw, err, _src_age = 0, b"", "", None
        try:
            req = urllib.request.Request(_req_url, headers={"User-Agent": "zmax-station"})
            with urllib.request.urlopen(req, timeout=10) as r:
                code = r.status
                _src_age = _hdr_age(r.headers)
                raw = r.read()
        except urllib.error.HTTPError as e:
            code = e.code
            err = (e.read()[:200].decode("utf-8", "ignore") if hasattr(e, "read") else "")
        except Exception as e:                                                    # noqa: BLE001
            err = str(e)[:140]

        if code == 200 and raw:
            bgr = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
            if bgr is not None:
                if mode == "same":
                    # 🎯 同一口径: 工控机那张就是判据图 ⇒ **一律不再本地加工**(再裁/再拉都会变成另一张图)
                    jpg, meta = _aoi_frame(bgr, clean=False, natural=False, deskew_deg=0.0,
                                           vstretch=1.0, fix_hw=None, quality=92)
                    meta = dict(meta or {})
                    meta["caliber"] = "same"
                else:
                    jpg, meta = _aoi_frame(bgr, clean=True, natural=True,
                                           deskew_deg=_aoi_gold_angle(port), vstretch=3.0,
                                           fix_hw=(900, 332))
                    meta = dict(meta or {})
                    meta["caliber"] = "canonical"
                if jpg:
                    _put(name, jpg, time.time(), len(raw) / 1024.0, src_age_s=_src_age)
                # 整板原图那格: canonical 下复用同一张 origin; same 下另取一次(低频)
                if full_name and (mode == "canonical" or (n % raw_every == 0)
                                  or (time.time() - _AOI_VIEW_TS.get(full_name, 0.0)) < _AOI_LIVE_WIN_S):
                    if mode == "canonical":
                        fj = _aoi_full_frame(bgr)
                        if fj:
                            _put(full_name, fj, time.time(), len(raw) / 1024.0, src_age_s=_src_age)
                    else:
                        try:
                            with urllib.request.urlopen(
                                    urllib.request.Request("http://192.168.23.23:%d/picture?kind=origin" % port,
                                                           headers={"User-Agent": "zmax-station"}),
                                    timeout=20) as r2:
                                if r2.status == 200:
                                    b2 = cv2.imdecode(np.frombuffer(r2.read(), np.uint8), cv2.IMREAD_COLOR)
                                    if b2 is not None:
                                        fj = _aoi_full_frame(b2)
                                        if fj:
                                            _put(full_name, fj, time.time(), 0.0, src_age_s=_hdr_age(r2.headers))
                        except Exception:                                         # noqa: BLE001
                            pass
                _aoi_note(port, ok=True, src=name, url=_req_url, http=code, kb=round(len(raw) / 1024.0, 1),
                          shape=[int(bgr.shape[0]), int(bgr.shape[1])], err="", live=bool(_watching),
                          caliber=mode, caliber_src=cal.get("src"), caliber_mode_src=kind,
                          caliber_meta=meta,
                          src_frame_age_s=(round(_src_age, 1) if _src_age is not None else None))
            else:
                _aoi_note(port, ok=False, src=name, url=url, http=code, caliber=mode,
                          err="取到 %d 字节但解不出图(不是图片?)" % len(raw))
        else:
            _no_photo = (code == 404 and ("grab=1" in err or "尚无" in err))
            _did_grab = False
            if (_no_photo and _AOI_AUTO.get(port)
                    and (time.time() - _AOI_AUTO_AT.get(port, 0.0)) >= _AOI_AUTO_MIN_S):
                _AOI_AUTO_AT[port] = time.time()
                g = _aoi_capture(port, name, timeout=60.0)
                _did_grab = bool(g.get("ok"))
            _fresh_grab = _no_photo and (time.time() - _AOI_AUTO_AT.get(port, 0.0)) < 90.0
            if _did_grab or _fresh_grab:
                _aoi_note(port, ok=True, src=name, url=url, http=200, err="", auto_grab=True, caliber=mode,
                          src_frame_age_s=(0.0 if _did_grab else
                                           round(time.time() - _AOI_AUTO_AT.get(port, 0.0), 1)),
                          note=("自动取景: 刚替它现拍了一张" if _did_grab else
                                "自动取景: 工控机里没照片, 显示的是最近现拍的那张"))
            else:
                _aoi_note(port, ok=False, src=name, url=url, http=code, caliber=mode,
                          err=("HTTP %d %s" % (code, err)).strip() or "取图失败")

        # 🧾 检测结果叠加 (kind=anno): 有人看那一格才取(内存帧, 8~11ms); 字节直传, 本地零加工
        if (time.time() - _AOI_VIEW_TS.get(anno_name, 0.0)) < _AOI_LIVE_WIN_S:
            try:
                au = "http://192.168.23.23:%d/picture?kind=anno" % port
                with urllib.request.urlopen(
                        urllib.request.Request(au, headers={"User-Agent": "zmax-station"}), timeout=10) as r3:
                    if r3.status == 200:
                        ab = r3.read()
                        _put(anno_name, ab, time.time(), len(ab) / 1024.0, src_age_s=_hdr_age(r3.headers))
                        _aoi_note(port, anno={"http": 200, "kb": round(len(ab) / 1024.0, 1),
                                              "boxes": r3.headers.get("X-Anno-Boxes"),
                                              "verdict": r3.headers.get("X-Anno-Verdict"),
                                              "age_s": r3.headers.get("X-Anno-Age-S"),
                                              "mem_key": r3.headers.get("X-Frame-Mem-Key"),
                                              "note": r3.headers.get("X-Anno-Note") or "",
                                              "url": au})
            except Exception as e:                                                # noqa: BLE001
                _aoi_note(port, anno={"http": 0, "err": str(e)[:100], "url": "GET %s" % (port,)})

        if _watching:
            _STOP.wait(0.01)
        else:
            time.sleep(max(0.05, max(0.2, 1.0 / max(0.1, fps)) - (time.time() - t0)))
        try:
            with urllib.request.urlopen(vurl, timeout=6) as r:
                v = json.loads(r.read().decode("utf-8", "ignore"))
            _aoi_note(port, verdict=v)
        except Exception as e:                                                    # noqa: BLE001
            _aoi_note(port, verdict_err=str(e)[:100])


def _aoi_capture(port: int, name: str, timeout: float = 90.0) -> dict:
    """「拍帧」: 让工控机**现拍一张** —— 这是**有副作用**的动作(现场真的拍一张并跑检测),
    所以只能由人点按钮触发, 绝不自动轮询。回执里若带图(base64 或直接图片字节)就存成该路帧。

    两条路实测口径不同(别照抄):
      · 10082 金手指: 服务自己的 404 提示就是「先 POST /capture_detect 或 **GET /picture?grab=1**」
        ⇒ 用 GET /picture?kind=origin&grab=1, 响应体直接是图片。**平时不要带 grab**(那会拍照)!
      · 10083 表面: 只有 POST /capture_detect, 回执是个 JSON(可能带 base64 图)。
    """
    if port == 10082:
        url = "http://192.168.23.23:%d/picture?kind=origin&grab=1" % port
        how, method = "GET /picture?grab=1", "GET"
    else:
        url = "http://192.168.23.23:%d/capture_detect" % port
        how, method = "POST /capture_detect", "POST"
    try:
        if method == "POST":
            req = urllib.request.Request(url, data=b"{}", method="POST",
                                         headers={"Content-Type": "application/json",
                                                  "User-Agent": "zmax-station"})
        else:
            req = urllib.request.Request(url, headers={"User-Agent": "zmax-station"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            code = r.status
            raw = r.read()
    except urllib.error.HTTPError as e:
        return {"ok": False, "http": e.code, "how": how,
                "msg": (e.read()[:300].decode("utf-8", "ignore"))}
    except Exception as e:                                                        # noqa: BLE001
        return {"ok": False, "http": 0, "how": how, "msg": str(e)[:200]}
    out = {"ok": code == 200, "http": code, "bytes": len(raw), "how": how, "msg": ""}
    try:
        j = json.loads(raw.decode("utf-8", "ignore"))
    except Exception:                                                             # noqa: BLE001
        j = None
    if isinstance(j, dict):
        out["msg"] = str(j.get("msg") or j.get("message") or j.get("error") or "")[:200]
        for k in ("image_base64", "image_b64", "jpeg_base64", "jpg_base64", "image"):
            v = j.get(k)
            if isinstance(v, str) and len(v) > 500:
                try:
                    img = cv2.imdecode(np.frombuffer(base64.b64decode(v.split(",")[-1]),
                                                     np.uint8), cv2.IMREAD_COLOR)
                    if img is not None:
                        _put_aoi_pair(port, name, img)
                        out["got_image"] = True
                except Exception as e:                                            # noqa: BLE001
                    out["msg"] = (out["msg"] + " | base64 解图失败: " + str(e)[:80])[:240]
                break
    if not out.get("got_image"):          # 直接返回图片字节(GET /picture?grab=1 就是这种)
        img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if img is not None:
            _put_aoi_pair(port, name, img)
            out["got_image"] = True
            out["shape"] = [int(img.shape[0]), int(img.shape[1])]
    if out.get("ok") and not out.get("got_image"):
        # v4(表面/金手指): /capture_detect 回执不带图, 但拍完内存里就有照片了
        #  ⇒ 顺手 GET 一次 /picture 把图取回来(这一步是只读取图, 不会再拍)
        try:
            gurl = "http://192.168.23.23:%d/picture?kind=%s" % (
                port, "crop" if port == 10083 else "origin")
            with urllib.request.urlopen(
                    urllib.request.Request(gurl, headers={"User-Agent": "zmax-station"}),
                    timeout=min(30.0, timeout)) as r:
                if r.status == 200:
                    img = cv2.imdecode(np.frombuffer(r.read(), np.uint8), cv2.IMREAD_COLOR)
                    if img is not None:
                        _put_aoi_pair(port, name, img)
                        out["got_image"] = True
                        out["shape"] = [int(img.shape[0]), int(img.shape[1])]
                        out["via"] = gurl
        except Exception as e:                                                # noqa: BLE001
            out["msg"] = (out.get("msg") or "" + " | 拍后取图失败: " + str(e)[:80])[-240:]
    _aoi_note(port, last_capture=out)
    return out


def _tail(path: str, off: int, limit: int = 8192) -> str:
    """读 from offset 的新内容 (给"下发后等执行器回执"用, 不依赖时间戳解析)"""
    try:
        with open(path, "rb") as f:
            f.seek(off)
            return f.read(limit).decode("utf-8", "ignore")
    except Exception:                                                             # noqa: BLE001
        return ""


def _ctl_move(req: dict) -> dict:
    """🕹 手动点动: 白名单校验 → 双重授权 → 限流 → 写执行器 FIFO → **等回执**。

    返回里一定带 `lines`(执行器的原始日志行) —— 老倪口径: 点了必须有结果, 而且是可复制的证据,
    不是"已发送"这种自报。
    """
    sid = str(req.get("skill") or "")
    _abs = _abs_skills().get(sid)
    if sid not in _CTL_SKILLS and _abs is None:
        return {"ok": False, "msg": "技能 %r 不在手动控制白名单里" % sid}
    if _abs is not None:
        # 🎯 绝对点位技能: 没有数字参数(点位锁在技能定义里) ⇒ 不校验 d_mm/deg
        pname, val = None, 0.0
    else:
        pname, lo, hi = _CTL_SKILLS[sid]
        try:
            val = float(req.get(pname, 0))
        except (TypeError, ValueError):
            return {"ok": False, "msg": "参数 %s 不是数字" % pname}
        if not (lo <= val <= hi):
            return {"ok": False, "msg": "%s=%.1f 超出允许范围 [%d, %d]" % (pname, val, lo, hi)}
    try:
        speed = float(req.get("speed", 8))
    except (TypeError, ValueError):
        speed = 8.0
    speed = max(1.0, min(1000.0, speed))          # 手动控制速度上限(2026-09-30 老倪: 「转速太慢了，加速。别限制，我在现场，安全」)
    #   口径: 页面档位 8/60/200/500 + 可自己填数字; 上限定 1000(相对量, 线性实测 ≈0.0999mm/s 每单位,
    #   即 speed=1000 ≈ 100mm/s) —— 真正的物理上限由控制器自己的关节限速兜, 这里只挡住"填错量级"。
    #   实测基线: speed=60 → 腕部 10° 花 ~10s (~1°/s), 所以想快 5 倍就用 300。
    want_real = bool(req.get("arm")) and bool(_CTL["motion"])
    if want_real and not _auth_info()["armed"]:
        # 🔐 现场安全: 真动必须由人显式授权(且授权未过期)。拒绝时**明确告诉怎么授权**, 不给含糊的失败。
        _win = float(_CTL_AUTH["window"]) / 60.0
        return {"ok": False, "denied": True, "code": 403, "auth": _auth_info(),
                "msg": "未授权真动(现场安全): 先点页面上『🔓 授权真动』并二次确认(现场确认无人), "
                       "再操作; 授权 %.0f 分钟后自动失效" % _win}
    cmd = {"skill": sid, "speed": speed} if pname is None else {"skill": sid, pname: val, "speed": speed}
    if not want_real:
        cmd["dry"] = True
        why = "服务未授权真动(--ctl-motion)" if not _CTL["motion"] else "未授权真动(只算目标, 不下发)"
    else:
        why = ""
        gap = time.time() - float(_CTL["last_real"])
        if gap < float(_CTL["min_gap"]):
            return {"ok": False, "msg": "太快了(距上一条 %.1fs < %.1fs), 防连点把臂当摇杆刷"
                    % (gap, _CTL["min_gap"])}
    # 🔐 带上"签发时的授权 epoch": 执行器下发前会比对; 撤销 (+1) 后旧命令一律作废(在途也能拦)
    try:
        cmd["auth_epoch"] = CA.epoch() if CA is not None else None
    except Exception:                                                   # noqa: BLE001
        cmd["auth_epoch"] = None
    try:
        fd = os.open(_L2_FIFO, os.O_WRONLY | os.O_NONBLOCK)
    except OSError as e:
        return {"ok": False, "msg": "执行器 FIFO 打不开(%s) —— L2 常驻执行器没在跑?" % e}
    off = 0
    try:
        off = os.path.getsize(_L2_LOG)
    except OSError:
        pass
    try:
        os.write(fd, (json.dumps(cmd, ensure_ascii=False) + "\n").encode("utf-8"))
    except OSError as e:
        os.close(fd)
        return {"ok": False, "msg": "写入执行器失败: %s" % e}
    os.close(fd)
    if want_real:
        _CTL["last_real"] = time.time()
    # 等回执: 执行器要先直读真值位姿再算目标, 实测 1~3s
    buf, t0 = "", time.time()
    while time.time() - t0 < 9.0:
        time.sleep(0.4)
        buf += _tail(_L2_LOG, off)
        if sid in buf and ("受理" in buf or "拒绝" in buf or "失败" in buf):
            break
    lines = [l.strip() for l in buf.splitlines() if l.strip()][-6:]
    # 🛡 语义层(VL)在场时: 执行器先「告知 VL」并等针对本次动作的裁决(实测 45~190s, 上限 300s) ——
    #    这 9s 窗口里只会有「目标 / 告知 VL」两行。如实报「执行器已收到, 在等裁决」,
    #    **不冒充当次已下发**(也不让现场把"还没动"当成"点了没反应/坏了"); 页面继续追 /ctl/log
    #    直到出现「受理: 已下发」或「🛑 被拦(...) ⇒ 拒发」那一行。
    _pend = bool(buf) and ("受理" not in buf) and ("等针对该动作的裁决" in buf or "告知 VL" in buf)
    _par = {} if pname is None else {pname: val}
    out = {"ok": True, "dry": not want_real, "skill": sid, "param": _par, "speed": speed,
           "pending": bool(_pend and want_real),
           "msg": ("⏳ 执行器已收到: 正在等安全裁决(最多 300s, 实测 45~190s) — 机械臂还没动, 继续追裁决"
                   if _pend else (("演练(未下发): %s" % why) if not want_real else "已下发(真动)")),
           "elapsed_s": round(time.time() - t0, 2), "lines": lines}
    rec = {"t": time.time(), "skill": sid, "param": _par, "speed": speed,
           "dry": not want_real, "lines": lines}
    _CTL["last"] = {"t": rec["t"], "skill": sid, "dry": not want_real, "ok": True,
                    "pending": out["pending"], "msg": out["msg"], "lines": lines}
    try:
        with open(_CTL_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return out


def _depth_src_dead(threshold: float = _DEPTH_DEAD_S):
    """🌈 深度源是否已断: 返回 (dead, 断了多少秒)。

    判据 = **源文件龄**(容器 ros_depth_stream 落的 depth_meta.json / depth_raw.npy) ——
    源停写就说停写。绝不能因为它最后一帧还在帧槽里, 就把那张旧图报成"在线/0.0s"。
    """
    now = time.time()
    for p in (DEPTH_META, DEPTH_NPY):
        try:
            age = now - os.path.getmtime(p)
        except OSError:
            continue
        return bool(age > threshold), round(age, 1)
    return True, -1.0            # 文件都不在 = 从来没起过/已被删


def _rokae_pose() -> dict:
    """🦾 手动控制台显示的机械臂位姿 —— **ROKAE SDK 直采** (绕开已死的 DDS 话题)。

    源: ~/zmax_data/rokae_sdk/tcp_out/latest.json (常驻容器 rokae_tcp_sampler, 5Hz,
    frame=base_link, src=rokae_xcoresdk/endInRef)。字段 ts/t/x/y/z/rx/ry/rz/qx/qy/qz/qw。

    ⚠️ 判真口径: **文件龄 >10s 即判失效**(stale=True) —— 页面据此显示「源已静止 Ns」,
    绝不把停更 15 小时的旧值当实时位姿报出去(原先就是这个毛病)。
    """
    d = _read_json(ROKAE_TCP_JSON, None)
    if not isinstance(d, dict):
        return {"xyz": None, "quat": None, "age_s": -1.0, "file_age_s": -1.0,
                "stale": True, "frame_id": "", "src": "ROKAE SDK 直采 (文件不可读)",
                "src_file": ROKAE_TCP_JSON, "err": "latest.json 不存在/不可解析"}
    try:
        file_age = round(time.time() - os.path.getmtime(ROKAE_TCP_JSON), 2)
    except OSError:
        file_age = -1.0
    stale = (file_age < 0.0) or (file_age > ROKAE_TCP_MAX_AGE_S)
    # 🅰️🅱️🅲 a b c = SDK 原生 p6[3..5] (endInRef 世界系欧拉角), 示教器/产线 /robot/tcp_pose 同口径。
    #    单位 rad, 页面上给度 —— **直接透传, 不由我方从四元数反算**(反算只在需要比对方便时用,
    #    已实测: quat 按 ZYX(绕X→Y→Z 命名) 反算与原生 abc 差 ≤1e-6 rad)。
    _abc = [d.get("rx"), d.get("ry"), d.get("rz")]
    return {
        "xyz": [d.get("x"), d.get("y"), d.get("z")],
        "abc_rad": _abc,
        "abc_deg": [None if v is None else round(math.degrees(v), 3) for v in _abc],
        "abc_src": "SDK 原生 p6[3..5] endInRef (与示教器/产线 /robot/tcp_pose 同口径)",
        "quat": [d.get("qx"), d.get("qy"), d.get("qz"), d.get("qw")],
        "age_s": _age(d.get("ts")),          # 数据自身时间(ts)的年龄
        "file_age_s": file_age,              # 采样器最后一次落盘的年龄(判失效用它)
        "stale": bool(stale),
        "frame_id": d.get("frame", ""),
        "src": "ROKAE SDK 直采 (rokae_tcp_sampler 5Hz · endInRef)",
        "src_file": ROKAE_TCP_JSON,
        "err": "" if not stale else "位姿源已静止 %.1fs (>%.0fs 判失效)" % (file_age, ROKAE_TCP_MAX_AGE_S),
    }


def _ctl_status() -> dict:
    """页面 1.5s 轮询用的一把抓状态: 三查 + TCP 位姿 + 最近运动 + 各路源心跳。"""
    st = _read_json(ROBOT_STATUS_JSON, {}) or {}
    with _LOCK:
        depth = dict(_DEPTH_INFO)
        aoi = {str(k): dict(v) for k, v in _AOI_INFO.items()}
    now = time.time()
    _d_dead, _d_dead_s = _depth_src_dead()
    return {
        "motion_armed": bool(_CTL["motion"]),
        "robot": {
            "ok": bool(st.get("success")),
            "power": st.get("power_state", ""), "operation": st.get("operation_state", ""),
            "has_error": st.get("has_error"), "error_code": st.get("error_code", ""),
            "error_reason": st.get("error_reason", ""), "error_context": st.get("error_context", ""),
            "controller_error_logs": st.get("controller_error_logs") or [],
            "estop": st.get("estop_detected"), "collision": st.get("collision_detected"),
            "age_s": _age(st.get("t")),
        },
        # 🦾 位姿真值: 走 SDK 直采文件 (老的 tcp_pose.json 是死数据, 已不读)
        "tcp": _rokae_pose(),
        "motion": _motion_state(),
        "auth": _auth_info(),        # 🔐 真动授权状态(页面横幅/倒计时靠它)
        "depth": dict(depth, age_s=_age(depth.get("t")),
                      dead=_d_dead, dead_s=_d_dead_s),
        "aoi": aoi,
        "last_cmd": dict(_CTL["last"], age_s=_age(_CTL["last"].get("t"))),
        "server_time": now,
        "labels": dict(_CAM_LABEL),
    }


def _aoi_note_init() -> None:
    """开局就给两路 AOI 建个状态槽, 免得页面在首帧前读不到键"""
    for port, nm in ((10082, "aoi_gold"), (10083, "aoi_surface")):
        _aoi_note(port, ok=None, src=nm, err="启动中…")


_TCP_LATEST = {"tcp": None, "ts": 0.0, "err": ""}


def _tcp_label(tcp, age) -> str:
    """TCP 标签: 带上是**多久前**的真值 —— 别把缓存值说成实时(老倪口径: 实时数据必须标时间)。"""
    s = "TCP=(%.4f, %.4f, %.4f) 真值" % (float(tcp[0]), float(tcp[1]), float(tcp[2]))
    if age is not None:
        s += " · %.1fs前" % age
    return s


def _tcp_refresher(interval: float = 2.0) -> None:
    """后台刷 TCP 位姿真值, 供叠加循环**非阻塞**取用。

    为什么必须独立成线程(2026-09-27 实测):
      读 TCP 的快速路径是容器写的 tcp_pose.json 缓存; 但 read_tcp 只在缓存
      **新鲜度 ≤1.5s** 时才认它。容器栈一停, 缓存立刻变陈旧 ⇒ 每次都回退到
      `sshpass ssh … ros2 topic echo --once`(单次 0.3~8s)。叠加循环每 2 秒同步
      做一次这种读, 实测把 ov_arm 从 10fps 拖到 **2.1~4.3fps**(中位 3.0)。
      拆成后台线程后: 循环只取最新值 ⇒ 帧率回到上限, TCP 最多旧一个刷新周期
      (标签里会写明是多少秒前的值, 不装实时)。
    """
    while not _STOP.is_set():
        try:
            if _SO is not None:
                v = _SO.read_tcp(timeout=8, allow_ssh=True)
                if v is not None:
                    with _LOCK:
                        _TCP_LATEST["tcp"] = v
                        _TCP_LATEST["ts"] = time.time()
                        _TCP_LATEST["err"] = ""
                elif _TCP_LATEST["tcp"] is None:
                    with _LOCK:
                        _TCP_LATEST["err"] = "读不到 TCP"
        except Exception as e:                                             # noqa: BLE001
            with _LOCK:
                _TCP_LATEST["err"] = str(e)[:80]
        _STOP.wait(max(0.5, interval))


def overlay_worker(src_name: str, fps_cap: float) -> None:
    """
    把 src_name 的最新帧解码, 叠加 data/scene/overlay_spec.json 里的框, 存到 ov_<src>。
    规格每帧重读（文件小，几 KB）⇒ 外部生成器一写就立刻生效，不用重启服务。
    TCP 位姿按 2s 缓存（投影需要；读 Orin 有开销，不能每帧读）。
    """
    out_name = "ov_" + src_name
    tcp, tcp_ts = None, 0.0
    params = [int(cv2.IMWRITE_JPEG_QUALITY), 78]
    last_seq = -1
    while not _STOP.is_set():
        t0 = time.time()
        if _SO is None:
            _STOP.wait(0.5)
            continue
        jpg, seq, ts, src_ts, _ = _get(src_name)
        if jpg is None or seq == last_seq:
            _STOP.wait(0.01)
            continue
        last_seq = seq
        arr = np.frombuffer(jpg, np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            continue
        try:
            spec = _SO.load_spec()
            he = _SO.load_handeye()
            # 只有本路真有需要投影的 3D 框时才去读 TCP（读 Orin 有开销；否则白等拖帧率）
            cam_boxes = (spec.get("cameras") or {}).get(src_name, {}).get("boxes") or []
            need_tcp = any(b.get("box3d") for b in cam_boxes)
            if need_tcp:
                # ★ 非阻塞取值: 后台 _tcp_refresher 刷, 本循环绝不在这里等 ssh
                #   (曾同步读 ⇒ ov_arm 被拖到 2.1~4.3fps)
                with _LOCK:
                    tcp = _TCP_LATEST.get("tcp")
                    tcp_age = (time.time() - _TCP_LATEST["ts"]) if _TCP_LATEST["ts"] else None
            else:
                tcp_age = None
            extra = {
                "frame_age": "帧龄 %.1fs · 源 %s" % (max(0.0, time.time() - src_ts),
                                                    time.strftime("%H:%M:%S", time.localtime(src_ts))),
                "handeye": ("手眼 cam→tcp |t|=%.0fmm (%s/%s位姿)"
                            % (np.linalg.norm(he["X"][:3, 3]) * 1000, he.get("method"), he.get("n_poses")))
                           if he["ok"] else "手眼未标定 ⇒ 仿真框无法投影",
                "tcp": (_tcp_label(tcp, tcp_age) if tcp is not None
                        else ("TCP 未读到（仿真投影将跳过）" if need_tcp else "本路无 3D 投影框（不需要 TCP）")),
            }
            img2, info = _SO.draw_overlay(img, spec, src_name, tcp, extra)
            ok, buf = cv2.imencode(".jpg", img2, params)
            if ok:
                _put(out_name, buf.tobytes(), src_ts, float(buf.size) / 1024.0)
                with _LOCK:
                    _OV_INFO[src_name] = {
                        "drawn": len(info["drawn"]), "skipped": info["skipped"],
                        "origins": {o: sum(1 for d in info["drawn"] if d["origin"] == o)
                                    for o in ("sim", "vlm", "det")},
                        "mode": spec.get("mode"), "source": spec.get("source"),
                        "spec_age_s": round(time.time() - spec.get("ts", 0), 1),
                        "tcp_ok": tcp is not None, "ts": time.time(),
                        # 🖱 可交互 3D 框: 像素几何 + 稳定 id + 已删清单(页面选中/删除用)
                        "boxes": info.get("boxes") or [], "deleted": info.get("deleted") or [],
                        "n_3d": info.get("n_3d", 0), "n_2d": info.get("n_2d", 0),
                    }
        except Exception as e:
            with _LOCK:
                _OV_INFO[src_name] = {"error": str(e)[:200], "ts": time.time()}
        dt = time.time() - t0
        if fps_cap > 0 and dt < 1.0 / fps_cap:
            _STOP.wait(1.0 / fps_cap - dt)


# ── ④ 规格生成触发器（页面按钮 → 后台跑，不阻塞请求）──────────────
def _boxes_payload(cam: str = "arm") -> dict:
    """🖱 给页面用的可交互框清单(像素几何 + 稳定 id + 已删清单)。

    优先用叠加线程刚画出来的那份(与画面同帧); 没人看流时叠加线程没跑 ⇒ 现算一遍,
    免得好按钮点了没反应。老倪口径: 工具按钮点了必出结果。
    """
    cam = cam or "arm"
    with _LOCK:
        inf = dict(_OV_INFO.get(cam) or {})
    if inf.get("boxes"):
        return {"ok": True, "cam": cam, "src": "live", "ts": inf.get("ts"),
                "boxes": inf["boxes"], "deleted": inf.get("deleted") or [],
                "drawn": inf.get("drawn"), "n_3d": inf.get("n_3d"), "n_2d": inf.get("n_2d"),
                "spec_age_s": inf.get("spec_age_s"), "mode": inf.get("mode")}
    if _SO is None:
        return {"ok": False, "cam": cam, "msg": "scene_overlay 未加载", "boxes": []}
    try:
        spec = _SO.load_spec()
        # TCP 真值: 先用后台线程缓存的那份(与画面同源口径), 没有才同步读一次
        with _LOCK:
            tcp = _TCP_LATEST.get("tcp")
        if tcp is None:
            tcp = _SO.read_tcp(timeout=8, allow_ssh=True)
        blank = np.zeros((480, 640, 3), np.uint8)
        _img, info = _SO.draw_overlay(blank, spec, cam, tcp, None)
        return {"ok": True, "cam": cam, "src": "computed", "boxes": info.get("boxes") or [],
                "deleted": info.get("deleted") or [], "drawn": len(info.get("drawn") or []),
                "n_3d": info.get("n_3d", 0), "n_2d": info.get("n_2d", 0),
                "skipped": info.get("skipped"), "tcp_ok": tcp is not None}
    except Exception as e:                                                        # noqa: BLE001
        return {"ok": False, "cam": cam, "msg": str(e)[:200], "boxes": []}


def _boxes_edit(cam: str, ids, mode: str) -> dict:
    """🗑 删除/恢复叠加框(操作者点选后调用)。

    id 是 `origin|label` (同名重复的加 #2…), 由 `scene_overlay.draw_overlay` 生成 ⇒
    同一件东西在重新生成后 id 仍然一样, 所以"删掉的别再冒出来"能持久, 不靠内存状态。
    """
    cam = cam or "arm"
    ids = [str(i) for i in (ids or []) if str(i).strip()]
    if _SO is None:
        return {"ok": False, "msg": "scene_overlay 未加载"}
    if not ids and mode != "restore_all":
        return {"ok": False, "msg": "没给框 id (先在上面的框上点一下选中)"}
    spec = _SO.load_spec()
    del_map = spec.setdefault("deleted", {})
    cur = set(del_map.get(cam) or [])
    if mode == "delete":
        cur |= set(ids)
    elif mode == "restore":
        cur -= set(ids)
    else:                                  # restore_all
        cur = set()
    del_map[cam] = sorted(cur)
    spec["deleted"] = del_map
    _SO.save_spec(spec)
    # 立刻让页面能核对(不等下一帧叠加)
    with _LOCK:
        inf = _OV_INFO.get(cam)
        if isinstance(inf, dict):
            inf["deleted"] = sorted(cur)
    labels = sorted(x.split("|")[-1] for x in cur)
    return {"ok": True, "cam": cam, "deleted": sorted(cur), "n": len(cur),
            "labels": labels,
            "msg": ("🗑 已删除 %d 个框: %s" % (len(ids), "、".join(i.split("|")[-1] for i in ids)))
            if mode == "delete" else
            ("↩ 已恢复 %d 个框" % len(ids) if mode == "restore"
             else "↩ 已恢复全部（清空删除清单）"),
            "note": "删除只作用于本叠加层, 原始物体没动; 重新标注时会把已删项作为'不要再给'的指示传给大模型"}


def _deleted_labels(cam: str = "arm") -> list:
    if _SO is None:
        return []
    try:
        spec = _SO.load_spec()
        return sorted({x.split("|")[-1] for x in ((spec.get("deleted") or {}).get(cam or "arm") or [])})
    except Exception:                                                             # noqa: BLE001
        return []


_GEN_STATE = {"busy": None, "last": None, "ts": 0.0}
_GEN_KINDS = {"sim": "仿真场景投影", "scene": "场景契约", "vlm": "L5 大模型理解", "det": "真机检测"}

# 🧩 开放词汇分割 (SAM3) —— L2 感知原语的服务化调用 (2026-09-29)
#   为什么走独立进程: SAM3 = 848M/1008px, 显存 ≈2GB, 与推流/GUI 同进程会打架
#   (本机红线: 同刻仅一模型进程) ⇒ 真执行件是常驻服务 `tools/sam3_seg.py --serve --port 8796`,
#   这里只做**转发 + 落规格**(origin='seg', kind='mask'), 失败时如实把原因回给页面。
_SEG_URL = os.environ.get("ZMAX_SEG_URL", "http://127.0.0.1:8796")
# ⚠️ 概念词必须**英文** (2026-09-29 实测: SAM3 文本塔是 CLIP, 中文提示词返回 0 实例; "光模块"→0, "green connector"→6)
# 默认概念 = 实测在这台工位真帧上有命中的三个词 (socket/gripper/optical module 实测 0 实例)
_SEG_DEFAULT_TEXTS = os.environ.get("ZMAX_SEG_TEXT", "green connector,slot,metal pin")
_SEG_STATE = {"at": None, "cam": None, "texts": None, "count": 0, "ms": None, "err": None}


def _seg_run(cam: str = "arm", texts: str = "", three_d: bool = True, timeout: float = 180.0) -> dict:
    """调常驻分割服务: 一帧 + 概念提示词 → 所有实例掩膜, 并写进叠加规格 (origin='seg')"""
    ts = [t.strip() for t in (texts or "").split(",") if t.strip()]
    used_default = False
    if not ts:
        ts = [t.strip() for t in _SEG_DEFAULT_TEXTS.split(",") if t.strip()]
        used_default = True
    body = json.dumps({"cam": cam, "texts": ts, "three_d": bool(three_d),
                       "write_spec": True, "cam_name": cam,
                       "note": "叠加页按钮 🧩 开放词汇分割 (L2/SAM3)"}).encode("utf-8")
    t0 = time.time()
    try:
        req = urllib.request.Request(_SEG_URL + "/seg", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            j = json.loads(r.read().decode("utf-8"))
    except Exception as e:                                                    # noqa: BLE001
        err = "%s: %s" % (type(e).__name__, str(e)[:150])
        _SEG_STATE.update(at=time.strftime("%H:%M:%S"), cam=cam, texts=ts, count=0,
                          ms=None, err=err)
        print("[seg] ✗ 分割服务调用失败: %s (URL %s)" % (err, _SEG_URL), flush=True)
        return {"ok": False, "count": 0, "texts": ts,
                "msg": "分割服务未响应 (%s) — 先起: python tools/sam3_seg.py --serve --port 8796" % err}
    dt = (time.time() - t0) * 1000
    _SEG_STATE.update(at=time.strftime("%H:%M:%S"), cam=cam, texts=ts,
                      count=int(j.get("count") or 0), ms=j.get("ms"),
                      err=None if j.get("ok") else (j.get("err") or "服务返回 ok=false"))
    if not j.get("ok"):
        return {"ok": False, "count": 0, "texts": ts, "msg": "分割失败: %s" % (j.get("err") or j)}
    n3d = sum(1 for it in (j.get("instances") or []) if (it.get("c3d") or {}).get("ok"))
    print("[seg] ✓ %s · 概念=%s · 实例 %d (其中 3D 成功 %d) · 推理 %.0fms · 端到端 %.0fms"
          % (cam, ts, j.get("count") or 0, n3d, j.get("ms") or -1, dt), flush=True)
    return {"ok": True, "count": j.get("count"), "texts": ts, "ms": j.get("ms"),
            "end2end_ms": round(dt), "n_3d": n3d, "size": j.get("size"),
            "ts_used_default": used_default,
            "instances": [{"label": it.get("label"), "score": it.get("score"),
                           "area_px": it.get("area_px"), "box_xyxy": it.get("box_xyxy"),
                           "c3d": (it.get("c3d") if (it.get("c3d") or {}).get("ok") else None)}
                          for it in (j.get("instances") or [])],
            "msg": "🧩 分割完成: 概念 %s → %d 个实例掩膜%s · 推理 %.0fms"
                   % ("/".join(ts), j.get("count") or 0,
                      ("(默认概念)" if used_default else ""), j.get("ms") or -1)}



# 生成卡死上限(秒): VLM 实测 5~120s, 网络最坏 300s(gen_overlay_from_vlm 的 urlopen timeout)
# ⇒ 留足余量; 超了判卡死并自动解锁, 避免 busy 永久占位把 4 个按钮全变哑巴
_GEN_STALE_S = 360.0


def _gen_worker(kind: str, cam: str = "", hint: str = "") -> None:
    """生成一路的来源框。🎥 2026-09-27: 支持按相机生成 ——
    · sim/scene 走真几何投影(手眼) ⇒ **只对臂上相机成立**; 本机/USB 相机如实拒绝, 不假装画得上
    · vlm/det 是纯 2D 视觉 ⇒ 三路相机都能跑
    💬 2026-09-28 老倪: vlm 支持带**现场指示(hint)** 重新标注 —— 人删掉错的框 + 给方向,
       大模型按指示重标; 被删的 label 作为"不要再给"的负项一起传下去。
    """
    cam = cam or "arm"
    try:
        if kind in ("sim", "scene"):
            if cam != "arm":
                r = "✗ %s 只支持臂上相机（仿真框要手眼真几何, 本机/USB 相机未标定）" % _GEN_KINDS[kind]
            else:
                # ⚠️ 2026-09-28 修: 这里是 save_spec(build_from_sim()) **整体覆盖** ——
                #   会把 vlm/det 的框与"已删清单"一起抹掉(页面上表现=点一次「重建仿真元素」,
                #   别家的框全没了, 老倪点一下就能撞上)。改为**按 origin 合并**: 只换 sim。
                fresh = _SO.build_from_sim() if kind == "sim" else _SO.build_from_scene_state()
                fboxes = ((fresh.get("cameras") or {}).get("arm", {}).get("boxes")) or []
                spec = _SO.merge_origin(_SO.load_spec(), "arm", "sim", fboxes,
                                        {"at": time.strftime("%H:%M:%S"), "by": "重建仿真元素",
                                         "src": str(fresh.get("source", ""))[:120], "n": len(fboxes)})
                _SO.save_spec(spec)
                _kept = sorted({b.get("origin") for c in (spec.get("cameras") or {}).values()
                                for b in (c.get("boxes") or [])})
                r = "%s: %d 框 (源 %s) · 保留其它来源 %s" % (
                    _GEN_KINDS[kind], len(fboxes), fresh.get("source"), _kept)
        else:
            mod = __import__("gen_overlay_from_" + ("vlm" if kind == "vlm" else "det"))
            if kind == "vlm":
                r = mod.main_cli(cam=cam, hint=hint, negatives=_deleted_labels(cam))
            else:
                r = mod.main_cli(cam=cam)
    except Exception as e:
        r = "✗ %s/%s: %s" % (kind, cam, str(e)[:180])
    with _LOCK:
        _GEN_STATE.update(busy=None, last=r, ts=time.time())
    print("[gen] %s/%s → %s" % (kind, cam, r), flush=True)


def _spawn_gen(kind: str, cam: str = "", hint: str = "") -> str:
    """启动一次生成。

    ★ 卡死自愈: VLM 走网络(DeepSeek), 单次可长达 120~300s; 若网断/进程被卡,
      busy 标志会永久占位 ⇒ 页面上 4 个按钮全变哑巴(点了没反应)。所以超过
      上限 + 余量还不回收, 就判为卡死并自动解锁, 同时如实报出"上次占了多久"。
    """
    cam = cam or "arm"
    with _LOCK:
        b = _GEN_STATE["busy"]
        age = time.time() - _GEN_STATE.get("ts", 0)
        if b and age > _GEN_STALE_S:
            print("[gen] ⚠ 上一次 %s 已占 %.0fs 未回收(超上限 %.0fs), 判为卡死 → 自动解锁"
                  % (b, age, _GEN_STALE_S), flush=True)
            _GEN_STATE.update(last="⚠ 上一次 %s 卡死 %.0fs 已自动解锁" % (b, age))
            b = None
        if b:
            return "已有生成在跑: %s (已 %.0fs, 上限 %.0fs)" % (b, age, _GEN_STALE_S)
        _GEN_STATE.update(busy="%s/%s" % (kind, cam), ts=time.time())
    threading.Thread(target=_gen_worker, args=(kind, cam, hint), daemon=True).start()
    return "已启动: %s (%s · %s)%s" % (_GEN_KINDS.get(kind, kind), kind, cam,
                                      (" · 带指示「%s」" % hint.strip()[:40]) if (hint or "").strip() else "")


# ── HTTP 服务 ─────────────────────────────────────────────────
PAGE = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Z-MAX 旁路调试 · 实时视频流（压缩）</title>
<style>
 body{margin:0;background:#0b0f14;color:#e6edf3;font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif}
 header{padding:10px 14px;background:#111820;border-bottom:1px solid #223}
 h1{margin:0;font-size:16px;font-weight:600}
 .meta{color:#8b98a5;font-size:12px;margin-top:3px}
 .wrap{display:grid;grid-template-columns:1fr;gap:10px;padding:10px}
@media(min-width:900px){.wrap{grid-template-columns:1fr 1fr}}
@media(min-width:1400px){.wrap{grid-template-columns:1fr 1fr 1fr}}
 .card{background:#111820;border:1px solid #223;border-radius:10px;overflow:hidden}
 .card h2{margin:0;padding:8px 12px;font-size:13px;font-weight:600;background:#0e151c;
          border-bottom:1px solid #223;display:flex;justify-content:space-between}
 .tag{font-weight:400;color:#8b98a5;font-size:11px}
 img{display:block;width:100%;height:auto;background:#000}
 .note{padding:8px 12px;color:#8b98a5;font-size:11px;border-top:1px solid #223}
 .motion{margin:0 10px 10px;padding:10px 14px;background:#111820;border:1px solid #223;
         border-radius:10px;display:flex;align-items:center;gap:12px;font-size:14px;
         position:sticky;bottom:0}
 .motion b{color:#7ee787;font-size:15px}
 .dot{width:11px;height:11px;border-radius:50%;background:#555;flex:0 0 auto}
 .dot.on{background:#3fb950;box-shadow:0 0 10px #3fb950}
 .dot.off{background:#6e7681}
 code{color:#7ee787}
</style></head><body>
<header>
  <h1>🎥 Z-MAX 旁路调试 · 实时视频流（压缩版）</h1>
  <div class="meta">手臂相机 = Orin 经 ROS 传来（JPEG 压缩推流） · 本机相机 = 驱动直读（三相机: 臂上 + 笔记本内置 + MAXHUB 电视顶摄） · <span id="stat">—</span></div>
</header>
<div class="wrap">
  <div class="card">
    <h2>🦾 手臂相机 <span class="tag" id="t_arm">Orin → 4060</span></h2>
    <img src="/arm.mjpg" alt="arm">
    <div class="note">源: <code>/realsense/color/image_raw</code> (Orin) · 帧龄 <b id="age_arm">—</b></div>
  </div>
  <div class="card">
    <h2>💻 本机相机① <span class="tag" id="t_local">/dev/video__IDX__</span></h2>
    <img src="/local.mjpg" alt="local">
    <div class="note">源: <code>/dev/video__IDX__</code> · 帧龄 <b id="age_local">—</b></div>
  </div>
  <div class="card">
    <h2>📺 本机相机② <span class="tag" id="t_local2">MAXHUB 电视顶摄</span></h2>
    <img src="/local2.mjpg" alt="local2">
    <div class="note">源: <code>/dev/videoN 或 rtsp://</code> · 帧龄 <b id="age_local2">—</b></div>
  </div>
</div>
<div class="motion" id="motion">
  <span class="dot" id="dot"></span>
  <b id="m_dir">等待动作</b>
  <span id="m_pos">—</span>
  <span id="m_age" class="tag">—</span>
</div>
<script>
async function tick(){
  try{const r=await fetch('/stats');const s=await r.json();
    const a=s.arm,l=s.local,x=s.local2;
    const f=(o)=>{const p=document.getElementById('age_'+o[0]); if(p) p.textContent = o[1] ? (o[1].age_s.toFixed(2)+'s ('+o[1].fps.toFixed(1)+'fps)') : '未接';};
    f(['arm',a]);f(['local',l]);f(['local2',x]);
    const lb=(id,o)=>{const e=document.getElementById(id); if(e&&o&&o.label) e.textContent=o.label;};
    lb('t_arm',a);lb('t_local',l);lb('t_local2',x);
    document.getElementById('stat').textContent =
      (a?`手臂 ${a.kb_per_frame.toFixed(0)}KB/帧 ${a.compress_x.toFixed(0)}x压`:'手臂 -')+
      (l?`  |  相机① ${l.kb_per_frame.toFixed(0)}KB/帧`:'')+
      (x?`  |  相机② ${x.kb_per_frame.toFixed(0)}KB/帧`:'  |  相机② 未接');
  }catch(e){}
  try{const r2=await fetch('/motion');const m=await r2.json();
    const d=document.getElementById('dot');
    if(m.ok){
      document.getElementById('m_dir').textContent = m.dir || m.skill;
      document.getElementById('m_pos').textContent = 'Δ='+m.delta+'mm  pos='+m.pos;
      document.getElementById('m_age').textContent = m.age_s>=0 ? ('下发于 '+m.age_s+'s 前') : '';
      d.className = 'dot ' + (m.age_s>=0 && m.age_s<20 ? 'on' : 'off');
    } else { document.getElementById('m_dir').textContent='未读到动作'; }
  }catch(e){}
}
setInterval(tick,700);tick();
</script></body></html>"""


# ══════════════════════════════════════════════════════════════
# 📱 手机版场景叠加页 (Z-MAX APP 入口的跳转目标)
#    真源 = 仓库 tools/web/scene-overlay.html —— 改完不用重启(按 mtime 重读)
#    为什么由 4060 自己提供: 站点是 HTTPS, 页面里再取 http:// 的 MJPEG
#    属"混合内容"会被浏览器拦死 ⇒ 页面必须跟视频流同源(都是 http, 同一个端口)
# ══════════════════════════════════════════════════════════════
_MOBILE_CACHE = {"t": None, "b": b""}


def _mobile_page() -> bytes:
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "scene-overlay.html")
    try:
        m = os.path.getmtime(p)
        if _MOBILE_CACHE["t"] != m:
            with open(p, "rb") as f:
                _MOBILE_CACHE["b"] = f.read()
            _MOBILE_CACHE["t"] = m
        return _MOBILE_CACHE["b"]
    except Exception as e:
        return ("<!doctype html><meta charset=utf-8>"
                "<h2>📱 手机叠加页缺失</h2><p>%s</p><p>期望: %s</p>" % (e, p)).encode("utf-8")


_STATION_CACHE = {"t": None, "b": b""}


def _station_page() -> bytes:
    """🛰 工位总览页真源 = `tools/web/station.html`(按 mtime 热读)。

    2026-09-29: 原来页面是**本文件内嵌的 STATION_PAGE** ⇒ 改一个按钮就得重启推流服务,
    而重启会掐断现场正在看的 MJPEG 流(且授权真动随进程失效)。改成外部文件热读后,
    以后加/改按钮**不用重启**(没这个文件时退回内嵌副本, 行为与老版本一致)。
    """
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "station.html")
    try:
        m = os.path.getmtime(p)
        if _STATION_CACHE["t"] != m:
            with open(p, "rb") as f:
                _STATION_CACHE["b"] = f.read()
            _STATION_CACHE["t"] = m
        return _STATION_CACHE["b"]
    except Exception:                                                         # noqa: BLE001
        return STATION_PAGE.encode("utf-8")


# ══════════════════════════════════════════════════════════════
# 场景叠加页（老倪：把仿真场景的检测框嵌进真实视频流 + 按钮切换来源）
# ══════════════════════════════════════════════════════════════
OVERLAY_PAGE = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Z-MAX 场景叠加 · 真实视频流 + 仿真边界框</title>
<style>
 html,body{margin:0;height:100%;background:#0b0f14;color:#e6edf3;
   font:16px/1.5 -apple-system,Segoe UI,Roboto,sans-serif}
 body{display:flex;flex-direction:column;overflow:hidden}
 header{padding:8px 14px;background:#111820;border-bottom:1px solid #223;flex:0 0 auto}
 h1{margin:0;font-size:17px;font-weight:600}
 .meta{color:#8b98a5;font-size:12px;margin-top:2px}
 .bar{display:flex;flex-wrap:wrap;gap:6px;padding:7px 14px;background:#0e151c;
      border-bottom:1px solid #223;flex:0 0 auto;align-items:center}
 button{font:14px/1 inherit;padding:9px 13px;border-radius:8px;border:1px solid #2d3a47;
        background:#16202b;color:#e6edf3;cursor:pointer}
 button:hover{background:#1d2a37}
 button.on{background:#1f6feb;border-color:#1f6feb;color:#fff}
 button.go{background:#238636;border-color:#238636;color:#fff;font-weight:600}
 .sep{width:1px;height:22px;background:#223;margin:0 4px}
 /* 舞台: 吃满剩余高度 —— 图像尽量大 (老倪: 图像要大一些) */
 #stage{flex:1 1 auto;min-height:0;position:relative;background:#000}
 #stage img{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;
            display:none;cursor:zoom-in;background:#000}
 body.m_ov   #ov{display:block}
 body.m_raw  #raw{display:block}
 body.m_both #stage{display:grid;grid-template-columns:1fr 1fr;gap:6px;background:#0b0f14}
 body.m_both #stage img{position:static;display:block;height:100%}
 #tape{position:absolute;left:0;right:0;bottom:0;padding:5px 10px;background:rgba(8,12,16,.72);
       color:#7ee787;font:13px/1.4 ui-monospace,Menlo,Consolas,monospace;pointer-events:none;
       white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
 body.m_both #tape{position:static;grid-column:1/-1;background:#0b0f14}
 .foot{flex:0 0 auto;display:flex;gap:16px;flex-wrap:wrap;padding:6px 14px;background:#0e151c;
       border-top:1px solid #223;font-size:13px;color:#8b98a5}
 .foot b{color:#e6edf3}
 .lg{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:4px;vertical-align:-1px}
 .msg{flex:0 0 auto;padding:6px 14px;color:#d29922;font-size:13px;background:#0e151c}
/* 🖵 铺满窗口 (老倪: 「图要大一些」) —— 藏页眉/按钮/页脚, 舞台占满整窗; 画面自带真值带+底部 #tape 仍在 */
body.m_full header,body.m_full .bar,body.m_full .foot,body.m_full .msg{display:none}
body.m_full #stage{position:fixed;inset:0;z-index:5}
#exitfull{display:none}
body.m_full #exitfull{display:block;position:fixed;right:12px;top:12px;z-index:9;
  opacity:.30;font-size:13px;padding:7px 11px}
body.m_full #exitfull:hover{opacity:1}
/* 并排两格各自尽量大 (宽屏用满宽度: 单格 4:3 在宽屏上只能占 46% 宽 —— 老倪说的"小窗口") */
body.m_both #stage img{width:100%;height:100%;object-fit:contain}
code{color:#7ee787;font-size:12px}
</style></head><body class="m_both">
<header>
  <h1>🧩 场景叠加 · 真实视频流 + 仿真场景边界框</h1>
  <div class="meta">真实画面 = 原始视频流 · 框 = 仿真投影 / L5 大模型理解 / 真机检测（颜色区分，不混为一谈）· 点画面=全屏</div>
  <div class="meta" style="margin-top:4px">
    <a href="/room" style="color:#ffd98a;font-weight:700;font-size:15px">📱 手机现场页（全看相机 + 人机在环 + 远程操作）</a>
&#160;·&#160;<a href="/station" style="color:#7ee787;font-weight:600;font-size:15px">🛰 工位总览（6 路同屏: 三相机+深度图+金手指+表面检测 · 右侧手动控制机器人）→</a>
  </div>
</header>
<div class="bar">
  <button id="c_arm" class="on" onclick="setCam('arm')">🦾 臂上相机</button>
  <button id="c_local" onclick="setCam('local')">💻 笔记本内置</button>
  <button id="c_local2" onclick="setCam('local2')">📺 MAXHUB 顶摄</button>
  <span class="sep"></span>
  <button id="m_ov" onclick="setMode('m_ov')">🧩 叠加图</button>
  <button id="m_raw" onclick="setMode('m_raw')">📷 原始图</button>
  <button id="m_both" class="on" onclick="setMode('m_both')">▣ 并排</button>
  <span class="sep"></span>
  <button id="m_full" onclick="setFull(true)">🖵 铺满窗口</button>
  <button onclick="fs()">⛶ 真全屏</button>
</div>
<div class="bar">
  <button class="go" onclick="gen('sim')">🎯 仿真场景投影</button>
  <button class="go" onclick="gen('vlm')">🧠 L5 大模型理解</button>
  <button class="go" onclick="gen('scene')">📋 场景契约框</button>
  <button onclick="gen('det')">🔍 真机检测</button>
  <span class="sep"></span>
  <button onclick="load()">↻ 刷新</button>
</div>
<div id="msg" class="msg"></div>
<div id="stage">
  <img id="raw" src="/arm.mjpg" alt="raw" onclick="fs()">
  <img id="ov" src="/overlay/arm.mjpg" alt="overlay" onclick="fs()">
  <div id="tape">帧龄 —</div>
  <button id="exitfull" onclick="setFull(false)">✕ 退出铺满</button>
</div>
<div class="foot">
  <span>规格 <b id="mode">—</b></span>
  <span>更新 <b id="age">—</b></span>
  <span><span class="lg" style="background:#22c55e"></span>仿真 <b id="n_sim">0</b></span>
  <span><span class="lg" style="background:#00b0ff"></span>大模型 <b id="n_vlm">0</b></span>
  <span><span class="lg" style="background:#eb3c3c"></span>检测 <b id="n_det">0</b></span>
  <span><span class="lg" style="background:#888"></span>跳过 <b id="n_skip">0</b></span>
  <span>手眼 <b id="he">—</b></span>
  <span>TCP <b id="tcp">—</b></span>
  <span>画框 <b id="ov_tag">0</b></span>
  <span>源 <b id="src">—</b></span>
  <span>任务 <b id="gen">—</b></span>
  <span>跳过 <b id="skip">—</b></span>
</div>
<script>
let CAM='arm', MODE='m_both', t0=Date.now();
const CAMS=['arm','local','local2'];
function setCam(c){
  CAM=c; t0=Date.now();
  CAMS.forEach(n=>{const b=document.getElementById('c_'+n); if(b) b.className=(n===c)?'on':'';});
  document.getElementById('raw').src='/'+c+'.mjpg?t='+t0;
  document.getElementById('ov').src='/overlay/'+c+'.mjpg?t='+t0;
}
function setMode(m){
  MODE=m;
  // 🐛 原写法 document.body.className=m 会把 m_full(铺满) 一起抹掉 ⇒ 用 classList 增删
  document.body.classList.remove('m_ov','m_raw','m_both');
  document.body.classList.add(m);
  ['m_ov','m_raw','m_both'].forEach(x=>{
    const b=document.getElementById(x); if(b) b.className=(x===m)?'on':'';});
}
function setFull(v){
  // 🖵 铺满: 藏页眉/按钮/页脚, 舞台占满整窗(图因此大 ~1.6 倍); Esc 或右上角 ✕ 退出
  document.body.classList.toggle('m_full', !!v);
  const b=document.getElementById('m_full'); if(b) b.className = v ? 'on' : '';
}
document.addEventListener('keydown', e=>{ if(e.key==='Escape') setFull(false); });
function fs(){
  // 点画面 = 全屏 (要更大的图就再点一次退出)
  if(!document.fullscreenElement){ (document.documentElement.requestFullscreen||function(){}).call(document.documentElement); }
  else { (document.exitFullscreen||function(){}).call(document); }
}
async function gen(kind){
  const r=await fetch('/gen?kind='+kind+'&cam='+CAM); const j=await r.json();
  document.getElementById('msg').textContent='⏳ '+j.msg+'（大模型理解约需 1~2 分钟，跑完自动出现在画面里）';
  setTimeout(load,1500);
}
async function load(){
  try{
    const r=await fetch('/scene.json'); const s=await r.json();
    const inf=(s._overlay_info||{})[CAM]||{};
    const g=s._gen||{};
    document.getElementById('mode').textContent=s.mode||'空';
    document.getElementById('src').textContent=(s.source||'').split('/').slice(-1)[0]||'—';
    document.getElementById('age').textContent=s.updated_at||'—';
    const o=inf.origins||{};
    document.getElementById('n_sim').textContent=o.sim||0;
    document.getElementById('n_vlm').textContent=o.vlm||0;
    document.getElementById('n_det').textContent=o.det||0;
    document.getElementById('n_skip').textContent=(inf.skipped||[]).length;
    document.getElementById('he').textContent=inf.tcp_ok?'已标定（见画面真值带）':'—';
    document.getElementById('tcp').textContent=inf.tcp_ok?'实时读取中':'未读到';
    const sk=(inf.skipped||[]).map(x=>x[0]+'('+x[1]+')').join(' · ')||'—';
    document.getElementById('skip').textContent=sk;
    document.getElementById('gen').textContent=(g.busy?('跑: '+g.busy):(g.last||'空闲'));
    document.getElementById('ov_tag').textContent=(inf.drawn||0);
    if(g.last) document.getElementById('msg').textContent='✓ '+g.last;
    // 真值带: 帧龄口径与工位总览一致 —— 优先源端自报, 其次「源已静止」, 最后才本端帧龄
    const st=await (await fetch('/stats')).json();
    const sv=st['ov_'+CAM]||st[CAM]||{};
    let _sa;
    if(sv.src_age_s!==undefined&&sv.src_age_s!==null) _sa='源帧龄 '+sv.src_age_s+'s';
    else if(sv.stalled) _sa='⛔ 源已静止 '+Math.round(sv.stall_s)+'s';
    else _sa='帧龄 '+(sv.age_s!==undefined?sv.age_s+'s':'—');
    document.getElementById('tape').textContent =
      '相机 '+CAM+' · '+_sa+
      ' · 源 '+(sv.fps!==undefined?sv.fps+'fps':'—')+
      ' · 画框 '+((inf.origins?Object.entries(inf.origins).map(([k,v])=>k+v).join(' '):''))+
      ' · '+(inf.tcp_ok?'手眼OK':'无手眼')+
      ' · '+new Date().toLocaleTimeString();
  }catch(e){}
}
setInterval(load,1500);load();
</script></body></html>"""


# 🎥 2026-09-27 老倪(三相机): 通用相机路由 —— 新增相机源不用再改路由表
STATION_PAGE = r"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Z-MAX 工位总览 · 6 路同屏 + 手动控制</title>
<style>
*{box-sizing:border-box}
html,body{margin:0;min-height:100%;background:#0d1117;color:#e6edf3;
  font:16px/1.45 system-ui,"Noto Sans CJK SC","Microsoft YaHei",sans-serif;
  /* 2026-09-28 老倪: 「工位总览这个页面怎么无法上下移动？只能看到6个视频窗口，下面的用鼠标无法滚动」
     原布局把整页锁成 height:100% + main 固定 calc(100% - 62px) ⇒ 内容超出就永远滚不到
     (3 倍高的判据图把它撑破，下面的面板/按钮全都够不着) ⇒ 改成整页可滚动：只留最小高度。 */
  overflow-y:auto;overflow-x:hidden}
header{display:flex;align-items:center;gap:14px;padding:10px 16px;background:#161b22;
  border-bottom:1px solid #30363d;position:sticky;top:0;z-index:9}
h1{font-size:24px;margin:0;letter-spacing:.5px}
.hint{color:#8b949e;font-size:15px}
.sp{flex:1}
.clk{font-variant-numeric:tabular-nums;color:#8b949e;font-size:17px}
.warnbar{background:#4b2b1a;border:1px solid #d29922;color:#f0c674;padding:5px 10px;
  border-radius:8px;font-size:15px;max-width:60vw}
main{display:grid;grid-template-columns:minmax(0,1fr) 640px;gap:12px;padding:12px}
.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;align-content:start}
.panel{background:#161b22;border:1px solid #30363d;border-radius:12px;overflow:hidden;
  display:flex;flex-direction:column;min-height:0}
.cap{display:flex;justify-content:space-between;align-items:baseline;gap:8px;padding:7px 10px;
  border-bottom:1px solid #21262d}
.ttl{font-size:18px;font-weight:600}
.meta{font-size:14px;color:#8b949e;font-variant-numeric:tabular-nums;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.panel img{width:100%;display:block;background:#010409;aspect-ratio:4/3;object-fit:contain}
.note{padding:8px 10px;font-size:15px;color:#f0c674;background:#2a2012;
  border-top:1px solid #4b3a1a;line-height:1.5}
.note b{color:#ffd479}
.dim{color:#8b949e}
.ok{color:#3fb950}.wa{color:#d29922}.bad{color:#f85149}
/* ── 右侧控制台 ── */
aside{display:flex;flex-direction:column;gap:10px;overflow:auto;min-height:0;padding-right:2px}
.card{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:10px 12px}
.card h2{font-size:18px;margin:0 0 8px;color:#c9d1d9;letter-spacing:.3px}
.big{font-size:30px;font-weight:700;font-variant-numeric:tabular-nums;line-height:1.25}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.row+.row{margin-top:8px}
.k{font-size:15px;color:#8b949e}
button{background:#21262d;color:#e6edf3;border:1px solid #30363d;border-radius:10px;
  font-size:20px;padding:12px 10px;cursor:pointer;font-family:inherit;touch-action:manipulation}
button:hover:not(:disabled){background:#2d333b;border-color:#8b949e}
button:disabled{opacity:.4;cursor:not-allowed}
.seg button{padding:10px 12px;font-size:19px;min-width:56px}
.seg button.on{background:#1f6feb;border-color:#1f6feb;color:#fff;font-weight:700}
#armbar{display:flex;align-items:center;gap:12px;padding:12px 14px;border-radius:12px;
  border:1px solid #d29922;background:#2a2012;font-size:20px;font-weight:700;color:#f0c674;
  width:100%;text-align:left}
#armbar.on{border-color:#3fb950;background:#0f2b17;color:#7ee787}
#armbar .st{font-size:22px}
.pad{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:8px}
.pad button{height:92px;font-size:24px;font-weight:600}
.pad .mid{background:#0d1117;border-style:dashed;font-size:19px;color:#8b949e;cursor:default;
  display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px}
.pad .mid b{font-size:30px;color:#e6edf3}
.rot{display:grid;grid-template-columns:1fr auto auto;gap:8px;align-items:center;margin-top:8px}
.rot button{font-size:21px;padding:14px 12px;min-width:104px}
.rot .lbl{font-size:17px;color:#c9d1d9}
.flash{animation:fl .9s ease-out}
body.locked .pad button[data-skill],body.locked .rot button[data-skill]{opacity:.55}
@keyframes fl{0%{background:#1f6feb;border-color:#58a6ff}100%{background:#21262d}}
#msg{font-size:22px;font-weight:700;margin:2px 0 6px;word-break:break-all}
#lines{background:#0d1117;border:1px solid #21262d;border-radius:8px;padding:8px;margin:0;
  font:14px/1.5 ui-monospace,Consolas,monospace;color:#9fb0c0;white-space:pre-wrap;
  max-height:190px;overflow:auto}
label.arm{display:flex;gap:10px;align-items:flex-start;cursor:pointer}
input[type=checkbox]{width:22px;height:22px;margin-top:2px}
input.num{width:84px;background:#0d1117;border:1px solid #30363d;border-radius:8px;
  color:#e6edf3;font-size:20px;padding:8px;font-family:inherit}
@media (max-width:1500px){
  main{grid-template-columns:minmax(0,1fr);height:auto}
  .grid{grid-template-columns:repeat(2,minmax(0,1fr))}
  aside{overflow:visible}
}
@media (max-width:900px){.grid{grid-template-columns:1fr}}
</style></head><body>
<header>
  <h1>🛰 工位总览</h1>
  <span class="hint">6 路同屏 · 右侧手动控制 (X Y Z 平动 / A B C 绕轴旋转)</span>
  <span class="sp"></span>
  <span class="warnbar" id="warn" style="display:none"></span>
  <span class="clk" id="clk"></span>
</header>
<main>
  <section class="grid">
    <div class="panel"><div class="cap"><span class="ttl">🦾 机器人臂上 D405</span>
      <span class="meta" id="m_arm">…</span></div>
      <img id="i_arm" data-mode="snap" data-src="/snapshot/overlay_arm.jpg" data-every="800"></div>
    <div class="panel"><div class="cap"><span class="ttl">💻 笔记本内置相机</span>
      <span class="meta" id="m_local">…</span></div>
      <img id="i_local" data-mode="snap" data-src="/snapshot/overlay_local.jpg" data-every="400"></div>
    <div class="panel"><div class="cap"><span class="ttl">📺 MAXHUB 顶摄</span>
      <span class="meta" id="m_local2">…</span></div>
      <img id="i_local2" data-mode="snap" data-src="/snapshot/overlay_local2.jpg" data-every="400"></div>
    <div class="panel"><div class="cap"><span class="ttl">🌈 D405 深度图</span>
      <span class="meta" id="m_depth">…</span></div>
      <img id="i_depth" data-mode="snap" data-src="/snapshot/depth.jpg" data-every="1500">
      <div class="note" id="n_depth" style="display:none"></div></div>
    <div class="panel"><div class="cap"><span class="ttl">🔍 金手指检测 (工控机 10082)</span>
      <span class="meta" id="m_aoi_gold">…</span></div>
      <img id="i_aoi_gold" data-mode="mjpg" data-src="/aoi_gold.mjpg">
      <div class="row" style="padding:6px 10px 2px"><span class="seg" id="gview">
        <button data-stream="/aoi_gold.mjpg" class="on">判据图</button>
        <button data-stream="/aoi_gold_raw.mjpg">整板原图</button></span></div>
      <div class="note" id="n_aoi_gold" style="display:none"></div>
      <div class="row" style="padding:4px 10px 2px">
        <button onclick="shot(10082)">📸 拍一帧</button>
        <button onclick="aoiDetect(10082)" style="font-weight:600">🔍 请求检测</button>
        <span id="aoi_det_msg" style="margin-left:8px;font-size:12px;opacity:.85"></span>
        <script>
        /* 2026-09-28 老倪: 「增加一个请求按钮, 发出正常的检测命令, 工控机本地也可以保存图片」
           走本服务 POST /api/aoi/detect → 转发工控机产线正常命令 POST /capture_detect
           (相机拍照 + 后台 YOLO); 工控机自己把原图落盘(saved_incoming)。
           结果整段 JSON 打在下面 <pre> 里 —— 可选中复制, 不弹窗、不截断。 */
        async function aoiDetect(port){
          const m=document.getElementById('aoi_det_msg'), o=document.getElementById('aoi_det_out');
          m.textContent='⏳ 已发出检测命令, 等判决…'; o.style.display='block'; o.textContent='';
          try{
            const t0=performance.now();
            const r=await fetch(_u('/api/aoi/detect?port='+port),{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
            const j=await r.json();
            m.textContent=(j.ok===true?'✅ ':'❌ ')+(j.msg||j.err||j.err2||'见下方 JSON')
                          +'  · 用时 '+((performance.now()-t0)/1000).toFixed(1)+'s';
            o.textContent=JSON.stringify(j,null,1);
          }catch(e){ m.textContent='❌ 请求失败: '+e; }
        }
        </script>
        <pre id="aoi_det_out" style="display:none;margin:4px 10px 8px;padding:8px;max-height:220px;overflow:auto;
             background:#0b1018;color:#cfe3ff;font-size:11px;line-height:1.45;border-radius:6px;
             white-space:pre-wrap;word-break:break-all;user-select:text"></pre>
        <label class="arm" style="font-size:15px;color:#8b949e">
          <input type="checkbox" id="auto82" style="width:18px;height:18px" checked>
          <span>自动取景(没照片时现拍一张)</span></label></div></div>
    <div class="panel"><div class="cap"><span class="ttl">🔍 表面检测 (工控机 10083)</span>
      <span class="meta" id="m_aoi_surface">…</span></div>
      <img id="i_aoi_surface" data-mode="mjpg" data-src="/aoi_surface.mjpg">
      <div class="note" id="n_aoi_surface"></div>
      <div class="row" style="padding:4px 10px 10px">
        <button onclick="shot(10083)">📸 拍帧 (真拍一次)</button></div></div>
  </section>
  <aside>
    <div class="card">
      <h2>🕹 手动控制台</h2>
      <div id="armbar">
        <button id="armbtn" onclick="armClick()" style="font-size:19px;padding:14px 16px;min-width:230px"
          title="现场安全: 真动必须先显式授权"><span id="armtxt">🔓 授权真动</span></button>
        <div style="flex:1">
          <div id="armstate2" style="font-size:19px">⛔ <b>未授权</b> · 点方向键只会算目标, <b>机械臂不会动</b></div>
          <span class="hint" id="armhint">现场安全: 只让守在机器旁的人授权 —— 先点「🔓 授权真动」, 再点一次「⚠️ 现场确认无人」。授权 5 分钟自动失效; 刷新页面也回到未授权(不记忆)。</span></div>
      </div>
      <div class="row" style="margin-top:10px">
        <span class="big" id="robot" style="font-size:20px">读取中…</span></div>
      <div class="hint" id="robot2"></div>
      <div class="big" id="tcp" style="margin-top:8px">X — Y — Z —</div>
      <div class="hint" id="tcp2"></div>
    </div>
    <div class="card">
      <h2>⏩ 平动 (走 /move_line)</h2>
      <div class="row"><span class="k">步长</span>
        <span class="seg" id="sX"><button data-v="5">5</button><button data-v="10" class="on">10</button>
        <button data-v="20">20</button><button data-v="50">50</button><button data-v="100">100</button></span>
        <span class="k">mm</span></div>
      <div class="pad">
        <span class="mid"></span>
        <button data-skill="L2.forward" data-p="d_mm">⏩ 前进<br><span class="hint">+X</span></button>
        <span class="mid"></span>
        <button data-skill="L2.left" data-p="d_mm">⬅️ 左移<br><span class="hint">+Y</span></button>
        <span class="mid">步长<b id="stepshow">10</b>mm</span>
        <button data-skill="L2.right" data-p="d_mm">➡️ 右移<br><span class="hint">−Y</span></button>
        <span class="mid"></span>
        <button data-skill="L2.backward" data-p="d_mm">⏪ 后退<br><span class="hint">−X</span></button>
        <span class="mid"></span>
        <button data-skill="L2.lift" data-p="d_mm">⬆️ 抬升<br><span class="hint">+Z</span></button>
        <span class="mid"></span>
        <button data-skill="L2.lower" data-p="d_mm">⬇️ 下降<br><span class="hint">−Z</span></button>
        <span class="mid"></span>
      </div>
      <div class="hint" style="margin-top:8px">键盘: ↑↓←→ = 前后左右 · PgUp/PgDn = 升降 (真动时同样受执行器 1.5s 间隔限制)</div>
    </div>
    <div class="card">
      <h2>🔄 绕轴旋转 (走 /move_pose, 位置不动)</h2>
      <div class="row"><span class="k">角度</span>
        <span class="seg" id="sA"><button data-v="1">1</button><button data-v="5" class="on">5</button>
        <button data-v="10">10</button><button data-v="20">20</button></span>
        <span class="k">°</span></div>
      <div class="rot"><span class="lbl">A 绕工具X轴 · 俯仰</span>
        <button data-skill="L2.rot_a_neg" data-p="deg">↻ −A <span class="hint">5°</span></button>
        <button data-skill="L2.rot_a_pos" data-p="deg">↺ +A <span class="hint">5°</span></button></div>
      <div class="rot"><span class="lbl">B 绕工具Y轴 · 倾侧</span>
        <button data-skill="L2.rot_b_neg" data-p="deg">↻ −B <span class="hint">5°</span></button>
        <button data-skill="L2.rot_b_pos" data-p="deg">↺ +B <span class="hint">5°</span></button></div>
      <div class="rot"><span class="lbl">C 绕工具Z轴 · 自转</span>
        <button data-skill="L2.rot_c_neg" data-p="deg">↻ −C <span class="hint">5°</span></button>
        <button data-skill="L2.rot_c_pos" data-p="deg">↺ +C <span class="hint">5°</span></button></div>
      <div class="row" style="margin-top:8px"><span class="k">速度 (相对量 1~60+)</span>
        <span class="seg" id="sSpd"><button data-v="8" class="on">8 慢·默认</button>
        <button data-v="20">20</button><button data-v="40">40</button><button data-v="60">60 快</button></span>
        <input class="num" id="spd" value="8"></div>
      <div class="hint" style="margin-top:6px">速度是相对量: <b>8 很慢</b>(一次动作可能十几~几十秒才停, 停下前
        驱动可能报一次 wait_until_idle 超时 —— <b>那是超时标记, 不是失败</b>, 看 TCP 有没有变就知道动没动);
        想快用 40/60。键盘: A/B/C 加 Shift = 反向; 单次 ≤30°(执行层守卫)。整页没有软急停, 急停请用示教器。</div>
    </div>
    <div class="card">
      <h2>📋 最近一次动作 (可复制)</h2>
      <div id="msg">—</div>
      <div class="row"><button id="copyb" onclick="copylog()">📄 复制原始日志</button>
        <button id="mq" onclick="moveReal()" style="display:none">🔓 授权真动(现场确认无人)</button></div>
      <pre id="lines">(点上面的按钮，这里出执行器的原始回执)</pre>
    </div>
    <div class="card">
      <h2>🛡 安全</h2>
      <div class="hint" id="armstate"></div>
      <div class="hint">急停请用示教器 / 现场急停按钮 —— 本页<b>没有</b>软急停，也不提供未验证的停止指令。
        真动前三查应: 上电 on · 无急停 · 无碰撞。</div>
    </div>
  </aside>
</main>
<script>
const $=(s)=>document.querySelector(s);
// 页面基址: 根目录访问(/station)时为空; 走子路径反代(/st/station, ECS 转发)时为 '/st'。
// 所有站内相对地址一律经 _u() 过一遍 —— 否则子路径反代下图片/接口都会打到站点根(404)。
// (2026-09-28 老倪: 「8793 这个通道推流到 ECS」)
const B=(location.pathname.replace(/\/[^/]*$/,'')||'');
const _u=(u)=>(typeof u==='string'&&u.charAt(0)==='/')?(B+u):u;
let STEP_MM=10, STEP_DEG=5;
/* 🔐 ARMED 不再写死: 由**服务端授权状态**决定(默认 false=未授权), 见 applyAuth()。
   老倪 2026-09-27: 「页面的授权真动 / 现场安全 / 授权」 —— 默认必须是未授权, 真动要人显式两步确认。 */
let ARMED=false, AUTH_LEFT=0, ARMWIN=300, AUTH_IP='', AUTH_PENDING=0;
function seg(id,cb){document.querySelectorAll('#'+id+' button').forEach(b=>b.onclick=()=>{
  document.querySelectorAll('#'+id+' button').forEach(x=>x.classList.remove('on'));
  b.classList.add('on'); cb(b.dataset.v);});}
seg('sX',v=>{STEP_MM=parseFloat(v); $('#stepshow').textContent=STEP_MM;
  document.querySelectorAll('.pad button[data-p=d_mm] .hint').forEach(h=>h.textContent=STEP_MM+'mm');});
seg('sA',v=>{STEP_DEG=parseFloat(v); document.querySelectorAll('.rot .hint').forEach(h=>h.textContent=STEP_DEG+'°');});
seg('sSpd',v=>{ $('#spd').value=v; });
function hhmmss(a){const d=new Date(Date.now()-a*1000);const p=n=>String(n).padStart(2,'0');
  return p(d.getHours())+':'+p(d.getMinutes())+':'+p(d.getSeconds());}
function fmt(x,n){return (x===null||x===undefined)?'—':Number(x).toFixed(n);}
async function post(url,body,ms){
  const ac=new AbortController(); const t=setTimeout(()=>ac.abort(), ms||20000);
  try{
    const r=await fetch(_u(url),{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body||{}),signal:ac.signal});
    return await r.json();
  } finally { clearTimeout(t); }
}
async function getj(url,ms){
  const ac=new AbortController(); const t=setTimeout(()=>ac.abort(), ms||8000);
  try{
    const r=await fetch(_u(url),{cache:'no-store',signal:ac.signal});
    return await r.json();
  } finally { clearTimeout(t); }
}
function _btns(on){document.querySelectorAll('button[data-skill]').forEach(b=>b.disabled=!on);}
function paintArm(){
  const b=$('#armbar'), on=ARMED;
  b.classList.toggle('on',on);
  $('#armtxt').textContent = on ? '🔒 立即撤销授权'
                                : (AUTH_PENDING?'⚠️ 再点一次: 现场确认无人':'🔓 授权真动');
  $('#armstate2').innerHTML = on
    ? ('✅ <b>真动已授权</b> · 剩 <b>'+Math.floor(AUTH_LEFT/60)+'分'
       +String(Math.max(0,Math.floor(AUTH_LEFT%60))).padStart(2,'0')+'秒</b>后自动失效 · 授权IP '+(AUTH_IP||'本机'))
    : '⛔ <b>未授权</b> · 点方向键只会算目标, <b>机械臂不会动</b>';
  $('#armhint').textContent = on
    ? '现场安全: 授权期内每点一次方向键, 机械臂就真的动一次(速度按下面档位, 执行器 1.5s 间隔); 人离开前点左边「🔒 立即撤销授权」。'
    : '现场安全: 只让守在机器旁的人授权 —— 点「🔓 授权真动」→ 再点一次「⚠️ 现场确认无人」。授权 '
      +Math.round(ARMWIN/60)+' 分钟自动失效; 刷新页面也回到未授权(不记忆)。';
  document.body.classList.toggle('locked',!on);
}
async function armClick(){
  if(ARMED){                                   // 撤销
    const j=await post('/ctl/arm',{on:false},8000);
    ARMED=false; AUTH_LEFT=0; paintArm();
    $('#msg').textContent=(j.msg||'🔒 已撤销授权: 现在点方向键不会动臂'); $('#msg').className='wa';
    return;
  }
  if(!AUTH_PENDING){                           // 第 1 步: 进入待确认(6s 内必须再点一次)
    AUTH_PENDING=Date.now(); paintArm();
    $('#msg').textContent='⚠️ 已按第 1 步 —— 确认机器旁没人、手不在臂内, 再点一次按钮上的「⚠️ 再点一次: 现场确认无人」才真正授权';
    $('#msg').className='wa';
    setTimeout(()=>{ if(AUTH_PENDING && Date.now()-AUTH_PENDING>6000){AUTH_PENDING=0;paintArm();} },6500);
    return;
  }
  AUTH_PENDING=0;                              // 第 2 步: 真授权
  const j=await post('/ctl/arm',{on:true,note:'页面两步确认(现场安全)'},8000);
  ARMED=!!j.armed; AUTH_LEFT=j.left_s||0; ARMWIN=j.window_s||ARMWIN; AUTH_IP=j.ip||'';
  paintArm();
  $('#msg').textContent=(j.msg||'✅ 真动已授权'); $('#msg').className='ok';
}
function applyAuth(a){                          // 服务端状态是唯一真相(到期/别人撤销都会同步过来)
  if(!a) return;
  const was=ARMED;
  ARMED=!!a.armed; AUTH_LEFT=a.left_s||0; ARMWIN=a.window_s||ARMWIN; AUTH_IP=a.ip||'';
  if(was&&!ARMED){
    const ls=a.last_stop||null, fresh=ls&&ls.ts&&(Date.now()/1000-ls.ts<180);
    let extra='';
    if(fresh&&ls.stopped) extra=' ⏹ 已对**在途动作**下达停止(/robot_stop 成功) —— 臂不会再多走。';
    else if(fresh) extra=' ⏹ 近 3 分钟内没有已下发的动作, 无需叫停。';
    else extra=' ⚠️ 已经下发到控制器的动作无法收回(慢速指令会走完), 只能等它到位或按急停 —— 本次已自动尝试叫停在途动作。';
    $('#msg').textContent='⌛ 授权已到期(或已被撤销) —— 自动回到未授权(现场安全)。要继续操作就先重新授权'+extra;
    $('#msg').className='wa';
  }
  paintArm();
}
function moveReal(){ armClick(); }              // 兼容旧按钮名
function flash(btn){try{btn.classList.remove('flash');void btn.offsetWidth;btn.classList.add('flash');}catch(e){}}
async function move(btn,force){
  const skill=btn.dataset.skill, p=btn.dataset.p;
  const v=(p==='deg')?STEP_DEG:STEP_MM;
  const spd=parseFloat($('#spd').value||'8');
  _lastMove={skill:skill,p:p,v:v};
  const real=ARMED;   // 🔐 只有已授权才真下发(服务端还会再拦一次); 未授权一律 dry-run 演练
  _btns(false); flash(btn);
  const unlock=setTimeout(()=>_btns(true),15000);   // 兜底: 请求卡住也必须把按钮放开
  $('#msg').textContent='下发中… (最多等 15s)'; $('#msg').className='wa';
  $('#mq').style.display='none';
  try{
    const j=await post('/ctl/move',{skill:skill,[p]:v,speed:spd,arm:real?1:0},18000);
    const _el=(typeof j.elapsed_s==='number')?(' · 用时 '+j.elapsed_s.toFixed(1)+'s'):'';
    $('#msg').textContent=(j.ok?(j.dry?'🧪 ':'✅ ')+j.msg+_el:'⛔ '+j.msg+_el)
      +'  (对上 X/Y/Z 看有没有变就知道动没动)';
    $('#msg').className=(j.ok?(j.dry?'wa':'ok'):'bad');
    $('#lines').textContent=(j.lines&&j.lines.length?j.lines.join('\n'):'(执行器还没有回执)');
    if(j.denied||(j.ok&&j.dry)){           // 未授权点了 → 给**授权入口**(不绕闸门), 绝不"点了没反应"
      $('#mq').style.display='';
      $('#mq').textContent='🔓 授权真动(现场确认无人) —— 授权完再点一次刚才那个方向键';
    }
  }catch(e){
    $('#msg').textContent='请求没发出去/超时: '+e+' —— 若反复如此, 请关掉其它本机页面(浏览器对同一端口只有 6 条连接)';
    $('#msg').className='bad';
  }
  clearTimeout(unlock); _btns(true);
  poll();
}
let _lastMove=null;
async function moveReal(){ if(_lastMove) move(_lastMove,true); }
document.querySelectorAll('button[data-skill]').forEach(b=>b.onclick=()=>move(b));
function copylog(){
  const t=$('#lines').textContent+'\n'+$('#msg').textContent;
  navigator.clipboard.writeText(t).then(()=>{$('#msg').textContent='✅ 已复制到剪贴板';
    $('#msg').className='ok';},()=>{$('#msg').textContent='复制失败, 请手动选择文本';$('#msg').className='bad';});
}
async function shot(port){
  $('#msg').textContent='拍帧中(工控机要真拍一张并跑检测，可能要几十秒)…'; $('#msg').className='wa';
  try{const j=await post('/api/aoi/capture?port='+port,{},100000);
    $('#msg').textContent=(j.ok?'✅ ':'⛔ ')+('HTTP '+j.http+' '+(j.msg||'')+(j.got_image?' · 已取到图并显示':''));
    $('#msg').className=(j.ok?'ok':'bad');
    $('#lines').textContent=JSON.stringify(j,null,1);}catch(e){$('#msg').textContent='失败: '+e;}
  poll();
}
function panel(id,st,label){
  const m=$('#m_'+id); if(!m) return;
  const _im=$('#i_'+id);
  const _live=(_im&&_im.dataset.mode==='mjpg')?' · 🔴 实时推流':'';
  if(!st){m.textContent='未接'+_live; return;}
  const _pre=(label?label+' · ':'');
  // ⛔ 源已断(如深度源文件停更): 如实报警, 绝不把上一帧旧图说成在线/新鲜
  if(st.dead){
    m.innerHTML=_pre+'<span class="bad">⛔ 源已断 '+fmt(st.dead_s,1)+'s（无新帧, 不显示假新鲜值）</span>'+_live;
    return;
  }
  if(!st.online){m.textContent=_pre+'无帧'+_live; return;}
  /* 🕒 帧龄口径 (2026-09-28 修): 标的是**源端那一帧**的年龄, 不是本端合成帧的年龄。
     ① 源端自报(X-Frame-Age-S 之类) → 直接用它的数;
     ② 源连续返回同一张图 ≥2s     → 醒目报「源已静止 Ns」(源卡死也不许显示 0.01s);
     ③ 都没有(本地相机)           → 本端帧龄即源帧龄, 照实标。 */
  let _age;
  if(st.src_age_s!==undefined&&st.src_age_s!==null){
    _age='源帧龄 '+fmt(st.src_age_s,2)+'s'
      +(st.src_age_s>3?'<span class="bad">（源端那帧本来就旧）</span>':'');
  }else if(st.stalled){
    _age='<span class="bad">⛔ 源已静止 '+fmt(st.stall_s,0)+'s（源卡死, 不是实时）</span>';
  }else{
    _age='本端帧龄 '+fmt(st.age_s,2)+'s';   // 源端没自报、也没卡死: 明说这是"本端"量, 不冒充源端时间
  }
  m.innerHTML=_pre+_age+' · '+fmt(st.fps,1)+'fps · '+fmt(st.kb_per_frame,0)+'KB'+_live;
}
let _pollBusy=false, _okAt=Date.now(), _pollAt=0;
async function poll(){
  if(_pollBusy) return; _pollBusy=true; _pollAt=Date.now();
  let s=null, aoi=null, st=null;
  try{
    const j=await getj('/station/status?t='+Date.now(),6000);
    s=j.ctl; aoi=j.aoi; st=j.stats; _okAt=Date.now();
    try{ window.__stats=st||{}; }catch(_e){}
    const a82=$('#auto82');
    if(a82){const want=((j.aoi_auto||{})['10082']!==false); if(a82.checked!==want) a82.checked=want;}
  }catch(e){}
  try{
    if(!s) throw 0;
    const r=s.robot||{}, tp=s.tcp||{};
    $('#robot').innerHTML=(r.operation&&r.operation!=='idle'
        ?'<span class="wa">🔄 移动中 </span>':'')
      +'上电 '+(r.power==='on'?'<span class="ok">on</span>':'<span class="bad">'+(r.power||'?')+'</span>')
      +' · 运行 <span class="'+(r.operation==='idle'?'ok':'wa')+'">'+(r.operation||'?')+'</span>'
      +' · 报警 '+(r.has_error?'<span class="bad">有 '+(r.error_code||'')+'</span>':'<span class="ok">无</span>');
    const _ce=r.controller_error_logs||[];
    if(r.has_error){
      const _bridge=(!(_ce.length)&&(r.error_context||'')==='wait_until_idle');
      $('#robot').innerHTML+='<div class="hint" style="margin-top:4px">'
        +(_bridge
          ? '⚠ 这是<b>我们桥自己记的超时标记</b>(等机械臂 30s 没回 idle), 控制器侧无报警; '
            +'按现场规矩<b>不要重发同一条指令</b>, 手动点一下别的轴或重新上电即可清除。'
          : '控制器报警详情: '+_ce.join(' | '))
        +'<br>'+(r.error_reason||'')+'</div>';
    }
    $('#robot2').textContent='急停 '+(r.estop?'有':'无')+' · 碰撞 '+(r.collision?'有':'无')
      +' · 状态帧龄 '+fmt(r.age_s,2)+'s ('+(s.motion_armed?'服务侧已授权真动':'服务侧未授权=只能演练')+')';
    if(tp.xyz&&tp.xyz[0]!==null&&tp.xyz[0]!==undefined){
      $('#tcp').textContent='X '+fmt(tp.xyz[0],4)+'   Y '+fmt(tp.xyz[1],4)+'   Z '+fmt(tp.xyz[2],4);
      $('#tcp').className='big'+(tp.stale?' bad':'');
    }else{$('#tcp').textContent='读不到位姿';$('#tcp').className='big bad';}
    /* 🦾 位姿口径 (2026-09-28 修): 读 ROKAE SDK 直采文件(5Hz, endInRef), 不再是停更 15h 的
       tcp_pose.json。文件龄 >10s ⇒ 判失效, 醒目报「源已静止 Ns」, 绝不当作实时位姿。 */
    const _qs=(tp.quat||[]).map(v=>fmt(v,3)).join(', ');
    $('#tcp2').innerHTML=(tp.stale
      ? '<span class="bad">⚠ 位姿源已静止 '+fmt(tp.file_age_s,1)+'s（ROKAE SDK 直采文件龄 >10s, 判定失效 —— 上面数字是最后一帧, 勿当实时位姿）</span>'
      : '源 '+((tp.src||'')||'—')+' · 帧龄 '+fmt(tp.age_s,2)+'s')
      +' · 四元数 '+(_qs||'—');
    $('#armstate').innerHTML=(s.motion_armed
      ? '服务侧 <span class="ok">已开 --ctl-motion</span>：授权后才真的动臂。'
      : '服务侧 <span class="bad">未开 --ctl-motion</span>：无论怎么点都只演练不下发。')
      +'<br>🔐 真动授权: '+(s.auth&&s.auth.armed
        ? '<span class="ok">已授权 · 剩 '+Math.floor((s.auth.left_s||0)/60)+'分'
          +String(Math.max(0,Math.floor((s.auth.left_s||0)%60))).padStart(2,'0')+'秒</span> · 授权IP '
          +(s.auth.ip||'—')+' · 授权时刻 '+hhmmss(Math.max(0,(s.server_time||0)-(s.auth.since||0)))
        : '<span class="bad">未授权</span> · 默认就是未授权, 要动臂先在上面授权(两步确认)');
    applyAuth(s.auth);
    /* 🌈 深度格 (2026-09-28 修): 深度源(容器 ros_depth_stream 落的 depth_raw.npy)早断更,
       原先显示「帧龄 57312s · 拍照 17:43:49 · 0.0fps」像"有一路在用" ⇒ 改成醒目「深度源已断 Ns」。 */
    const d=s.depth||{};
    if(d.dead){
      $('#m_depth').innerHTML='<span class="bad">⛔ 深度源已断 '+fmt(d.dead_s,1)+'s</span>';
      const _nd=$('#n_depth');
      if(_nd){
        _nd.style.display='block';
        _nd.innerHTML='深度源 = <code>/home/ubuntu/zmax_ss_remote/zmax_scene/depth_raw.npy</code>'
          +'(容器 ros_depth_stream 落盘)。该文件已 <b>'+fmt(d.dead_s,0)+'s</b> 没更新 ⇒ <b>源早断</b>。'
          +'这一格显示的是<b>最后一帧旧图</b>, 不是实时画面; 帧龄/拍照时刻一律按源停写那一刻算, 不伪造新鲜值。';
      }
    }else{
      $('#m_depth').innerHTML='帧龄 '+fmt(d.age_s,2)+'s · 拍照 '+hhmmss(d.age_s)
        +' · 中位 '+fmt(d.median_m,3)+'m · 有效 '+fmt(d.valid_pct,1)+'%';
      const _nd=$('#n_depth'); if(_nd) _nd.style.display='none';
    }
  }catch(e){}
  try{
    if(!st) throw 0;
    panel('arm',st.arm,(st.arm&&st.arm.label)||'');
    panel('local',st.local,(st.local&&st.local.label)||'');
    panel('local2',st.local2,(st.local2&&st.local2.label)||'');
    panel('depth',st.depth,'深度');
    panel('aoi_gold',st.aoi_gold,'判据图');
    panel('aoi_surface',st.aoi_surface,'表面');
  }catch(e){}
  if(aoi){
    const g=aoi['10082']||{}, sf=aoi['10083']||{};
    const gv=(g.verdict&&(g.verdict.count!==undefined||g.verdict.n!==undefined))
      ? ' · 上轮检出 '+((g.verdict.count!==undefined)?g.verdict.count:g.verdict.n)+' 个' : '';
    /* 🕒 金手指格帧龄也让**源端**说话: 工控机响应头 X-Frame-Age-S(g.src_frame_age_s)。
       没这个数才退回本端"取回来的时刻" —— 原来只报本端, 取回一张 100s 前的内存图也显示 0.9s。 */
    const _gsa=g.src_frame_age_s;
    $('#m_aoi_gold').innerHTML=(g.ok?'判据图在线':'取图失败')+gv
      +' · 源 '+fmt(g.kb,0)+'KB/帧 · '
      +((_gsa===null||_gsa===undefined)
        ? '本端帧龄 '+fmt(Date.now()/1000-(g.t||0),1)+'s'
        : '源帧龄 '+fmt(_gsa,2)+'s'+(_gsa>3?'<span class="bad">（工控机内存里那帧本就旧, 非实时）</span>':''));
    const ng=$('#n_aoi_gold');
    const noPhoto=/尚无照片|grab=1/.test(g.err||'');
    ng.style.display=((g.ok===false)||g.auto_grab)?'block':'none';
    if(g.ok===true&&g.auto_grab){
      ng.innerHTML='🔁 <b>自动取景</b>：工控机内存里没照片时替它现拍一张(最快 30s 一次) —— '
        +'这一格显示的是最近现拍的那张。<span class="dim">'+(g.note||'')+'</span>';
    } else if(g.ok===false){
      ng.innerHTML=(noPhoto
        ? '<b>工控机内存里当前没有照片</b> —— OPT 只在检测/拍照时留图, 它闲着的时候取就是 404「尚无照片」, '
          +'这就是这一格没画面的原因(不是我们链路断了)。<br>下面「自动取景」已默认打开: 发现没照片就替你现拍一张'
          +'(最快 30s 一次); 不想让它自己拍就取消勾选, 改用手点「📸 拍一帧」。拍过之后即使它又闲着, 这一格也保留最后一张。'
        : '取图失败：'+g.err);
      ng.innerHTML+='<br><span class="dim">源: '+(g.url||'')+'</span>';
    }
    const sfv=(sf.verdict&&(sf.verdict.count!==undefined))
      ? ' · 上轮判定 '+(sf.verdict.verdict||'')+' ('+sf.verdict.count+' 缺陷 · 推理 '+fmt(sf.verdict.ms,0)+'ms)' : '';
    if(sf.ok===true){ $('#m_aoi_surface').textContent+=' · 模型看的规范图 kind=crop'+sfv; }
    if(sf.ok===false){
      $('#n_aoi_surface').style.display='block';
      $('#n_aoi_surface').innerHTML='<b>这一格还没有画面 —— 10083 那台程序还是 v2(没有取图路由)</b><br>'
        +'实测: 10083 上 55 条候选路径全 404, 只有 POST /capture_detect; 工控机上也没有第二个 HTTP 服务能取表面相机的图。<br>'
        +'<b>修法已经备好, 只等在那台机器上执行</b>: 把 <code>surface_10083_work_v4.py</code> 拷进 '
        +'<code>D:\\xspace\\ultralytics_AOI</code>, 停掉 v2 的进程后运行它 —— 端口还是 10083, '
        +'<b>v2 的文件一个字都不改</b>(出问题原样回 v2)。<br>'
        +'<b>它一上线, 本页不用改一行就出图</b> —— 这一格一直在轮询 <code>GET /picture?kind=crop</code> '
        +'(v4 新增的取图路由), 还会顺带显示它上一轮的判定(OK/NG + 缺陷数 + 推理耗时)。<br>'
        +'现在能做的: 点「📸 拍帧」真拍一次(图会存到工控机 ./surface_images/, 但在 v2 下取不回来)。';
      const lc=sf.last_capture;
      if(lc) $('#n_aoi_surface').innerHTML+='<br>上次拍帧: HTTP '+lc.http+' '+(lc.msg||'')
        +(lc.got_image?' · 已取到图':(lc.how?' · '+lc.how:''));
    } else { $('#n_aoi_surface').style.display='none'; }
  }
  $('#clk').textContent=new Date().toLocaleTimeString();
  const lag=(Date.now()-_okAt)/1000;
  const w=$('#warn');
  if(lag>7){ w.style.display=''; w.textContent='⚠ 状态已 '+lag.toFixed(0)
      +'s 没更新 —— 浏览器对同一主机(端口)只有 6 条连接, 可能被别的页面占满了。'
      +'本页已改成只剩 2 条(状态+串行快照), 若还卡请关掉同一个浏览器里其它本机页面再刷新。'; }
  else { w.style.display='none'; }
  _pollBusy=false;
}
setInterval(()=>{ if(_pollBusy && Date.now()-_pollAt>8000){ _pollBusy=false; } }, 2000);
/* ── 取图调度: 本页**一格 MJPEG 都不用**(HTTP/1.1 对同一 host:port 只有 6 条连接, 长连接会把
      状态/按钮请求全饿死) —— 6 格全走单帧快照且全局串行, 常占 1 条连接。 */
const _q=[]; let _busy=false;
function _pump(){ if(_busy||!_q.length) return; _busy=true;
  const f=_q.shift(); f(()=>{_busy=false;_pump();}); }
function _enq(f){_q.push(f);_pump();}
const SNAPS=[...document.querySelectorAll('img[data-mode=snap]')].map(im=>({
  im:im, url:_u(im.dataset.src), every:parseInt(im.dataset.every||'2000'), due:0, miss:0}));
/* 🔴 2026-09-27 老倪: 「金手指和表面检测要实时推流」 —— 这两格改走 MJPEG 长连接
   (各占 1 条连接; 加上 1 条状态轮询 + 1 条串行快照 = ≤4 条, 仍在本机 6 条名额内)。
   源侧本身是"每次检测才有一张", 所以看起来是"有新图就立刻推" + 帧龄如实标。 */
document.querySelectorAll('img[data-mode=mjpg]').forEach(im=>{
  im.classList.add('live'); im.src=im.dataset.src+'?t='+Date.now();
});
/* 🔁 MJPEG 断线/停帧自愈 (2026-09-28 老倪: 「金手指和表面检测怎么没有图像」)
   根因: 推流进程一重启(换相机 / 守护纠正映射 / 控制台重新拉流), 这两格的长连接会**停在死连接**上
   —— 快照格每轮自己再请求所以自动恢复, MJPEG 不会 ⇒ 那两格永远空着(实测: 服务侧 /stats 帧序号在涨、
   curl 取流有真帧, 页面却是空的 ⇒ 问题在**页面连接**这一层)。
   判据(不猜, 都有数): ① img.onerror 立刻重连 ② 每 6s 比对 /stats 的 frames_served:
   在涨=连接活着; 连续 2 轮不涨 ⇒ 换 src(新时间戳)强制重连。 */
const MJPG=[...document.querySelectorAll('img[data-mode=mjpg]')].map(im=>({im:im, url:_u(im.dataset.src), seen:-1, still:0}));
MJPG.forEach(rec=>{ rec.im.onerror=()=>setTimeout(()=>{ rec.im.src=rec.url+'?t='+Date.now(); rec.still=0; },1500); });
setInterval(()=>{
  const st=window.__stats||{};
  MJPG.forEach(rec=>{
    const v=st[rec.im.id.replace(/^i_/,'')]; if(!v) return;
    const n=v.frames_served; if(n===undefined||n===null) return;
    if(rec.seen<0){ rec.seen=n; return; }
    if(n>rec.seen){ rec.seen=n; rec.still=0; return; }
    if(++rec.still>=2){ rec.im.src=rec.url+'?t='+Date.now(); rec.still=0; }
  });
}, 6000);
document.querySelectorAll('#gview button').forEach(b=>b.onclick=()=>{
  document.querySelectorAll('#gview button').forEach(x=>x.classList.remove('on'));
  b.classList.add('on');
  const im=$('#i_aoi_gold');                    // 现在是 MJPEG 流: 换 src 就等于换源(旧连接自动断)
  if(im) im.src=_u(b.dataset.stream)+'?t='+Date.now();
});
const _a82=$('#auto82');
if(_a82) _a82.onchange=async()=>{
  $('#msg').textContent='切换自动取景…'; $('#msg').className='wa';
  try{const j=await post('/api/aoi/auto?port=10082&on='+(_a82.checked?1:0),{},8000);
    $('#msg').textContent=(j.ok?'✅ ':'⛔ ')+(j.note||''); $('#msg').className=(j.ok?'ok':'bad');
  }catch(e){$('#msg').textContent='切换失败: '+e; $('#msg').className='bad';}
};
setInterval(()=>{
  const t=Date.now();
  const p=SNAPS.filter(x=>x.due<=t).sort((a,b)=>a.due-b.due)[0];
  if(!p) return;
  _enq(done=>{
    const u=p.url+'?t='+Date.now();
    const pre=new Image();
    pre.onload=()=>{ p.im.src=u; p.due=Date.now()+p.every; p.miss=0; done(); };
    pre.onerror=()=>{ p.due=Date.now()+Math.max(3000,p.every); p.miss++; done(); };
    pre.src=u;
  });
}, 250);
/* 键盘: 方向键 = X/Y 点动, PgUp/PgDn = Z, A/B/C(+Shift 反向) = 绕轴旋转 */
const KEYS={'ArrowUp':'L2.forward','ArrowDown':'L2.backward','ArrowLeft':'L2.left',
  'ArrowRight':'L2.right','PageUp':'L2.lift','PageDown':'L2.lower'};
addEventListener('keydown',(e)=>{
  const t=e.target.tagName;
  if(t==='INPUT'||t==='TEXTAREA') return;
  let skill=KEYS[e.key];
  if(!skill && /^[abcABC]$/.test(e.key)){
    const ax=e.key.toLowerCase();
    skill='L2.rot_'+ax+(e.shiftKey?'_neg':'_pos');
  }
  if(!skill) return;
  const b=document.querySelector('button[data-skill="'+skill+'"]');
  if(b && !b.disabled){ e.preventDefault(); move(b); }
});
poll(); setInterval(poll,1500);
</script></body></html>

"""


_RE_MJPG = re.compile(r"^/(?P<ov>overlay/)?(?P<name>[A-Za-z0-9_]+)\.mjpg$")
_RE_SNAP = re.compile(r"^/snapshot/(?P<ov>overlay_)?(?P<name>[A-Za-z0-9_]+)\.jpg$")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    station_port = 0        # 工位总览专用端口, main() 里按 --station-port 设

    def log_message(self, *a):  # 静音
        pass

    def do_GET(self):
        p = self.path.split("?")[0]
        if p in ("/", "/index.html"):
            body = PAGE.replace("__IDX__", str(self.server.local_dev)).encode("utf-8")
            self._send(200, "text/html; charset=utf-8", body)
        elif p in ("/overlay", "/overlay.html", "/scene", "/live"):
            # 🧩 2026-09-27: 叠加/现场实况页 —— 真源 = tools/web/scene-overlay.html(按 mtime 热读)。
            #   之前这里发的是本文件内嵌的 OVERLAY_PAGE 旧副本 ⇒ 改 html 不生效(内嵌副本只认 arm 那路)。
            #   /app 原先也被 room.html 那条分支**抢先命中**(死代码), 现一并归位到同一份真源。
            self._send(200, "text/html; charset=utf-8", _mobile_page())
        elif p.startswith("/dl/"):
            # 📦 2026-09-27 交付件下载(手机 APP 装包等): 只服务 tools/web/dl/ 这一个目录,
            #   文件名取 basename ⇒ 就算路径里塞 ../ 也穿不出去。
            _dl = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "dl")
            _fn = os.path.basename(p[len("/dl/"):])
            try:
                with open(os.path.join(_dl, _fn), "rb") as f:
                    _b = f.read()
                self._send(200, "application/vnd.android.package-archive"
                           if _fn.endswith(".apk") else "application/octet-stream", _b)
            except Exception as e:                                          # noqa: BLE001
                self._send(404, "text/plain; charset=utf-8",
                           ("没有这个文件: %s (%s)" % (_fn, e)).encode("utf-8"))
        elif p in ("/room", "/room.html", "/hil-live"):
            # 📱 2026-09-27 老倪: 手机 APP 现场页 —— 视频会议式看全工位相机 + 🙋 HIL 人机在环 + 🕹 远程操作
            #   页面本体独立成 tools/web/room.html(便于维护, 手机竖屏优先);
            #   HIL 部分直连本机 8795 的本地 HIL API = 与画布 n_hil 节点同一个大脑。
            #   ⚠ /app 与 /app.html 归 **场景叠加/现场实况页**(它们原来的分支被这里抢先命中成了死代码)。
            _rp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "room.html")
            try:
                with open(_rp, encoding="utf-8") as f:
                    _body = f.read()
                self._send(200, "text/html; charset=utf-8", _body.encode("utf-8"))
            except Exception as e:                                          # noqa: BLE001
                self._send(500, "text/plain; charset=utf-8",
                           ("room.html 读不到(%s): %s" % (_rp, e)).encode("utf-8"))
        elif p in ("/station", "/station.html", "/board"):
            # 🛰 工位总览: 6 窗同屏(3 相机 + 深度 + 金手指 + 表面) + 手动控制区
            # 老倪的浏览器里曾有两个窗口都开着本机页面, 把「同一主机 6 条连接」占满 ⇒
            # 本页的图/状态/按钮全排队(看起来就是"没图像 + 按钮点不动")。
            # 所以本页有**自己的端口**(--station-port, 默认 8793): 主端口的 /station 一律 302 过去,
            # 两个端口各自 6 条连接名额, 互不影响。
            sp = int(getattr(Handler, "station_port", 0) or 0)
            if sp and not getattr(self.server, "is_station", False):
                host = (self.headers.get("Host") or "").split(":")[0] or self.client_address[0]
                self.send_response(302)
                self.send_header("Location", "http://%s:%d%s" % (host, sp, p))
                self.send_header("Content-Length", "0")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            self._send(200, "text/html; charset=utf-8", _station_page())
        elif p in ("/app", "/app.html", "/m"):
            # 📱 手机版场景叠加页 (Z-MAX APP 首页「🧩 场景叠加」的跳转目标)
            self._send(200, "text/html; charset=utf-8", _mobile_page())
        elif p == "/scene.json":
            spec = _SO.load_spec() if _SO else {"error": "scene_overlay 未加载"}
            with _LOCK:
                spec = dict(spec)
                spec["_overlay_info"] = dict(_OV_INFO)
                spec["_gen"] = dict(_GEN_STATE)
            self._send(200, "application/json; charset=utf-8",
                       json.dumps(spec, ensure_ascii=False).encode("utf-8"))
        elif p == "/gen":
            kind = cam = hint = ""
            if "?" in self.path:
                for kv in self.path.split("?", 1)[1].split("&"):
                    if kv.startswith("kind="):
                        kind = kv.split("=", 1)[1]
                    elif kv.startswith("cam="):
                        cam = kv.split("=", 1)[1]
                    elif kv.startswith("hint="):
                        hint = urllib.parse.unquote_plus(kv.split("=", 1)[1])
            if _SO is None:
                msg = "scene_overlay 未加载，叠加能力不可用"
            else:
                msg = _spawn_gen(kind, cam, hint) if kind in _GEN_KINDS else "未知 kind=%s" % kind
            self._send(200, "application/json; charset=utf-8",
                       json.dumps({"msg": msg}, ensure_ascii=False).encode("utf-8"))
        elif p == "/seg":
            # 🧩 开放词汇分割 (SAM3): 概念提示词 → 所有实例掩膜(像素级), 写 origin='seg' 进叠加规格
            #    GET /seg?cam=arm&texts=光模块,插孔&three_d=1   (texts 空 = 用默认三个概念, 回执里标明)
            cam, texts, t3d = "arm", "", "1"
            if "?" in self.path:
                for kv in self.path.split("?", 1)[1].split("&"):
                    if kv.startswith("cam="):
                        cam = urllib.parse.unquote_plus(kv.split("=", 1)[1])
                    elif kv.startswith("texts=") or kv.startswith("text="):
                        texts = urllib.parse.unquote_plus(kv.split("=", 1)[1])
                    elif kv.startswith("three_d="):
                        t3d = kv.split("=", 1)[1]
            res = _seg_run(cam, texts, t3d not in ("0", "false", "no", "off"))
            self._send(200, "application/json; charset=utf-8",
                       json.dumps(res, ensure_ascii=False).encode("utf-8"))
        elif p == "/boxes":
            # 🖱 可交互框清单: 像素几何(3D 线框 8 角点 / 2D xyxy) + 稳定 id + 已删清单
            cam = "arm"
            if "?" in self.path:
                for kv in self.path.split("?", 1)[1].split("&"):
                    if kv.startswith("cam="):
                        cam = urllib.parse.unquote_plus(kv.split("=", 1)[1])
            self._send(200, "application/json; charset=utf-8",
                       json.dumps(_boxes_payload(cam), ensure_ascii=False).encode("utf-8"))
        elif p == "/arm.mjpg":
            self._mjpeg("arm")
        elif p == "/local.mjpg":
            self._mjpeg("local")
        elif p == "/overlay/arm.mjpg":
            self._mjpeg("ov_arm")
        elif p == "/overlay/local.mjpg":
            self._mjpeg("ov_local")
        elif p == "/aoi_modelin.png":
            # 🆕 v11: 模型**实际吃的那张**(960x960 同帧派生图) 原样转发 —— 无损 PNG,
            #   像素与喂进 YOLO 的逐位相同; 响应头带 md5/尺寸/编号, 便于与 /last_result 对账。
            try:
                _st, _raw, _hd = _aoi_modelin_get()
                self._send(_st, "image/png", _raw, extra={
                    "X-Zmax-Modelin-Md5": _hd.get("X-Zmax-Modelin-Md5", ""),
                    "X-Zmax-Modelin-HW": _hd.get("X-Zmax-Modelin-HW", ""),
                    "X-Zmax-Modelin-N": _hd.get("X-Zmax-Modelin-N", "")})
            except Exception as _e:                                               # noqa: BLE001
                self._send(502, "application/json; charset=utf-8",
                           _jbytes({"code": 502, "msg": "取模型输入图失败: %s" % str(_e)[:120]}))
        elif p == "/aoi_surface_modelin.png":
            # 🆕 2026-09-30: 表面 10083 的"模型实际吃的那张"(v12 起的 /picture?kind=modelin)
            try:
                _st, _raw, _hd = _aoi_modelin_get("", 10083)
                self._send(_st, "image/png", _raw, extra={
                    "X-Zmax-Modelin-Md5": _hd.get("X-Zmax-Modelin-Md5", ""),
                    "X-Zmax-Modelin-HW": _hd.get("X-Zmax-Modelin-HW", ""),
                    "X-Zmax-Modelin-N": _hd.get("X-Zmax-Modelin-N", "")})
            except Exception as _e:                                               # noqa: BLE001
                self._send(502, "application/json; charset=utf-8",
                           _jbytes({"code": 502, "msg": "取表面模型输入图失败: %s" % str(_e)[:120]}))
        elif p == "/aoi_surface_modelin_meta":
            try:
                _st, _raw, _hd = _aoi_modelin_get("&meta=1", 10083)
                self._send(_st, "application/json; charset=utf-8", _raw)
            except Exception as _e:                                               # noqa: BLE001
                self._send(502, "application/json; charset=utf-8",
                           _jbytes({"code": 502, "msg": str(_e)[:120]}))
        elif p == "/aoi_modelin_meta":
            try:
                _st, _raw, _hd = _aoi_modelin_get("&meta=1")
                self._send(_st, "application/json; charset=utf-8", _raw)
            except Exception as _e:                                               # noqa: BLE001
                self._send(502, "application/json; charset=utf-8",
                           _jbytes({"code": 502, "msg": str(_e)[:120]}))
        elif p == "/snapshot/arm.jpg":
            self._snapshot("arm")
        elif p == "/snapshot/local.jpg":
            self._snapshot("local")
        elif p == "/snapshot/overlay_arm.jpg":
            self._snapshot("ov_arm")
        elif p == "/snapshot/overlay_local.jpg":
            self._snapshot("ov_local")
        elif p == "/stats":
            self._send(200, "application/json; charset=utf-8",
                       json.dumps(self._stats(), ensure_ascii=False).encode("utf-8"))
        elif p == "/motion":
            self._send(200, "application/json; charset=utf-8", _jbytes(_motion_state()))
        elif p == "/ctl/status":
            self._send(200, "application/json; charset=utf-8", _jbytes(_ctl_status()))
        elif p == "/ctl/points":
            # 📍 1~7 号位状态(只读, GET 安全): 页面用它决定「绿按钮(有记录/可点) / 灰按钮(没记录)」。
            # 2026-09-30 老倪: 「有记录的点就是绿色按钮, 没有记录的点就是灰色按钮」。判据在服务端
            # (示教点库 + 注册表 + 白名单), 页面只画不算 —— 免得页面画出假绿(点了却没通道)。
            self._send(200, "application/json; charset=utf-8", _jbytes(_ctl_points()))
        elif p == "/ctl/log":
            # 📜 执行器日志尾(只读, GET 安全): 页面用它追「等安全裁决 → 受理·已下发 / 拒发」这一行。
            # 为什么需要: 带 VL 安全闸时, 一次动作的最终结果在 45~190s 后才落在执行器日志里,
            # 而 /ctl/move 的回执只有 9s 窗口 —— 没有这个接口页面就只能停在"已收到"上, 现场会判"没反应"。
            _n = 14
            for kv in (self.path.split("?", 1)[1] if "?" in self.path else "").split("&"):
                if kv.startswith("n="):
                    try:
                        _n = max(1, min(80, int(kv.split("=", 1)[1])))
                    except ValueError:
                        pass
            _sz = os.path.getsize(_L2_LOG) if os.path.exists(_L2_LOG) else 0
            _off = max(0, _sz - 60000)                      # 只看尾部 60KB(日志已 MB 级, 别整读)
            _t = _tail(_L2_LOG, _off, 60000)
            _ls = [l.strip() for l in _t.splitlines() if l.strip()][-_n:]
            _done = ""
            for l in _ls:
                if "受理:" in l or "🛑 被拦" in l or "⇒ 拒发" in l:
                    _done = l
            self._send(200, "application/json; charset=utf-8",
                       _jbytes({"ok": True, "n": len(_ls), "lines": _ls,
                                "done": bool(_done), "verdict": _done,
                                "log": _L2_LOG, "size": _sz}))
        elif p == "/station/status":
            # 🛰 页面只发**一条**状态请求 (3 条合并成 1) —— 见页面注释里的 HTTP/1.1 六连接坑
            payload = {"stats": self._stats(), "ctl": _ctl_status(),
                       "aoi_auto": _aoi_auto_status()}
            with _AOI_LOCK:
                payload["aoi"] = {str(k): dict(v) for k, v in _AOI_INFO.items()}
            self._send(200, "application/json; charset=utf-8", _jbytes(payload))
        elif p in ("/api/aoi/last_result", "/aoi/last_result"):
            # 🧾 2026-09-30: 页面「最后结果」按钮 → 工控机 GET /last_result(只读)
            _p = 10082
            for _kv in (self.path.split("?", 1)[1] if "?" in self.path else "").split("&"):
                if _kv.startswith("port="):
                    try:
                        _p = int(_kv.split("=", 1)[1])
                    except ValueError:
                        _p = 10082
            self._send(200, "application/json; charset=utf-8", _jbytes(_aoi_last_result(_p)))
        elif p == "/aoi/status":
            with _AOI_LOCK:
                d = {str(k): dict(v) for k, v in _AOI_INFO.items()}
            self._send(200, "application/json; charset=utf-8", _jbytes(d))
        else:
            # 🎥 2026-09-27: 通用路由 —— 任意相机源自动可用 (加相机不用改路由表)
            #   /<cam>.mjpg · /overlay/<cam>.mjpg · /snapshot/<cam>.jpg · /snapshot/overlay_<cam>.jpg
            m = _RE_MJPG.match(p)
            if m:
                self._mjpeg(("ov_" if m.group("ov") else "") + m.group("name"))
                return
            m = _RE_SNAP.match(p)
            if m:
                self._snapshot(("ov_" if m.group("ov") else "") + m.group("name"))
                return
            self._send(404, "text/plain", b"not found")

    def do_POST(self):
        """🕹 只有 POST 能触发动作(点动/拍帧) —— GET 一律不行。

        原因: 浏览器预取、截图工具、爬虫、甚至我自己的取证脚本都会 GET;
        绝不能因为一次预取就把机械臂动了 / 让产线相机拍一张。
        """
        p = self.path.split("?")[0]
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        body = {}
        if n:
            try:
                body = json.loads(self.rfile.read(n).decode("utf-8", "ignore"))
            except Exception:                                                     # noqa: BLE001
                body = {}
        if p in ("/ctl/arm", "/api/ctl/arm"):
            # 🔐 授权真动 / 撤销(只有 POST 能改, 且记 IP+时刻审计)
            on = bool((body or {}).get("on"))
            out = _auth_set(on, str(self.client_address[0]),
                            str((body or {}).get("note") or ("页面授权" if on else "页面撤销")))
            out.update({"ok": True, "code": 200,
                        "msg": ("✅ 真动已授权: %.0f 分钟内可直接操作, 到期自动失效" % (out["left_s"] / 60.0))
                        if on else "🔒 已撤销授权: 现在点方向键只算目标, 机械臂不会动"})
        elif p in ("/ctl/move", "/api/ctl/move"):
            out = _ctl_move(body if isinstance(body, dict) else {})
        elif p in ("/ctl/record_point", "/api/ctl/record_point"):
            # 📝 把当前 TCP 真值记成号位示教点(零运动, 不需要真动授权; 只允许 slot1~slot7)。
            #    2026-09-30 老倪: 「4 5 6 号位, 你能自己实现记录么？」 ⇒ 现场点动到位后一键记住。
            out = _ctl_record_point(body if isinstance(body, dict) else {})
        elif p in ("/boxes/delete", "/api/boxes/delete"):
            # 🗑 删除选中的叠加框(操作者点选后)
            out = _boxes_edit(str((body or {}).get("cam") or "arm"),
                              (body or {}).get("ids") or [], "delete")
        elif p in ("/boxes/restore", "/api/boxes/restore"):
            # ↩ 恢复: 给 ids 恢复这些; 不给 ids ⇒ 清空删除清单
            _ids = (body or {}).get("ids") or []
            out = _boxes_edit(str((body or {}).get("cam") or "arm"), _ids,
                              "restore" if _ids else "restore_all")
        elif p in ("/api/aoi/detect", "/aoi/detect"):
            # 2026-09-28 老倪: 「增加一个请求按钮, 发出正常的检测命令, 工控机本地也可以保存图片」
            #   发的是**产线正常检测命令** POST /capture_detect(触发相机拍照 + 后台 YOLO),
            #   工控机自己会把 incoming 原图落盘(回执里的 saved_incoming) —— 这里只做转发,
            #   再把判决(/last_result: verdict/count/defects/耗时)取回来给页面显示。
            #   必须 POST(与点动同规矩): 预取/爬虫的 GET 绝不能触发产线相机拍照。
            _port = 10082
            if "port=" in self.path:
                try:
                    _port = int(self.path.split("port=")[1].split("&")[0])
                except Exception:                                                # noqa: BLE001
                    _port = 10082
            out = _aoi_detect(_port)
        elif p in ("/api/aoi/capture", "/aoi/capture"):
            port = 10083
            for kv in (self.path.split("?", 1)[1] if "?" in self.path else "").split("&"):
                if kv.startswith("port="):
                    try:
                        port = int(kv.split("=", 1)[1])
                    except ValueError:
                        pass
            out = _aoi_capture(port, "aoi_surface" if port == 10083 else "aoi_gold")
        elif p in ("/api/aoi/auto", "/aoi/auto"):
            # 🔁 自动取景开关(只 POST 能改): 工控机内存里没照片时, 由本服务每 ≥30s 现拍一张
            port, on = 10082, None
            for kv in (self.path.split("?", 1)[1] if "?" in self.path else "").split("&"):
                if kv.startswith("port="):
                    try:
                        port = int(kv.split("=", 1)[1])
                    except ValueError:
                        pass
                elif kv.startswith("on="):
                    on = kv.split("=", 1)[1] not in ("0", "false", "off", "")
            if on is not None:
                _AOI_AUTO[port] = bool(on)
            out = {"ok": True, "port": port, "auto": bool(_AOI_AUTO.get(port)),
                   "aoi_auto": _aoi_auto_status(),
                   "note": "自动取景 %s" % ("开(工控机没照片时现拍一张, 最快30s一次)"
                                          if _AOI_AUTO.get(port) else "关(只在手动点「拍一帧」时拍)")}
        else:
            self._send(404, "text/plain", b"not found")
            return
        self._send(int(out.get("code") or 200) if isinstance(out, dict) else 200,
                   "application/json; charset=utf-8",
                   json.dumps(out, ensure_ascii=False).encode("utf-8"))

    def _send(self, code: int, ctype: str, body: bytes, extra: dict = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        for _k, _v in (extra or {}).items():
            if _v:
                self.send_header(_k, _v)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _snapshot(self, name: str):
        jpg, seq, _, _, _ = _get(name)
        if not jpg:
            self._send(503, "text/plain; charset=utf-8",
                       "该路还没有帧（检查相机/源）".encode("utf-8"))
            return
        self._send(200, "image/jpeg", jpg)

    def _mjpeg(self, name: str):
        self.send_response(200)
        self.send_header("Content-Type",
                         "multipart/x-mixed-replace; boundary=zmaxframe")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        last_seq = -1
        while not _STOP.is_set():
            # 🔴 2026-09-27 老倪: "有人在看这一格" 的心跳 —— AOI 两格靠它决定是否顶到设备上限连续触发
            _AOI_VIEW_TS[name] = time.time()
            jpg, seq, ts, src_ts, raw_kb = _get(name)
            if jpg is None or seq == last_seq:
                _STOP.wait(0.004)
                continue
            last_seq = seq
            try:
                self.wfile.write(b"--zmaxframe\r\n")
                self.wfile.write(b"Content-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(jpg)}\r\n".encode())
                self.wfile.write(f"X-Frame-Age-S: {time.time()-src_ts:.3f}\r\n".encode())
                self.wfile.write(b"\r\n")
                self.wfile.write(jpg)
                self.wfile.write(b"\r\n")
            except (BrokenPipeError, ConnectionResetError, OSError):
                break

    def _stats(self):
        now = time.time()
        out = {}
        # 🎥 2026-09-27: 原始路全报 (arm/local/local2); 叠加路只在真有帧时报
        # 🛰 2026-09-27 工位总览: 深度源与工控机两路也一并报 (页面靠这张表出每格帧龄)
        names = [n for n in ("arm", "local", "local2", "depth", "aoi_gold", "aoi_gold_raw",
                            "aoi_surface")
                 if _FRAMES.get(n)]
        names += [n for n in sorted(_FRAMES) if n.startswith("ov_")
                  and _FRAMES.get(n, {}).get("jpg") is not None]
        for name in names:
            jpg, seq, ts, src_ts, raw_kb = _get(name)
            kb = (len(jpg) / 1024.0) if jpg else 0.0
            with _LOCK:
                f = _FRAMES[name]
                hist = f.setdefault("_hist", [])
                hist.append((now, seq))
                if len(hist) > 60:
                    hist.pop(0)
                if len(hist) >= 2 and (hist[-1][0] - hist[0][0]) > 0.2:
                    fps = (hist[-1][1] - hist[0][1]) / (hist[-1][0] - hist[0][0])
                else:
                    fps = 0.0
                # 🕒 源端新鲜度取证 (帧龄口径修, 2026-09-28):
                #   src_age_s  = 源端自报的帧龄(响应头 X-Frame-Age-S), 没有 = None
                #   stall_s    = 源连续返回同一张图的时长(帧字节签名不变)
                _hdr = f.get("_hdr_age_s")
                _stall_since = float(f.get("_stall_since") or 0.0)
                _stall_s = round(now - _stall_since, 1) if _stall_since else 0.0
                _stalled = bool(_stall_since) and _stall_s >= _SRC_STALL_S
            out[name] = {
                "online": jpg is not None,
                "fps": round(fps, 2),
                "kb_per_frame": round(kb, 1),
                "raw_kb_per_frame": round(raw_kb, 1),
                "compress_x": round(raw_kb / kb, 1) if kb > 0 else 0.0,
                "age_s": round(now - src_ts, 2) if src_ts else -1.0,
                # ── 帧龄如实口径 ──
                "src_age_s": (round(float(_hdr), 2) if _hdr is not None else None),
                "stall_s": _stall_s,
                "stalled": _stalled,
                "age_basis": ("hdr" if _hdr is not None else ("stall" if _stalled else "local")),
                "frames_served": seq,
                "label": _CAM_LABEL.get(name.replace("ov_", ""), ""),
            }
            if name == "depth":
                # 🌈 深度格: 源文件停更 ⇒ 如实报「深度源已断 Ns」(不是"帧龄 5 万秒"那种含糊)
                _dd, _dd_s = _depth_src_dead()
                out[name]["dead"] = _dd
                out[name]["dead_s"] = _dd_s
                out[name]["src_file"] = DEPTH_NPY
        return out


def _v4l_name(idx: int) -> str:
    """读 /dev/videoN 的真实设备名 (页面/日志直接显示"到底哪个摄像头", 不靠猜)"""
    try:
        with open("/sys/class/video4linux/video%d/name" % idx, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8791)
    ap.add_argument("--quality", type=int, default=70, help="JPEG 质量 (60-80 推荐)")
    ap.add_argument("--fps", type=float, default=15.0, help="推流上限 fps")
    ap.add_argument("--arm-src", default="/home/ubuntu/zmax_ss_remote/cam_rs.png",
                    help="手臂相机帧来源 (tap 落盘 PNG, 慢速模式)")
    ap.add_argument("--arm-raw", action="store_true",
                    help="手臂走全速模式: 读 ros_arm_tap_raw.py 落的 /dev/shm 原始帧")
    ap.add_argument("--arm-raw-path", default="/dev/shm/zmax_arm.raw")
    ap.add_argument("--arm-meta-path", default="/dev/shm/zmax_arm.meta")
    ap.add_argument("--arm-http", default="",
                    help="手臂走高速通道: 从 Orin rs_fast_node 的 JPEG 端点取帧(如 http://192.168.23.66:8792/frame.jpg)")
    ap.add_argument("--arm-fps", type=float, default=30.0, help="手臂取帧上限 fps")
    ap.add_argument("--local-dev", type=int, default=0, help="相机①本机 /dev/videoN")
    ap.add_argument("--no-local", action="store_true", help="不启第一路本机相机")
    # 🎥 2026-09-27 老倪: 三相机兼容 —— 第二路本机相机 (MAXHUB 电视顶摄) 或网络相机
    ap.add_argument("--local2-dev", type=int, default=-1,
                    help="相机②本机 /dev/videoN (MAXHUB 电视顶摄; -1=关)")
    ap.add_argument("--local2-url", default="",
                    help="相机②走网络: http(s) JPEG/MJPEG 或 rtsp:// (MAXHUB 联网模式)")
    ap.add_argument("--no-local2", action="store_true", help="不启第二路相机")
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--overlay", action="store_true", default=False,
                    help="开启场景叠加（真实流 + 仿真/大模型/检测框；页面 /overlay）")
    ap.add_argument("--overlay-src", default="arm",
                    choices=["arm", "local", "local2", "both", "all"],
                    help="叠加哪几路 (both=arm+local; all=三路)")
    ap.add_argument("--overlay-fps", type=float, default=12.0, help="叠加渲染上限 fps")
    # 🌈🏭🕹 2026-09-27 老倪: 工位总览 6 窗 —— 深度源 / 工控机 OPT 检测源 / 手动控制闸门
    ap.add_argument("--depth-fps", type=float, default=4.0, help="深度源刷新上限 fps (源话题实测仅 ~0.24Hz)")
    ap.add_argument("--station-port", type=int, default=8793,
                    help="工位总览 /station 专用端口 (0=不另开, 直接在主端口出页)。"
                         "为什么要单独端口: 浏览器对**同一主机:端口**只有 6 条连接, "
                         "老倪同时开着别的本机页面时会把主端口占满 ⇒ 总览页图表全排队")
    ap.add_argument("--no-depth", action="store_true", help="不起深度源 (D405 深度图窗口)")
    ap.add_argument("--depth-npy", default=DEPTH_NPY, help="容器 ros_depth_stream 落的原始深度数组")
    ap.add_argument("--depth-meta", default=DEPTH_META, help="同上配套的元数据 JSON")
    ap.add_argument("--aoi-fps", type=float, default=1.0,
                    help="工控机 OPT 取图频率 (默认 0.25 = 每 4s; 原图 6MB/帧, 别调太高)")
    ap.add_argument("--no-aoi", action="store_true", help="不起工控机金手指/表面检测源")
    ap.add_argument("--ctl-motion", action="store_true",
                    help="⚠️ 允许页面「授权真动」真的下发运动 (不加则一律 dry-run 演练)")
    ap.add_argument("--ctl-auth-window", type=float, default=300.0,
                    help="🔐 真动授权有效期(秒, 默认 300); 页面每次授权后这么久内有效, 到期自动失效")
    args = ap.parse_args()

    print(f"🎥 Z-MAX 实时视频流（压缩）· JPEG q{args.quality} · 推流 ≤{args.fps}fps",
          flush=True)
    if args.arm_http:
        print(f"   手臂源(高速HTTP): {args.arm_http} ← Orin D405 直驱节点", flush=True)
        threading.Thread(target=arm_http_worker,
                         args=(args.arm_http, args.arm_fps),
                         daemon=True, name="arm-http").start()
    elif args.arm_raw:
        print(f"   手臂源(全速): {args.arm_raw_path} ← ros_arm_tap_raw.py", flush=True)
        threading.Thread(target=arm_raw_worker,
                         args=(args.arm_raw_path, args.arm_meta_path,
                               args.quality, args.fps),
                         daemon=True, name="arm-raw").start()
    else:
        print(f"   手臂源(慢速): {args.arm_src}", flush=True)
        threading.Thread(target=arm_worker,
                         args=(args.arm_src, args.quality, args.fps),
                         daemon=True, name="arm").start()
    _CAM_LABEL["arm"] = "🦾 机器人臂上 D405 (Orin)"
    if not args.no_local:
        _nm = _v4l_name(args.local_dev)
        _CAM_LABEL["local"] = ("💻 " + (_nm or ("/dev/video%d" % args.local_dev)))
        print(f"   相机① 本机: /dev/video{args.local_dev} = {_nm or '(无名)'}", flush=True)
        threading.Thread(target=local_worker,
                         args=(args.local_dev, args.quality, args.width,
                               args.height, args.fps, "local"),
                         daemon=True, name="local").start()
    # 🎥 三相机: 第二路 (MAXHUB 电视顶摄: 本机 USB 或网络流二选一)
    if not args.no_local2 and (args.local2_url or args.local2_dev >= 0):
        if args.local2_url:
            _CAM_LABEL["local2"] = "📺 " + args.local2_url.split("//")[-1][:34]
            print(f"   相机② 网络: {args.local2_url}", flush=True)
            threading.Thread(target=url_cam_worker,
                             args=(args.local2_url, args.fps, "local2", args.quality),
                             daemon=True, name="local2-url").start()
        else:
            _nm2 = _v4l_name(args.local2_dev)
            _CAM_LABEL["local2"] = ("📺 " + (_nm2 or ("/dev/video%d" % args.local2_dev)))
            print(f"   相机② 本机: /dev/video{args.local2_dev} = {_nm2 or '(无名)'}", flush=True)
            threading.Thread(target=local_worker,
                             args=(args.local2_dev, args.quality, args.width,
                                   args.height, args.fps, "local2"),
                             daemon=True, name="local2").start()

    # ── 场景叠加（老倪 2026-09-27）──
    if args.overlay:
        if _SO is None:
            print("   ⚠ 场景叠加: scene_overlay 未加载 ⇒ 叠加不可用（纯推流不受影响）", flush=True)
        else:
            he = _SO.load_handeye()
            _m = {"arm": ["arm"], "local": ["local"], "local2": ["local2"],
                  "both": ["arm", "local"], "all": ["arm", "local", "local2"]}
            srcs = _m.get(args.overlay_src, ["arm"])
            # TCP 真值改由后台线程刷, 叠加循环只取最新值(否则每 2s 一次 ssh 读会把帧率拖到 3fps)
            threading.Thread(target=_tcp_refresher, args=(2.0,), daemon=True,
                             name="tcp-refresh").start()
            for s in srcs:
                threading.Thread(target=overlay_worker, args=(s, args.overlay_fps),
                                 daemon=True, name="ov-" + s).start()
            print(f"   🧩 场景叠加: 已开 [{'+'.join(srcs)}] ≤{args.overlay_fps}fps · "
                  f"手眼 {'✓ |t|=%.0fmm' % (np.linalg.norm(he['X'][:3, 3]) * 1000) if he['ok'] else '✗未标定(仅臂上臂有真几何)'}"
                  f" · 规格 {_SO.SPEC_PATH}", flush=True)
            print("      注: 真几何投影(仿真框)只对**臂上相机**成立 —— 本机/USB 相机无手眼标定,"
                  " 那两路只画 检测/大模型 2D 框", flush=True)
            print(f"      叠加页: http://0.0.0.0:{args.port}/overlay", flush=True)

    # ── 🌈 深度源 (D405 深度图) ──
    if not args.no_depth:
        _CAM_LABEL["depth"] = "🌈 D405 深度图 (彩色化)"
        threading.Thread(target=_depth_worker,
                         args=(args.depth_npy, args.depth_meta, args.depth_fps),
                         daemon=True, name="depth").start()
        print(f"   🌈 深度源: {args.depth_npy} ≤{args.depth_fps}fps "
              f"(容器 ros_depth_stream.py 落盘; 话题实测 ~0.24Hz ⇒ 帧龄如实标)", flush=True)
    # ── 🏭 工控机 OPT 检测源 (10082 金手指 / 10083 表面) ──
    if not args.no_aoi:
        _aoi_note_init()
        _CAM_LABEL["aoi_gold"] = "🔍 金手指检测 (工控机 OPT)"
        _CAM_LABEL["aoi_gold_anno"] = "🧾 金手指检测框 (叠加结果)"
        _CAM_LABEL["aoi_surface"] = "🔍 表面检测 (工控机 OPT)"
        _CAM_LABEL["aoi_surface_raw"] = "🖼 表面检测整板原图 (工控机 OPT)"
        # 2026-09-28 老倪: 「工控机拍摄的照片与你的金手指判据图不一样, 要跟判据图保持一致」+
        #   「改成一样的, 产线可以切换」⇒ 金手指格改**口径感知** (见 _aoi_gold_worker 文档):
        #     口径 canonical(默认) = 老口径(kind=origin → 本地原比例+去倾角+3× → 900x332)
        #     口径 same           = 工控机送检那张(kind=crop 内存帧) 本地零加工直显 ⇒ 页面 == 模型输入
        #   页面上的「判据口径：规范/同一」按钮 = POST /api/aoi/caliber → 转发工控机 POST /caliber。
        threading.Thread(target=_aoi_gold_worker,
                         args=(10082, "aoi_gold", args.aoi_fps, "aoi_gold_raw", "aoi_gold_anno"),
                         daemon=True, name="aoi-gold").start()
        # 2026-09-30 老倪: 「表面检测也要增加判据图, 将光模块整体切割出来, 调整好水平状态, 不要背景;
        #   增加判据图 和 整板原图 两个按钮」⇒ 表面格改成:
        #     判据图 = 取工控机 v12.1 的 **kind=judge**(已在工控机切好模块+调平+定尺 1600x300) ⇒ 本地零加工;
        #     整板原图 = 低频取 kind=origin(原图缩图) ⇒ /aoi_surface_raw.mjpg。
        #   模型输入那张(1280 全幅规范图)不受影响, 仍可在 /aoi_surface_modelin.png 看。
        threading.Thread(target=_aoi_worker,
                         args=(10083, "aoi_surface", args.aoi_fps, "judge", False, True,
                               "aoi_surface_raw", "origin", 3),
                         daemon=True, name="aoi-surface").start()
        print(f"   🏭 工控机检测源: 10082 金手指(**口径感知**: canonical=本地 原比例+去倾角+3×→900×332 · "
              f"same=直接显示工控机送检那张 kind=crop, 零本地加工; 另推 /aoi_gold_anno.mjpg = 判据图+检测框) "
              f"+ 10083 表面 @≤{args.aoi_fps}Hz (只 GET 不触发拍照; /aoi_surface.mjpg=**判据图**(工控机 v12.1 切模块+调平) "
              f"· /aoi_surface_raw.mjpg=整板原图; 模型输入那张看 /aoi_surface_modelin.png) "
              f"· 两路都推 MJPEG: /aoi_gold.mjpg · /aoi_surface.mjpg", flush=True)
    # ── 🕹 手动控制闸门 (双重: 这里 + 页面勾选) ──
    _CTL["motion"] = bool(args.ctl_motion)
    _CTL_AUTH["window"] = max(30.0, float(args.ctl_auth_window))
    print("   🕹 手动控制: %s" % ("服务侧允许真动; 🔐 页面还需显式授权(默认未授权, 授权 %.0f 分钟自动失效)"
                                 % (_CTL_AUTH["window"] / 60.0)
                                 if args.ctl_motion else
                                 "仅演练(dry-run) —— 要真动加 --ctl-motion 重启本服务"), flush=True)

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    srv.local_dev = args.local_dev
    srv.is_station = False
    Handler.station_port = int(args.station_port or 0) if int(args.station_port or 0) != args.port else 0
    print(f"   ✅ 看板: http://0.0.0.0:{args.port}/   (手机/PC 同网可开)", flush=True)
    if Handler.station_port:
        try:
            st2 = ThreadingHTTPServer((args.host, Handler.station_port), Handler)
            st2.local_dev = args.local_dev
            st2.is_station = True
            threading.Thread(target=st2.serve_forever, daemon=True, name="station-port").start()
            print(f"   ✅ 工位总览: http://0.0.0.0:{Handler.station_port}/station  "
                  f"(6 路同屏 + 手动控制; 独立端口 = 独立 6 条连接名额)", flush=True)
            print(f"      (主端口 /station 会 302 跳到这里)", flush=True)
        except OSError as e:
            Handler.station_port = 0
            print(f"   ⚠️ 工位总览专用端口 {args.station_port} 起不来({e}) —— 退回主端口出页", flush=True)
            print(f"   ✅ 工位总览: http://0.0.0.0:{args.port}/station", flush=True)
    else:
        print(f"   ✅ 工位总览: http://0.0.0.0:{args.port}/station  (6 路同屏 + 手动控制)", flush=True)
    if args.overlay:
        print(f"   ✅ 叠加: http://0.0.0.0:{args.port}/overlay", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        _STOP.set()


if __name__ == "__main__":
    main()
