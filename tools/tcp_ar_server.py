#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tcp_ar_server.py — TCP 轨迹 AR/VR 可视化服务 (独立端口, 不碰在跑的推流服务)
════════════════════════════════════════════════════════════════════════════
老倪 2026-09-29: 「把可视化的管道轨迹渲染叠加到笔记本相机这个场景中(侧面固定视角)」
              +「应用 VR AR 技术把工具中心轨迹可视化出来」

职责划分(为什么不塞进 cam_live_stream.py):
  · 推流服务(8791/8793)老倪正看着 ⇒ 改它必须重启, 会打断在看的画面;
    本服务**独立端口**起, 页面另占一套 6 条连接名额, 与总览页互不饿死。

端点:
  /                   AR 页 (tools/web/tcp-ar.html, 按 mtime 热读 ⇒ 改页面不用重启)
  /local.mjpg         笔记本相机实时流 (代理 8791, 作为 AR 底图)
  /snapshot/local.jpg 单帧 (代理)
  /scene.json         叠加规格 (代理; 页面从这里取 trace/plan 的 3D 点)
  /stats              相机状态 (代理)
  /api/tcp            当前 TCP 真值(base 系, 珞石 SDK 直采) + 帧龄
  /api/traj           轨迹 3D 点: {"trace":[...], "plan":[...]} (从叠加规格里取)
  /api/stable         臂是否停稳(采 1.2s TCP, 报最大漂移 mm) —— 标定点必须停稳才准
  /api/calib GET      当前笔记本相机外参
  /api/calib POST     {"points":[{"uv":[u,v],"tcp":[x,y,z]}...]} → 解 f/R/t, 存盘, 回重投影证据
  /api/verify         独立验收: 把 TCP 投到"运动中机械臂"掩膜, 回命中率
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import laptop_cam_solve as LS                                                    # noqa: E402
import traj_display as TD                                                        # noqa: E402

UP = "http://127.0.0.1:8791"
PORT = int(os.environ.get("AR_PORT", "8797"))
PAGE = os.path.join(REPO, "tools", "web", "tcp-ar.html")
CALIB = os.path.join(REPO, "data", "scene", "laptop_cam_calib.json")            # 旧单相机文件(兼容保留)
MCALIB = os.path.join(REPO, "data", "scene", "cam_calib.json")                   # 多相机: {"local":{...},"local2":{...}}
# 每台固定相机的原生分辨率(标定点按像素存, 必须和分辨率绑定; 混用 = 投影全错)
CAMS = {"local": {"w": 640, "h": 480, "label": "笔记本相机 640×480", "mjpg": "/local.mjpg"},
        "local2": {"w": 1280, "h": 720, "label": "MAXHUB 相机 1280×720", "mjpg": "/local2.mjpg"}}
TCP_JSON = os.path.expanduser("~/zmax_data/rokae_sdk/tcp_out/latest.json")
IMG_W, IMG_H = 640, 480


def _get(path: str, timeout: float = 10.0):
    with urllib.request.urlopen(UP + path, timeout=timeout) as r:
        return r.read()


def read_tcp():
    try:
        with open(TCP_JSON) as f:
            d = json.load(f)
        return {"ok": True, "x": d["x"], "y": d["y"], "z": d["z"],
                "t": d.get("t"), "age_s": round(time.time() - float(d["ts"]), 3)}
    except Exception as e:                                                        # noqa: BLE001
        return {"ok": False, "err": str(e)[:120]}


def snap_cam(cam: str = "local"):
    b = _get("/snapshot/%s.jpg" % cam)
    return cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR)


def motion_mask(gap: float = 0.8, thr: int = 18, cam: str = "local"):
    """运动掩膜(哪台相机就量哪台): 两帧差 + 膨胀。用来做"TCP 投影是否落在运动中的臂上"的独立验收。"""
    f1 = snap_cam(cam)
    time.sleep(gap)
    f2 = snap_cam(cam)
    if f1 is None or f2 is None or f1.shape != f2.shape:
        return np.zeros((CAMS.get(cam, {}).get("h", 480), CAMS.get(cam, {}).get("w", 640)), np.uint8)
    d = np.abs(f2.astype(np.int16) - f1.astype(np.int16)).max(2)
    return cv2.dilate((d > thr).astype(np.uint8), np.ones((9, 9), np.uint8))


