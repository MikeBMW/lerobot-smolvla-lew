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
import json
import os
import re
import sys
import threading
import time
import urllib.error
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
_FRAME_TPL = {"jpg": None, "ts": 0.0, "seq": 0, "src_ts": 0.0, "raw_kb": 0.0}
_FRAMES = {k: dict(_FRAME_TPL) for k in
           ("arm", "local", "local2", "depth", "aoi_gold", "aoi_surface",
            "ov_arm", "ov_local", "ov_local2")}
_OV_INFO = {}                        # 每路最近一次的叠加统计（画了多少框/跳过原因）
_CAM_LABEL = {}                      # 🎥 源名 → 真实相机名 (页面/画布直显"这是哪个摄像头")
_STOP = threading.Event()


def _put(name: str, jpg: bytes, src_ts: float, raw_kb: float) -> None:
    with _LOCK:
        f = _FRAMES.setdefault(name, dict(_FRAME_TPL))   # 新源自动注册
        f["jpg"] = jpg
        f["ts"] = time.time()
        f["seq"] += 1
        f["src_ts"] = src_ts or f["ts"]
        f["raw_kb"] = raw_kb


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
        try:
            with urllib.request.urlopen(url, timeout=2.0) as r:
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
        _put("arm", data, time.time(), last_len / 1024.0)
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
        try:
            with urllib.request.urlopen(url, timeout=2.0) as r:
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
        _put(frame_name, data, time.time(), len(data) / 1024.0)
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
_AOI_INFO = {}            # port → {ok, err, http, t, kb, verdict, kind, src}
_AOI_LOCK = threading.Lock()
_DEPTH_INFO = {}
# 🕹 手动控制: **服务级开关** —— 不加 --ctl-motion 时本进程只演练(dry), 真动需要
#   ①启动参数 --ctl-motion ②页面勾「授权真动」, 双重闸门(防止推流服务被当成遥控器)。
_CTL = {"motion": False, "min_gap": 1.5, "last_real": 0.0,
        "last": {"t": 0.0, "skill": "", "dry": True, "ok": False, "msg": "", "lines": []}}
_CTL_LOG = "/tmp/zmax_ctl.log"
_L2_FIFO = os.path.expanduser("~/zmax_data/l2_cmd.fifo")
# 允许的指令白名单: 技能 → (参数名, 最小, 最大)。**只认这些**, 别的技能(含点位/多阶段技能)
# 一律拒绝 —— 手动控制区是给"点动"用的, 不是通用技能下发口。
_CTL_SKILLS = {
    "L2.forward": ("d_mm", 5, 300), "L2.backward": ("d_mm", 5, 300),
    "L2.left": ("d_mm", 5, 300), "L2.right": ("d_mm", 5, 300),
    "L2.lift": ("d_mm", 5, 300), "L2.lower": ("d_mm", 5, 100),
    "L2.rot_a_pos": ("deg", 1, 30), "L2.rot_a_neg": ("deg", 1, 30),
    "L2.rot_b_pos": ("deg", 1, 30), "L2.rot_b_neg": ("deg", 1, 30),
    "L2.rot_c_pos": ("deg", 1, 30), "L2.rot_c_neg": ("deg", 1, 30),
}


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


def _aoi_frame(bgr, clean: bool = True, out: int = 900, quality: int = 78):
    """工控机原图(BGR) → 判据图 JPEG。

    ⚠️ 色彩顺序坑: `aoi_exposure_fix.clean_judge_frame` 内部按 **RGB** 加权算灰度(过曝/边缘),
    喂它 BGR 会把红的过曝带判成别的 ⇒ **进出各转一次**; 传错的表现是"判据图偏色/裁错行"。
    """
    img, meta = bgr, {}
    if clean:
        try:
            from aoi_exposure_fix import clean_judge_frame
            clean_rgb, meta = clean_judge_frame(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), out=out)
            if clean_rgb is not None:
                img = cv2.cvtColor(clean_rgb, cv2.COLOR_RGB2BGR)
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
_AOI_AUTO_MIN_S = 30.0


