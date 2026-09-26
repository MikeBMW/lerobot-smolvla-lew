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
import json
import os
import re
import sys
import threading
import time
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
           ("arm", "local", "local2", "ov_arm", "ov_local", "ov_local2")}
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
_RE_MJPG = re.compile(r"^/(?P<ov>overlay/)?(?P<name>[A-Za-z0-9_]+)\.mjpg$")
_RE_SNAP = re.compile(r"^/snapshot/(?P<ov>overlay_)?(?P<name>[A-Za-z0-9_]+)\.jpg$")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # 静音
        pass

    def do_GET(self):
        p = self.path.split("?")[0]
        if p in ("/", "/index.html"):
            body = PAGE.replace("__IDX__", str(self.server.local_dev)).encode("utf-8")
            self._send(200, "text/html; charset=utf-8", body)
        elif p in ("/overlay", "/overlay.html", "/scene"):
            self._send(200, "text/html; charset=utf-8", OVERLAY_PAGE.encode("utf-8"))
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
        names = [n for n in ("arm", "local", "local2") if _FRAMES.get(n)]
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

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    srv.local_dev = args.local_dev
    print(f"   ✅ 看板: http://0.0.0.0:{args.port}/   (手机/PC 同网可开)", flush=True)
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
