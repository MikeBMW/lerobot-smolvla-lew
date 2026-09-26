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

# ── 全局：两路相机的最新 JPEG 帧 ───────────────────────────────
_LOCK = threading.Lock()
_FRAMES = {
    "arm":   {"jpg": None, "ts": 0.0, "seq": 0, "src_ts": 0.0, "raw_kb": 0.0},
    "local": {"jpg": None, "ts": 0.0, "seq": 0, "src_ts": 0.0, "raw_kb": 0.0},
    "ov_arm":   {"jpg": None, "ts": 0.0, "seq": 0, "src_ts": 0.0, "raw_kb": 0.0},
    "ov_local": {"jpg": None, "ts": 0.0, "seq": 0, "src_ts": 0.0, "raw_kb": 0.0},
}
_OV_INFO = {}                        # 每路最近一次的叠加统计（画了多少框/跳过原因）
_STOP = threading.Event()


def _put(name: str, jpg: bytes, src_ts: float, raw_kb: float) -> None:
    with _LOCK:
        f = _FRAMES[name]
        f["jpg"] = jpg
        f["ts"] = time.time()
        f["seq"] += 1
        f["src_ts"] = src_ts or f["ts"]
        f["raw_kb"] = raw_kb


def _get(name: str):
    with _LOCK:
        f = _FRAMES[name]
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