def _aoi_auto_status() -> dict:
    return {str(p): bool(_AOI_AUTO.get(p)) for p in (10082, 10083)}


def _aoi_note(port: int, **kw) -> None:
    with _AOI_LOCK:
        d = _AOI_INFO.setdefault(port, {})
        d.update(kw)
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
        _put(name, jpg, time.time(), 0.0)
    if port == 10082:
        fj = _aoi_full_frame(bgr)
        if fj:
            _put(name + "_raw", fj, time.time(), 0.0)


def _aoi_worker(port: int, name: str, fps: float, kind: str = "origin",
                clean: bool = True, verdict: bool = True, full_name: str = "") -> None:
    """🏭 工控机 OPT 检测图 → 帧槽。**只 GET, 不带 grab** ⇒ 取服务端内存里最近一张, 不触发拍照。

    · 10082 金手指: `/picture?kind=origin`(实测 6.07MB PNG/0.07s) → 去死白 → 判据图
      (`name`), 另存一张**整板缩图** (`full_name`); 顺带每轮读 `/last_result`。
    · 10083 表面: 实测**没有取图路由**(只有 POST /capture_detect) ⇒ 如实报「无取图路由」,
      面板给「拍帧」按钮 —— 点了才 POST 一次(一次一帧), 回执里带 base64 图就直接显示。
    """
    url = "http://192.168.23.23:%d/picture?kind=%s" % (port, kind)
    vurl = "http://192.168.23.23:%d/last_result" % port
    n = 0
    while not _STOP.is_set():
        t0 = time.time()
        n += 1
        code, raw, err = 0, b"", ""
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "zmax-station"})
            with urllib.request.urlopen(req, timeout=10) as r:
                code = r.status
                raw = r.read()
        except urllib.error.HTTPError as e:
            code, err = e.code, (e.read()[:200].decode("utf-8", "ignore") if hasattr(e, "read") else "")
        except Exception as e:                                                    # noqa: BLE001
            err = str(e)[:140]
        if code == 200 and raw:
            bgr = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
            if bgr is not None:
                jpg, _meta = _aoi_frame(bgr, clean=clean)
                if jpg:
                    _put(name, jpg, time.time(), len(raw) / 1024.0)
                if full_name:                              # 整板缩图 (面板上可切换到这一张)
                    fj = _aoi_full_frame(bgr)
                    if fj:
                        _put(full_name, fj, time.time(), len(raw) / 1024.0)
                _aoi_note(port, ok=True, src=name, url=url, http=code, kb=round(len(raw) / 1024.0, 1),
                          shape=[int(bgr.shape[0]), int(bgr.shape[1])], err="")
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
                          note=("自动取景: 刚替它现拍了一张" if _did_grab else
                                "自动取景: 工控机里没照片, 显示的是最近现拍的那张"))
            else:
                _aoi_note(port, ok=False, src=name, url=url, http=code,
                          err=("HTTP %d %s" % (code, err)).strip() or "取图失败")
        if verdict and port == 10082:
            try:
                with urllib.request.urlopen(vurl, timeout=6) as r:
                    v = json.loads(r.read().decode("utf-8", "ignore"))
                _aoi_note(port, verdict=v)
            except Exception as e:                                                # noqa: BLE001
                _aoi_note(port, verdict_err=str(e)[:100])
        time.sleep(max(0.2, 1.0 / max(0.1, fps)) - (time.time() - t0))


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
    if sid not in _CTL_SKILLS:
        return {"ok": False, "msg": "技能 %r 不在手动控制白名单里" % sid}
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
    speed = max(1.0, min(30.0, speed))            # 手动控制一律低速(实测默认 8)
    want_real = bool(req.get("arm")) and bool(_CTL["motion"])
    cmd = {"skill": sid, pname: val, "speed": speed}
    if not want_real:
        cmd["dry"] = True
        why = "服务未授权真动(--ctl-motion)" if not _CTL["motion"] else "页面未勾「授权真动」"
    else:
        why = ""
        gap = time.time() - float(_CTL["last_real"])
        if gap < float(_CTL["min_gap"]):
            return {"ok": False, "msg": "太快了(距上一条 %.1fs < %.1fs), 防连点把臂当摇杆刷"
                    % (gap, _CTL["min_gap"])}
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
    out = {"ok": True, "dry": not want_real, "skill": sid, "param": {pname: val}, "speed": speed,
           "msg": ("演练(未下发): %s" % why) if not want_real else "已下发(真动)",
           "elapsed_s": round(time.time() - t0, 2), "lines": lines}
    rec = {"t": time.time(), "skill": sid, pname: val, "speed": speed,
           "dry": not want_real, "lines": lines}
    _CTL["last"] = {"t": rec["t"], "skill": sid, "dry": not want_real, "ok": True,
                    "msg": out["msg"], "lines": lines}
    try:
        with open(_CTL_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return out


def _ctl_status() -> dict:
    """页面 1.5s 轮询用的一把抓状态: 三查 + TCP 位姿 + 最近运动 + 各路源心跳。"""
    st = _read_json(ROBOT_STATUS_JSON, {}) or {}
    tp = _read_json(TCP_JSON, {}) or {}
    with _LOCK:
        depth = dict(_DEPTH_INFO)
        aoi = {str(k): dict(v) for k, v in _AOI_INFO.items()}
    now = time.time()
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
        "tcp": {"xyz": tp.get("xyz"), "quat": tp.get("quat"), "age_s": _age(tp.get("t")),
                "frame_id": tp.get("frame_id", "")},
        "motion": _motion_state(),
        "depth": dict(depth, age_s=_age(depth.get("t"))),
        "aoi": aoi,
        "last_cmd": dict(_CTL["last"], age_s=_age(_CTL["last"].get("t"))),
        "server_time": now,
        "labels": dict(_CAM_LABEL),
    }