def load_calib(cam="local"):
    """读某台固定相机的外参: 先查多相机文件 cam_calib.json[cam], 没命中再回落到旧的单相机文件。"""
    try:
        with open(MCALIB) as f:
            d = json.load(f)
        if isinstance(d, dict):
            if cam in d and isinstance(d[cam], dict):
                return d[cam]
            if d.get("cam") == cam:                    # 旧格式(单条)
                return d
    except Exception:                                                             # noqa: BLE001
        pass
    if cam == "local":
        try:
            with open(CALIB) as f:
                return json.load(f)
        except Exception:                                                         # noqa: BLE001
            return None
    return None


def save_calib(cam, obj):
    d = {}
    try:
        with open(MCALIB) as f:
            d = json.load(f)
        if not isinstance(d, dict) or "cam" in d:      # 旧格式/坏文件 ⇒ 重开
            d = {}
    except Exception:                                                             # noqa: BLE001
        d = {}
    d[cam] = obj
    tmp = MCALIB + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, MCALIB)
    return MCALIB


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "zmax-tcp-ar/1.0"

    def log_message(self, fmt, *a):                                               # noqa: A003
        sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), fmt % a))

    def _send(self, code, ctype, body: bytes, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        # 🌐 CORS: 8791 上的场景叠加页/工位总览页要能直接调这里的轨迹开关
        #    (跨端口 = 跨源, 不放开的话浏览器把请求直接拦掉, 表现为"按钮点了没反应")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_OPTIONS(self):                                                         # noqa: N802
        self._send(204, "text/plain", b"")

    def _json(self, obj, code=200):
        self._send(code, "application/json; charset=utf-8",
                   json.dumps(obj, ensure_ascii=False).encode())

    def do_GET(self):                                                             # noqa: N802
        p = self.path.split("?")[0]
        qs = {}
        if "?" in self.path:
            for kv in self.path.split("?", 1)[1].split("&"):
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    qs[k] = v
        cam = qs.get("cam") or qs.get("c") or "local"
        try:
            if p in ("/", "/tcp-ar", "/tcp-ar.html", "/ar"):
                with open(PAGE, "rb") as f:                                       # 热读: 改页面不用重启
                    self._send(200, "text/html; charset=utf-8", f.read())
            elif p == "/api/cams":
                self._json({"ok": True, "cams": CAMS, "calibrated": [c for c in CAMS if load_calib(c)]})
            elif p == "/api/tcp":
                self._json(read_tcp())
            elif p == "/api/traj":
                self._json(self._traj())
            elif p == "/api/stable":
                self._json(self._stable())
            elif p == "/api/calib":
                c = load_calib(cam)
                self._json({"ok": bool(c), "calib": c, "cam": cam, "cams": CAMS})
            elif p == "/api/traj/state":
                self._json(self._traj_state())
            elif p == "/api/verify":
                self._json(self._verify(cam))
            elif p in ("/scene.json", "/stats", "/station/status"):
                self._send(200, "application/json; charset=utf-8", _get(p))
            elif p == "/cam.mjpg":
                self._proxy_stream((CAMS.get(cam) or CAMS["local"])["mjpg"])
            elif p in ("/local.mjpg", "/local2.mjpg"):
                self._proxy_stream(p)
            elif p.startswith("/snapshot/") and p.endswith(".jpg"):
                self._send(200, "image/jpeg", _get(p))
            else:
                self._send(404, "text/plain", b"not found")
        except Exception as e:                                                    # noqa: BLE001
            self._json({"ok": False, "err": "%s: %s" % (type(e).__name__, e)}, 500)

    def _proxy_stream(self, p):
        """MJPEG 透传: 不断开、边读边写(不要 copyfile — 它是无限的)。"""
        try:
            req = urllib.request.Request(UP + p)
            with urllib.request.urlopen(req, timeout=20) as r:
                self.send_response(200)
                self.send_header("Content-Type", r.headers.get("Content-Type", "multipart/x-mixed-replace"))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                while True:
                    chunk = r.read(8192)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:                                                    # noqa: BLE001
            self.log_message("stream err %s", e)

    # ── 数据 ────────────────────────────────────────────────
    def _traj(self):
        d = json.loads(_get("/scene.json"))
        arm = ((d.get("cameras") or {}).get("arm") or {})
        out = {"trace": [], "plan": [], "trace_label": "", "plan_label": ""}
        for b in arm.get("boxes") or []:
            if b.get("kind") != "path3d":
                continue
            o = str(b.get("origin"))
            if o in out and b.get("pts3d"):
                out[o] = b["pts3d"]
                out[o + "_label"] = str(b.get("label") or "")
        out["ok"] = True
        out["at"] = time.strftime("%H:%M:%S")
        return out

    def _traj_state(self):
        st = TD.get_state()
        rec = 0
        try:
            rec = int(json.load(open(os.path.join(REPO, "reports", "moveit", "live_trace.json"))).get("n") or 0)
        except Exception:                                                          # noqa: BLE001
            pass
        return {"ok": True, "state": st, "in_spec": TD.paths_in_spec(),
                "recorded_pts": rec, "plan_cached": TD.paths_cached(),
                "hint": "show=false 是默认(人工开启); clear 只影响显示, 录制历史保留"}

    def _stable(self, seconds: float = 1.2):
        pts = []
        t0 = time.time()
        while time.time() - t0 < seconds:
            d = read_tcp()
            if d.get("ok"):
                pts.append((d["x"], d["y"], d["z"]))
            time.sleep(0.1)
        if len(pts) < 3:
            return {"ok": False, "err": "读不到 TCP"}
        a = np.array(pts)
        drift = float(np.linalg.norm(a - a.mean(0), axis=1).max() * 1000.0)
        return {"ok": True, "drift_mm": round(drift, 2), "stable": drift < 3.0, "n": len(pts)}

    def _verify(self, cam="local"):
        c = load_calib(cam)
        if not c:
            return {"ok": False, "err": "还没有标定(%s)" % cam}
        m = motion_mask(cam=cam)
        n_mv = int(m.sum())
        tcp = read_tcp()
        if not tcp.get("ok"):
            return {"ok": False, "err": "读不到 TCP"}
        if n_mv == 0:
            return {"ok": False, "err": "画面没有运动像素 —— 请**移动一下机械臂**再验证",
                    "moving_px": 0}
        hits, total, detail = LS.tcp_motion_hits(c, [{"mask": m, "tcp": [tcp["x"], tcp["y"], tcp["z"]]}])
        return {"ok": True, "hits": hits, "total": total, "moving_px": n_mv, "detail": detail,
                "note": "hits=1 ⇒ 当前 TCP 投影落在正在运动的机械臂上(AR 对准)"}

    # ── 标定 ────────────────────────────────────────────────
    def do_POST(self):                                                            # noqa: N802
        p = self.path.split("?")[0]
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n).decode("utf-8", "ignore") or "{}")
        except Exception:                                                         # noqa: BLE001
            body = {}
        if p == "/api/calib":
            self._json(self._do_calib(body))
        elif p == "/api/traj/show":
            show = bool(body.get("show"))
            r = TD.apply(show)
            pub = self._publish_once(show)
            self._json({"ok": True, "show": show, "detail": r, "publish": pub,
                        "in_spec": TD.paths_in_spec(),
                        "msg": ("✅ 已显示轨迹(实测轨迹 + 规划航路)" if show
                                else "⏸ 已隐藏轨迹(画面上的轨迹线撤掉, 录制历史保留)")})
        elif p == "/api/traj/clear":
            rec = 0
            try:
                rec = int(json.load(open(os.path.join(REPO, "reports", "moveit",
                                                      "live_trace.json"))).get("n") or 0)
            except Exception:                                                      # noqa: BLE001
                pass
            TD.set_state(baseline_n=rec)
            pub = self._publish_once(True) if TD.get_state()["show"] else None
            self._json({"ok": True, "baseline_n": rec, "publish": pub,
                        "msg": "🧹 已清除画面上走过的轨迹(清除线=%d); 之后新走的会重新画. 录制历史未动" % rec})
        elif p == "/api/traj/baseline":                 # 直接设"清除线": 0 = 画全部历史
            n = body.get("n")
            n = 0 if n is None else max(0, int(n))
            TD.set_state(baseline_n=n)
            pub = self._publish_once(True) if TD.get_state()["show"] else None
            self._json({"ok": True, "baseline_n": n, "publish": pub,
                        "msg": ("📜 清除线已归 0 ⇒ 画**全部已走过**的轨迹" if n == 0
                                else "清除线=%d" % n)})
        else:
            self._json({"ok": False, "err": "no route %s" % p}, 404)

    def _publish_once(self, show: bool):
        """让发布器立刻跑一轮 ⇒ 按钮点了就见效(不然最多等 2s 的壳周期)。"""
        try:
            import subprocess
            env = dict(os.environ)
            py = os.path.join(REPO, "gui-venv311", "bin", "python")
            r = subprocess.run([py, os.path.join(HERE, "live_trace_publisher.py"), "--once"],
                               capture_output=True, text=True, timeout=90, env=env)
            return (r.stdout or r.stderr or "").strip().splitlines()[-1:] or [""]
        except Exception as e:                                                    # noqa: BLE001
            return ["发布器单跑失败: %s" % str(e)[:120]]

    def _do_calib(self, body):
        cam = str(body.get("cam") or "local")
        meta = CAMS.get(cam) or CAMS["local"]
        W, H = int(meta["w"]), int(meta["h"])
        pts = body.get("points") or []
        if len(pts) < 6:
            return {"ok": False, "err": "至少 6 个点(建议 6~8, 且**高低/左右都要变**): 少于 6 个时 "
                                        "没有线性初值(DLT), 容易解飞 —— 现在 %d 个" % len(pts)}
        P3 = [q["tcp"] if isinstance(q.get("tcp"), list) else [q["tcp"]["x"], q["tcp"]["y"], q["tcp"]["z"]]
              for q in pts]
        P2 = [q["uv"] for q in pts]
        # 几何质量自检: 3D 点别挤成一条线/一个面
        A = np.array(P3, float)
        s = A.std(0) * 1000.0                                                     # mm
        spread_mm = float(np.linalg.norm(s))
        rng_mm = [float(v) for v in (A.max(0) - A.min(0)) * 1000.0]
        sol = LS.solve(P3, P2, W, H)
        if sol is None:
            return {"ok": False, "err": "解算失败(超定/退化) —— 点多散布一些再试"}
        calib = {
            "kind": "laptop_cam_calib", "cam": cam,
            "model": "pinhole, fx=fy=f, 主点=图像中心",
            "f": sol["f"], "cx": sol["cx"], "cy": sol["cy"], "image_size": sol["image_size"],
            "R_base_to_cam": sol["R"], "t_base_to_cam": sol["t"],
            "rms_px": round(sol["rms_px"], 2), "err_px": [round(e, 2) for e in sol["err_px"]],
            "n_points": len(P3), "spread_sigma_mm": round(spread_mm, 1), "range_mm": rng_mm,
            "solver_selftest": bool(LS.selftest(verbose=False)),
            "dlt_used": bool(sol.get("dlt_used")),
            "points": [{"uv": [float(u) for u in uvv], "tcp": [float(v) for v in p3]}
                       for uvv, p3 in zip(P2, P3)],
            "method": "页面人工标定: 停稳后点画面里的夹爪尖, 同刻记录 TCP 真值 → 解 f/rvec/t",
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        warn = []
        if sol["rms_px"] > 8.0:
            warn.append("重投影 RMS %.1fpx 偏大(>8): 八成有点点位不准或臂没停稳" % sol["rms_px"])
        if spread_mm < 40:
            warn.append("点位太集中(σ=%.0fmm): 请把机械臂停到**不同高度/左右前后**再采点" % spread_mm)
        if cam not in CAMS:
            warn.append("相机名 %r 不认识(只认 %s), 按默认分辨率存了" % (cam, list(CAMS)))
        saved = save_calib(cam, calib)
        return {"ok": True, "calib": calib, "warn": warn, "cam": cam,
                "saved": os.path.relpath(saved, REPO),
                "next": "移动机械臂后点『验证对准』, 看 TCP 投影是否落在正在运动的手臂上"}


def main():
    if not os.path.exists(PAGE):
        print("✗ 页面不存在: %s" % PAGE); return 1
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), H)
    srv.daemon_threads = True
    print("═══ TCP 轨迹 AR/VR 服务 ═══")
    print("  AR 页:      http://0.0.0.0:%d/          (手机/PC 同网可开)" % PORT)
    for k, v in CAMS.items():
        print("  底图 %-7s %s  → 代理 %s%s" % (k, v["label"], UP, v["mjpg"]))
    print("  轨迹来源:   %s/scene.json 的 cameras.arm 里 origin=trace/plan (kind=path3d)" % UP)
    print("  标定文件:   %s" % os.path.relpath(MCALIB, REPO))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n退出")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