# ── ② 笔记本内置相机：本机驱动直读 ────────────────────────────
def local_worker(dev_index: int, quality: int, width: int, height: int,
                 fps_cap: float) -> None:
    cap = cv2.VideoCapture(dev_index)
    if not cap.isOpened():
        print(f"[local] /dev/video{dev_index} 打不开", flush=True)
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
                print(f"[local] 读帧失败 x{fails}", flush=True)
            _STOP.wait(0.05)
            continue
        ok, buf = cv2.imencode(".jpg", frame, params)
        if ok:
            _put("local", buf.tobytes(), time.time(),
                 float(frame.nbytes) / 1024.0)
        dt = time.time() - t0
        if fps_cap > 0 and dt < 1.0 / fps_cap:
            _STOP.wait(1.0 / fps_cap - dt)
    cap.release()


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
        # TCP 缓存 2s（投影链需要实时位姿；频繁 ssh 读会拖慢）
        if time.time() - tcp_ts > 2.0:
            try:
                tcp = _SO.read_tcp(timeout=20)
            except Exception:
                tcp = None
            tcp_ts = time.time()
        try:
            spec = _SO.load_spec()
            he = _SO.load_handeye()
            extra = {
                "frame_age": "帧龄 %.1fs · 源 %s" % (max(0.0, time.time() - src_ts),
                                                    time.strftime("%H:%M:%S", time.localtime(src_ts))),
                "handeye": ("手眼 cam→tcp |t|=%.0fmm (%s/%s位姿)"
                            % (np.linalg.norm(he["X"][:3, 3]) * 1000, he.get("method"), he.get("n_poses")))
                           if he["ok"] else "手眼未标定 ⇒ 仿真框无法投影",
                "tcp": ("TCP=(%.4f, %.4f, %.4f) 实时真值" % tuple(tcp[:3])) if tcp is not None
                       else "TCP 未读到（仿真投影将跳过）",
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


def _gen_worker(kind: str) -> None:
    try:
        if kind == "sim":
            spec = _SO.build_from_sim()
            _SO.save_spec(spec)
            r = "仿真投影: %d 框 (源 %s)" % (len(spec["cameras"]["arm"]["boxes"]), spec["source"])
        elif kind == "scene":
            spec = _SO.build_from_scene_state()
            _SO.save_spec(spec)
            r = "场景契约: %d 框" % len(spec["cameras"]["arm"]["boxes"])
        else:
            r = __import__("gen_overlay_from_" + ("vlm" if kind == "vlm" else "det")).main_cli()
    except Exception as e:
        r = "✗ %s: %s" % (kind, str(e)[:180])
    with _LOCK:
        _GEN_STATE.update(busy=None, last=r, ts=time.time())
    print("[gen] %s → %s" % (kind, r), flush=True)


def _spawn_gen(kind: str) -> str:
    with _LOCK:
        if _GEN_STATE["busy"]:
            return "已有生成在跑: %s" % _GEN_STATE["busy"]
        _GEN_STATE.update(busy=kind, ts=time.time())
    threading.Thread(target=_gen_worker, args=(kind,), daemon=True).start()
    return "已启动: %s (%s)" % (_GEN_KINDS.get(kind, kind), kind)


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
  <div class="meta">手臂相机 = Orin 经 ROS 传来（JPEG 压缩推流） · 笔记本相机 = 本机驱动 · <span id="stat">—</span></div>
</header>
<div class="wrap">
  <div class="card">
    <h2>🦾 手臂相机 <span class="tag" id="t_arm">Orin → 4060</span></h2>
    <img src="/arm.mjpg" alt="arm">
    <div class="note">源: <code>/realsense/color/image_raw</code> (Orin) · 帧龄 <b id="age_arm">—</b></div>
  </div>
  <div class="card">
    <h2>💻 笔记本内置相机 <span class="tag" id="t_local">本机驱动</span></h2>
    <img src="/local.mjpg" alt="local">
    <div class="note">源: <code>/dev/video__IDX__</code> · 帧龄 <b id="age_local">—</b></div>
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
    const a=s.arm,l=s.local;
    document.getElementById('age_arm').textContent = a.age_s.toFixed(2)+'s ('+a.fps.toFixed(1)+'fps)';
    document.getElementById('age_local').textContent = l.age_s.toFixed(2)+'s ('+l.fps.toFixed(1)+'fps)';
    document.getElementById('stat').textContent =
      `手臂 ${a.kb_per_frame.toFixed(0)}KB/帧 ${a.compress_x.toFixed(0)}x压`+
      `  |  笔记本 ${l.kb_per_frame.toFixed(0)}KB/帧 ${l.compress_x.toFixed(0)}x压`;
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
# 场景叠加页（老倪：把仿真场景的检测框嵌进真实视频流 + 按钮切换来源）
# ══════════════════════════════════════════════════════════════
OVERLAY_PAGE = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Z-MAX 场景叠加 · 真实视频流 + 仿真边界框</title>
<style>
 body{margin:0;background:#0b0f14;color:#e6edf3;font:16px/1.55 -apple-system,Segoe UI,Roboto,sans-serif}
 header{padding:12px 16px;background:#111820;border-bottom:1px solid #223}
 h1{margin:0;font-size:20px;font-weight:600}
 .meta{color:#8b98a5;font-size:14px;margin-top:4px}
 .bar{display:flex;flex-wrap:wrap;gap:8px;padding:12px 16px;background:#0e151c;border-bottom:1px solid #223;
      position:sticky;top:0;z-index:9}
 button{font:15px/1 inherit;padding:11px 16px;border-radius:9px;border:1px solid #2d3a47;
        background:#16202b;color:#e6edf3;cursor:pointer}
 button:hover{background:#1d2a37}
 button.on{background:#1f6feb;border-color:#1f6feb;color:#fff}
 button.go{background:#238636;border-color:#238636;color:#fff;font-weight:600}
 .wrap{display:grid;grid-template-columns:1fr;gap:12px;padding:12px}
 @media(min-width:1000px){.wrap{grid-template-columns:1fr 1fr}}
 .card{background:#111820;border:1px solid #223;border-radius:10px;overflow:hidden}
 .card h2{margin:0;padding:10px 14px;font-size:15px;font-weight:600;background:#0e151c;
          border-bottom:1px solid #223;display:flex;justify-content:space-between}
 .tag{font-weight:400;color:#8b98a5;font-size:13px}
 img{display:block;width:100%;height:auto;background:#000}
 .panel{margin:0 12px 12px;padding:14px 16px;background:#111820;border:1px solid #223;border-radius:10px;
        font-size:15px}
 .panel b{color:#7ee787}
 .row{display:flex;gap:18px;flex-wrap:wrap;margin-top:6px}
 .k{color:#8b98a5;font-size:13px}
 code{color:#7ee787;font-size:13px}
 .lg{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:5px;vertical-align:-1px}
 .msg{padding:10px 16px;color:#d29922;font-size:14px}
</style></head><body>
<header>
  <h1>🧩 场景叠加 · 真实视频流 + 仿真场景边界框</h1>
  <div class="meta">真实画面 = 原始视频流 · 框 = 仿真投影 / L5 大模型理解 / 真机检测（颜色区分，不混为一谈）</div>
</header>
<div class="bar">
  <button id="c_arm" class="on" onclick="setCam('arm')">🦾 手臂相机</button>
  <button id="c_local" onclick="setCam('local')">💻 笔记本相机</button>
  <span style="width:1px;background:#223;margin:0 4px"></span>
  <button class="go" onclick="gen('sim')">🎯 仿真场景投影</button>
  <button class="go" onclick="gen('vlm')">🧠 L5 大模型理解</button>
  <button class="go" onclick="gen('scene')">📋 场景契约框</button>
  <button onclick="gen('det')">🔍 真机检测</button>
  <button onclick="load()">↻ 刷新</button>
</div>
<div id="msg" class="msg"></div>
<div class="wrap">
  <div class="card">
    <h2>📷 原始真实画面 <span class="tag" id="raw_tag">—</span></h2>
    <img id="raw" src="/arm.mjpg" alt="raw">
  </div>
  <div class="card">
    <h2>🧩 叠加后 <span class="tag" id="ov_tag">—</span></h2>
    <img id="ov" src="/overlay/arm.mjpg" alt="overlay">
  </div>
</div>
<div class="panel">
  <div>规格: <b id="mode">—</b> · 源 <span class="k" id="src"></span> · 更新 <span class="k" id="age"></span></div>
  <div class="row">
    <span><span class="lg" style="background:#22c55e"></span>仿真 <b id="n_sim">0</b></span>
    <span><span class="lg" style="background:#00b0ff"></span>大模型 <b id="n_vlm">0</b></span>
    <span><span class="lg" style="background:#eb3c3c"></span>检测 <b id="n_det">0</b></span>
    <span><span class="lg" style="background:#888"></span>跳过 <b id="n_skip">0</b></span>
  </div>
  <div class="row"><span class="k">手眼</span><span id="he">—</span></div>
  <div class="row"><span class="k">TCP</span><span id="tcp">—</span></div>
  <div class="row"><span class="k">跳过原因</span><span id="skip">—</span></div>
  <div class="row"><span class="k">生成任务</span><span id="gen">—</span></div>
</div>
<script>
let CAM='arm';
function setCam(c){
  CAM=c;
  document.getElementById('c_arm').className = c==='arm'?'on':'';
  document.getElementById('c_local').className = c==='local'?'on':'';
  document.getElementById('raw').src='/'+c+'.mjpg';
  document.getElementById('ov').src='/overlay/'+c+'.mjpg';
}
async function gen(kind){
  const r=await fetch('/gen?kind='+kind); const j=await r.json();
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
    document.getElementById('raw_tag').textContent='帧 '+new Date().toLocaleTimeString();
    document.getElementById('ov_tag').textContent='画框 '+(inf.drawn||0)+' 个';
    if(g.last) document.getElementById('msg').textContent='✓ '+g.last;
  }catch(e){}
}
setInterval(load,1500);load();
</script></body></html>"""


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
        elif p == "/scene.json":
            spec = _SO.load_spec() if _SO else {"error": "scene_overlay 未加载"}
            with _LOCK:
                spec = dict(spec)
                spec["_overlay_info"] = dict(_OV_INFO)
                spec["_gen"] = dict(_GEN_STATE)
            self._send(200, "application/json; charset=utf-8",
                       json.dumps(spec, ensure_ascii=False).encode("utf-8"))
        elif p == "/gen":
            kind = ""
            if "?" in self.path:
                for kv in self.path.split("?", 1)[1].split("&"):
                    if kv.startswith("kind="):
                        kind = kv.split("=", 1)[1]
            if _SO is None:
                msg = "scene_overlay 未加载，叠加能力不可用"
            else:
                msg = _spawn_gen(kind) if kind in _GEN_KINDS else "未知 kind=%s" % kind
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
        names = ["arm", "local"] + [n for n in ("ov_arm", "ov_local")
                                    if _FRAMES.get(n, {}).get("jpg") is not None]
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
            }
        return out


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
    ap.add_argument("--local-dev", type=int, default=0, help="笔记本相机 /dev/videoN")
    ap.add_argument("--no-local", action="store_true", help="不启笔记本相机")
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--overlay", action="store_true", default=False,
                    help="开启场景叠加（真实流 + 仿真/大模型/检测框；页面 /overlay）")
    ap.add_argument("--overlay-src", default="arm",
                    choices=["arm", "local", "both"], help="叠加哪几路")
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
    if not args.no_local:
        print(f"   笔记本: /dev/video{args.local_dev}", flush=True)
        threading.Thread(target=local_worker,
                         args=(args.local_dev, args.quality, args.width,
                               args.height, args.fps),
                         daemon=True, name="local").start()

    # ── 场景叠加（老倪 2026-09-27）──
    if args.overlay:
        if _SO is None:
            print("   ⚠ 场景叠加: scene_overlay 未加载 ⇒ 叠加不可用（纯推流不受影响）", flush=True)
        else:
            he = _SO.load_handeye()
            srcs = ["arm", "local"] if args.overlay_src == "both" else [args.overlay_src]
            for s in srcs:
                threading.Thread(target=overlay_worker, args=(s, args.overlay_fps),
                                 daemon=True, name="ov-" + s).start()
            print(f"   🧩 场景叠加: 已开 [{'+'.join(srcs)}] ≤{args.overlay_fps}fps · "
                  f"手眼 {'✓ |t|=%.0fmm' % (np.linalg.norm(he['X'][:3, 3]) * 1000) if he['ok'] else '✗未标定'}"
                  f" · 规格 {_SO.SPEC_PATH}", flush=True)
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