def _aoi_note_init() -> None:
    """开局就给两路 AOI 建个状态槽, 免得页面在首帧前读不到键"""
    for port, nm in ((10082, "aoi_gold"), (10083, "aoi_surface")):
        _aoi_note(port, ok=None, src=nm, err="启动中…")


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
            if need_tcp and time.time() - tcp_ts > 2.0:
                try:
                    tcp = _SO.read_tcp(timeout=20)
                except Exception:
                    tcp = None
                tcp_ts = time.time()
            extra = {
                "frame_age": "帧龄 %.1fs · 源 %s" % (max(0.0, time.time() - src_ts),
                                                    time.strftime("%H:%M:%S", time.localtime(src_ts))),
                "handeye": ("手眼 cam→tcp |t|=%.0fmm (%s/%s位姿)"
                            % (np.linalg.norm(he["X"][:3, 3]) * 1000, he.get("method"), he.get("n_poses")))
                           if he["ok"] else "手眼未标定 ⇒ 仿真框无法投影",
                "tcp": (("TCP=(%.4f, %.4f, %.4f) 实时真值" % tuple(tcp[:3])) if tcp is not None
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
                    }
        except Exception as e:
            with _LOCK:
                _OV_INFO[src_name] = {"error": str(e)[:200], "ts": time.time()}
        dt = time.time() - t0
        if fps_cap > 0 and dt < 1.0 / fps_cap:
            _STOP.wait(1.0 / fps_cap - dt)


# ── ④ 规格生成触发器（页面按钮 → 后台跑，不阻塞请求）──────────────
_GEN_STATE = {"busy": None, "last": None, "ts": 0.0}
_GEN_KINDS = {"sim": "仿真场景投影", "scene": "场景契约", "vlm": "L5 大模型理解", "det": "真机检测"}
# 生成卡死上限(秒): VLM 实测 5~120s, 网络最坏 300s(gen_overlay_from_vlm 的 urlopen timeout)
# ⇒ 留足余量; 超了判卡死并自动解锁, 避免 busy 永久占位把 4 个按钮全变哑巴
_GEN_STALE_S = 360.0


def _gen_worker(kind: str, cam: str = "") -> None:
    """生成一路的来源框。🎥 2026-09-27: 支持按相机生成 ——
    · sim/scene 走真几何投影(手眼) ⇒ **只对臂上相机成立**; 本机/USB 相机如实拒绝, 不假装画得上
    · vlm/det 是纯 2D 视觉 ⇒ 三路相机都能跑
    """
    cam = cam or "arm"
    try:
        if kind in ("sim", "scene"):
            if cam != "arm":
                r = "✗ %s 只支持臂上相机（仿真框要手眼真几何, 本机/USB 相机未标定）" % _GEN_KINDS[kind]
            else:
                spec = _SO.build_from_sim() if kind == "sim" else _SO.build_from_scene_state()
                _SO.save_spec(spec)
                r = "%s: %d 框 (源 %s)" % (_GEN_KINDS[kind],
                                          len(spec["cameras"]["arm"]["boxes"]), spec["source"])
        else:
            r = __import__("gen_overlay_from_" + ("vlm" if kind == "vlm" else "det")).main_cli(cam=cam)
    except Exception as e:
        r = "✗ %s/%s: %s" % (kind, cam, str(e)[:180])
    with _LOCK:
        _GEN_STATE.update(busy=None, last=r, ts=time.time())
    print("[gen] %s/%s → %s" % (kind, cam, r), flush=True)


def _spawn_gen(kind: str, cam: str = "") -> str:
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
    threading.Thread(target=_gen_worker, args=(kind, cam), daemon=True).start()
    return "已启动: %s (%s · %s)" % (_GEN_KINDS.get(kind, kind), kind, cam)


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
 code{color:#7ee787;font-size:12px}
</style></head><body class="m_ov">
<header>
  <h1>🧩 场景叠加 · 真实视频流 + 仿真场景边界框</h1>
  <div class="meta">真实画面 = 原始视频流 · 框 = 仿真投影 / L5 大模型理解 / 真机检测（颜色区分，不混为一谈）· 点画面=全屏</div>
  <div class="meta" style="margin-top:4px">
    <a href="/station" style="color:#7ee787;font-weight:600;font-size:15px">🛰 工位总览（6 路同屏: 三相机+深度图+金手指+表面检测 · 右侧手动控制机器人）→</a>
  </div>
</header>
<div class="bar">
  <button id="c_arm" class="on" onclick="setCam('arm')">🦾 臂上相机</button>
  <button id="c_local" onclick="setCam('local')">💻 笔记本内置</button>
  <button id="c_local2" onclick="setCam('local2')">📺 MAXHUB 顶摄</button>
  <span class="sep"></span>
  <button id="m_ov" class="on" onclick="setMode('m_ov')">🧩 叠加图</button>
  <button id="m_raw" onclick="setMode('m_raw')">📷 原始图</button>
  <button id="m_both" onclick="setMode('m_both')">▣ 并排</button>
  <button onclick="fs()">⛶ 全屏</button>
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
let CAM='arm', MODE='m_ov', t0=Date.now();
const CAMS=['arm','local','local2'];
function setCam(c){
  CAM=c; t0=Date.now();
  CAMS.forEach(n=>{const b=document.getElementById('c_'+n); if(b) b.className=(n===c)?'on':'';});
  document.getElementById('raw').src='/'+c+'.mjpg?t='+t0;
  document.getElementById('ov').src='/overlay/'+c+'.mjpg?t='+t0;
}
function setMode(m){
  MODE=m; document.body.className=m;
  ['m_ov','m_raw','m_both'].forEach(x=>{
    const b=document.getElementById(x); if(b) b.className=(x===m)?'on':'';});
}
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
    // 真值带: 帧龄直接取 /stats (跨域同源, 拿不到就留旧值)
    const st=await (await fetch('/stats')).json();
    const sv=st['ov_'+CAM]||st[CAM]||{};
    document.getElementById('tape').textContent =
      '相机 '+CAM+' · 帧龄 '+(sv.age_s!==undefined?sv.age_s+'s':'—')+
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
html,body{margin:0;height:100%;background:#0d1117;color:#e6edf3;
  font:16px/1.45 system-ui,"Noto Sans CJK SC","Microsoft YaHei",sans-serif}
header{display:flex;align-items:center;gap:14px;padding:10px 16px;background:#161b22;
  border-bottom:1px solid #30363d;position:sticky;top:0;z-index:9}
h1{font-size:24px;margin:0;letter-spacing:.5px}
.hint{color:#8b949e;font-size:15px}
.sp{flex:1}
.clk{font-variant-numeric:tabular-nums;color:#8b949e;font-size:17px}
.warnbar{background:#4b2b1a;border:1px solid #d29922;color:#f0c674;padding:5px 10px;
  border-radius:8px;font-size:15px;max-width:60vw}
main{display:grid;grid-template-columns:minmax(0,1fr) 640px;gap:12px;padding:12px;
  height:calc(100% - 62px)}
.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;align-content:start;
  overflow:auto;min-height:0}
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
      <img id="i_arm" data-mode="snap" data-src="/snapshot/arm.jpg" data-every="800"></div>
    <div class="panel"><div class="cap"><span class="ttl">💻 笔记本内置相机</span>
      <span class="meta" id="m_local">…</span></div>
      <img id="i_local" data-mode="snap" data-src="/snapshot/local.jpg" data-every="400"></div>
    <div class="panel"><div class="cap"><span class="ttl">📺 MAXHUB 顶摄</span>
      <span class="meta" id="m_local2">…</span></div>
      <img id="i_local2" data-mode="snap" data-src="/snapshot/local2.jpg" data-every="400"></div>
    <div class="panel"><div class="cap"><span class="ttl">🌈 D405 深度图</span>
      <span class="meta" id="m_depth">…</span></div>
      <img id="i_depth" data-mode="snap" data-src="/snapshot/depth.jpg" data-every="1500"></div>
    <div class="panel"><div class="cap"><span class="ttl">🔍 金手指检测 (工控机 10082)</span>
      <span class="meta" id="m_aoi_gold">…</span></div>
      <img id="i_aoi_gold" data-mode="snap" data-src="/snapshot/aoi_gold.jpg" data-every="2000">
      <div class="row" style="padding:6px 10px 2px"><span class="seg" id="gview">
        <button data-src="/snapshot/aoi_gold.jpg" class="on">判据图</button>
        <button data-src="/snapshot/aoi_gold_raw.jpg">整板原图</button></span></div>
      <div class="note" id="n_aoi_gold" style="display:none"></div>
      <div class="row" style="padding:4px 10px 2px">
        <button onclick="shot(10082)">📸 拍一帧</button>
        <label class="arm" style="font-size:15px;color:#8b949e">
          <input type="checkbox" id="auto82" style="width:18px;height:18px" checked>
          <span>自动取景(没照片时现拍一张)</span></label></div></div>
    <div class="panel"><div class="cap"><span class="ttl">🔍 表面检测 (工控机 10083)</span>
      <span class="meta" id="m_aoi_surface">…</span></div>
      <img id="i_aoi_surface" data-mode="snap" data-src="/snapshot/aoi_surface.jpg" data-every="4000">
      <div class="note" id="n_aoi_surface"></div>
      <div class="row" style="padding:4px 10px 10px">
        <button onclick="shot(10083)">📸 拍帧 (真拍一次)</button></div></div>
  </section>
  <aside>
    <div class="card">
      <h2>🕹 手动控制台</h2>
      <button id="armbar" onclick="toggleArm()"><span class="st" id="armtxt">⛔ 演练模式</span>
        <span class="hint" id="armhint">点这里启用「真动」；不启用时按钮只算目标、不动机械臂</span></button>
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
      <div class="row" style="margin-top:8px"><span class="k">速度(相对量, 1~30+)</span>
        <span class="seg" id="sSpd"><button data-v="8" class="on">8 慢·默认</button>
        <button data-v="20">20</button><button data-v="40">40</button><button data-v="60">60 快</button></span>
        <input class="num" id="spd" value="8"></div>
      <div class="hint" style="margin-top:6px">速度是相对量: <b>8 很慢</b>(一次动作可能十几~几十秒才停, 停下前
        驱动可能报一次 wait_until_idle 超时 —— **那是超时标记不是失败**, 看 TCP 有没有变就知道动没动);
        想快用 40/60。键盘: A/B/C 加 Shift = 反向; 单次 ≤30°(执行层守卫)</div>
    </div>
    <div class="card">
      <h2>📋 最近一次动作 (可复制)</h2>
      <div id="msg">—</div>
      <div class="row"><button id="copyb" onclick="copylog()">📄 复制原始日志</button></div>
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
let STEP_MM=10, STEP_DEG=5, ARMED=false;
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
    const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body||{}),signal:ac.signal});
    return await r.json();
  } finally { clearTimeout(t); }
}
async function getj(url,ms){
  const ac=new AbortController(); const t=setTimeout(()=>ac.abort(), ms||8000);
  try{
    const r=await fetch(url,{cache:'no-store',signal:ac.signal});
    return await r.json();
  } finally { clearTimeout(t); }
}
function _btns(on){document.querySelectorAll('button[data-skill]').forEach(b=>b.disabled=!on);}
function toggleArm(){
  ARMED=!ARMED;
  const b=$('#armbar');
  b.classList.toggle('on',ARMED);
  $('#armtxt').textContent=ARMED?'✅ 真动已启用':'⛔ 演练模式';
  $('#armhint').textContent=ARMED
    ? '点这里关掉。启用后每次点击都会真下发(执行器侧 1.5s 间隔限制)'
    : '点这里启用「真动」；不启用时按钮只算目标、不动机械臂';
  try{localStorage.setItem('zmax_armed',ARMED?'1':'0');}catch(e){}
  const srv=$('#armstate');
  if(srv) srv.innerHTML+='';
  $('#msg').textContent=ARMED?'真动已启用 —— 点方向键会真的动机械臂':'已切回演练模式(只算目标不下发)';
  $('#msg').className=(ARMED?'bad':'wa');
}
function flash(btn){try{btn.classList.remove('flash');void btn.offsetWidth;btn.classList.add('flash');}catch(e){}}
async function move(btn){
  const skill=btn.dataset.skill, p=btn.dataset.p;
  const v=(p==='deg')?STEP_DEG:STEP_MM;
  _btns(false); flash(btn);
  const unlock=setTimeout(()=>_btns(true),15000);   // 兜底: 请求卡住也必须把按钮放开
  $('#msg').textContent='下发中… (最多等 15s)'; $('#msg').className='wa';
  try{
    const j=await post('/ctl/move',{skill:skill,[p]:v,speed:parseFloat($('#spd').value||'8'),
      arm:ARMED?1:0},18000);
    const _el=(typeof j.elapsed_s==='number')?(' · 用时 '+j.elapsed_s.toFixed(1)+'s'):'';
    $('#msg').textContent=(j.ok?(j.dry?'🧪 ':'✅ ')+j.msg+_el:'⛔ '+j.msg+_el)
      +'  (对上 X/Y/Z 看有没有变就知道动没动)';
    $('#msg').className=(j.ok?(j.dry?'wa':'ok'):'bad');
    $('#lines').textContent=(j.lines&&j.lines.length?j.lines.join('\n'):'(执行器还没有回执)');
  }catch(e){
    $('#msg').textContent='请求没发出去/超时: '+e+' —— 若反复如此, 请关掉其它本机页面(浏览器对同一端口只有 6 条连接)';
    $('#msg').className='bad';
  }
  clearTimeout(unlock); _btns(true);
  poll();
}
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
  if(!st){m.textContent='未接'; return;}
  if(!st.online){m.textContent=(label||'')+' 无帧'; return;}
  m.textContent=(label?label+' · ':'')+'帧龄 '+fmt(st.age_s,2)+'s · 拍照 '+hhmmss(st.age_s)
    +' · '+fmt(st.fps,1)+'fps · '+fmt(st.kb_per_frame,0)+'KB';
}
let _pollBusy=false, _okAt=Date.now(), _pollAt=0;
async function poll(){
  if(_pollBusy) return; _pollBusy=true; _pollAt=Date.now();
  let s=null, aoi=null, st=null;
  try{
    const j=await getj('/station/status?t='+Date.now(),6000);
    s=j.ctl; aoi=j.aoi; st=j.stats; _okAt=Date.now();
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
    if(tp.xyz){$('#tcp').textContent='X '+fmt(tp.xyz[0],4)+'   Y '+fmt(tp.xyz[1],4)+'   Z '+fmt(tp.xyz[2],4);}
    else{$('#tcp').textContent='读不到位姿';}
    $('#tcp2').textContent=(tp.frame_id||'')+' · 帧龄 '+fmt(tp.age_s,2)+'s · 四元数 '
      +((tp.quat||[]).map(v=>fmt(v,3)).join(', ')||'—');
    $('#armstate').innerHTML=s.motion_armed
      ? '服务侧 <span class="ok">已开 --ctl-motion</span>：启用上面的「真动」后按钮真的会动臂。'
      : '服务侧 <span class="bad">未开 --ctl-motion</span>：无论怎么点都只演练不下发。';
    const d=s.depth||{};
    $('#m_depth').textContent='帧龄 '+fmt(d.age_s,2)+'s · 拍照 '+hhmmss(d.age_s)+' · 中位 '+fmt(d.median_m,3)
      +'m · 有效 '+fmt(d.valid_pct,1)+'%';
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
    $('#m_aoi_gold').textContent=(g.ok?'判据图在线':'取图失败')+gv
      +' · 源 '+fmt(g.kb,0)+'KB/帧 · 拍照 '+hhmmss(Date.now()/1000-(g.t||0));
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
    if(sf.ok===false){
      $('#n_aoi_surface').style.display='block';
      $('#n_aoi_surface').innerHTML='<b>这一格没有实时画面 —— 工控机那台程序没开取图口</b><br>'
        +'本机用 OPTIONS 把 10083 上 50+ 条候选路径全探了一遍(零副作用), 只有 POST /capture_detect; '
        +'工控机上也没有第二个 HTTP 服务能取表面相机的图。<br>'
        +'修法在工控机侧: 粘 30 行加一条 /picture 路由 → <b>docs/patch/opt_surface_10083_add_picture_route.md</b>'
        +'(含 4 步上线自测)。补丁一上, 本页**不用改一行**就会自动出图(这一格一直在轮询取图)。<br>'
        +'现在能做的: 点「📸 拍帧」真拍一次(它会把图存到工控机 ./surface_images/, 但取不回来)。';
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
  im:im, url:im.dataset.src, every:parseInt(im.dataset.every||'2000'), due:0, miss:0}));
document.querySelectorAll('#gview button').forEach(b=>b.onclick=()=>{
  document.querySelectorAll('#gview button').forEach(x=>x.classList.remove('on'));
  b.classList.add('on');
  const p=SNAPS.find(x=>x.im.id==='i_aoi_gold');
  if(p){ p.url=b.dataset.src; p.every=(b.dataset.src.indexOf('raw')>=0)?3000:2000; p.due=0; }
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
try{ if(localStorage.getItem('zmax_armed')==='1') toggleArm(); }catch(e){}
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
        elif p in ("/overlay", "/overlay.html", "/scene"):
            self._send(200, "text/html; charset=utf-8", OVERLAY_PAGE.encode("utf-8"))
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
            self._send(200, "text/html; charset=utf-8", STATION_PAGE.encode("utf-8"))
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
            kind = cam = ""
            if "?" in self.path:
                for kv in self.path.split("?", 1)[1].split("&"):
                    if kv.startswith("kind="):
                        kind = kv.split("=", 1)[1]
                    elif kv.startswith("cam="):
                        cam = kv.split("=", 1)[1]
            if _SO is None:
                msg = "scene_overlay 未加载，叠加能力不可用"
            else:
                msg = _spawn_gen(kind, cam) if kind in _GEN_KINDS else "未知 kind=%s" % kind
            self._send(200, "application/json; charset=utf-8",
                       json.dumps({"msg": msg}, ensure_ascii=False).encode("utf-8"))
        elif p == "/arm.mjpg":
            self._mjpeg("arm")
        elif p == "/local.mjpg":
            self._mjpeg("local")
        elif p == "/overlay/arm.mjpg":
            self._mjpeg("ov_arm")
        elif p == "/overlay/local.mjpg":
            self._mjpeg("ov_local")
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
            self._send(200, "application/json; charset=utf-8",
                       json.dumps(_motion_state(), ensure_ascii=False).encode("utf-8"))
        elif p == "/ctl/status":
            self._send(200, "application/json; charset=utf-8",
                       json.dumps(_ctl_status(), ensure_ascii=False).encode("utf-8"))
        elif p == "/station/status":
            # 🛰 页面只发**一条**状态请求 (3 条合并成 1) —— 见页面注释里的 HTTP/1.1 六连接坑
            payload = {"stats": self._stats(), "ctl": _ctl_status(),
                       "aoi_auto": _aoi_auto_status()}
            with _AOI_LOCK:
                payload["aoi"] = {str(k): dict(v) for k, v in _AOI_INFO.items()}
            self._send(200, "application/json; charset=utf-8",
                       json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        elif p == "/aoi/status":
            with _AOI_LOCK:
                d = {str(k): dict(v) for k, v in _AOI_INFO.items()}
            self._send(200, "application/json; charset=utf-8",
                       json.dumps(d, ensure_ascii=False).encode("utf-8"))
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
        if p in ("/ctl/move", "/api/ctl/move"):
            out = _ctl_move(body if isinstance(body, dict) else {})
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
        self._send(200, "application/json; charset=utf-8",
                   json.dumps(out, ensure_ascii=False).encode("utf-8"))

    def _send(self, code: int, ctype: str, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
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
            out[name] = {
                "online": jpg is not None,
                "fps": round(fps, 2),
                "kb_per_frame": round(kb, 1),
                "raw_kb_per_frame": round(raw_kb, 1),
                "compress_x": round(raw_kb / kb, 1) if kb > 0 else 0.0,
                "age_s": round(now - src_ts, 2) if src_ts else -1.0,
                "frames_served": seq,
                "label": _CAM_LABEL.get(name.replace("ov_", ""), ""),
            }
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
    ap.add_argument("--aoi-fps", type=float, default=0.25,
                    help="工控机 OPT 取图频率 (默认 0.25 = 每 4s; 原图 6MB/帧, 别调太高)")
    ap.add_argument("--no-aoi", action="store_true", help="不起工控机金手指/表面检测源")
    ap.add_argument("--ctl-motion", action="store_true",
                    help="⚠️ 允许页面「授权真动」真的下发运动 (不加则一律 dry-run 演练)")
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
        _CAM_LABEL["aoi_surface"] = "🔍 表面检测 (工控机 OPT)"
        threading.Thread(target=_aoi_worker,
                         args=(10082, "aoi_gold", args.aoi_fps, "origin", True, True, "aoi_gold_raw"),
                         daemon=True, name="aoi-gold").start()
        threading.Thread(target=_aoi_worker,
                         args=(10083, "aoi_surface", args.aoi_fps, "origin", False, False),
                         daemon=True, name="aoi-surface").start()
        print(f"   🏭 工控机检测源: 10082 金手指(取原图→去死白判据图) + 10083 表面 "
              f"@≤{args.aoi_fps}Hz (只 GET 不触发拍照)", flush=True)
    # ── 🕹 手动控制闸门 (双重: 这里 + 页面勾选) ──
    _CTL["motion"] = bool(args.ctl_motion)
    print("   🕹 手动控制: %s" % ("⚠️ 已授权真动 (页面还需勾「授权真动」)"
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
