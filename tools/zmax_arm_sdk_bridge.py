#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""zmax_arm_sdk_bridge.py — 🦾 Orin 侧 SDK 直驱桥 (常驻 HTTP 服务, 不依赖 ROS2 栈)

老倪 (2026-09-26): 「桥放在 Orin 上, 直接驱动 SDK」+「不依赖当前机器人的 ROS2 服务, 每次重启还要启动
ROS2 程序不方便」+「同时兼容现有 ROS2 SRV 框架」。

架构:
  状态空间工程(4060) ──HTTP──> **本桥(Orin, 常驻)** ──xCoreSDK──> 控制器 192.168.23.160
  ROS2 SRV 老路(/move_pose 等)保持不动 → 两条路共存, 效率优先走本桥 (无 ROS 栈、无 DDS 发现开销)

接口 (stdlib http.server, python3.10):
  GET  /health                     → {"ok":true,"sdk":bool,"ctrl":"192.168.23.160"}
  GET  /status                     → 关节/速度/力矩/TCP(endInRef)/模式/电源 (只读)
  POST /reset                      → moveReset (SDK 接管前置; 技能坑 #1)
  POST /move_pose  {p,q,speed,dry} → dry 默认 true (只算不下发); dry=false 才真发 (moveAppend+moveStart)
  POST /stop                       → stopMove 兜底
安全: 默认 dry; 真下发前由 **4060 侧统一安全闸**(Δ守卫/限幅/现场闸门)判定; 本桥只做 SDK 收口。
资源: CPUQuota=20% · MemoryMax=300M · Nice=10 (不打搅产线)
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.environ.get(
    "ZMAX_SDK_PATH",
    "/home/tashan/0810/tashan_robot_so_20260807_174920_6983506_aarch64/install/robot_driver/"
    "lib/python3.10/site-packages/robot_driver/rokae"))

CTRL_IP = os.environ.get("ZMAX_CTRL_IP", "192.168.23.160")
PORT = int(os.environ.get("ZMAX_SDK_BRIDGE_PORT", "39061"))
STATE = {"robot": None, "ct": None, "err": None, "conn_ts": None, "calls": 0}
LOCK = threading.Lock()


def connect():
    import xcoresdk_python as x                                               # type: ignore
    r = x.xMateRobot()
    r.connectToRobot(CTRL_IP)
    STATE.update({"robot": r, "ct": x.CoordinateType, "conn_ts": time.time(), "err": None})
    return r


def _pose(obj):
    got = []
    for attr in ("trans", "position", "p"):
        v = getattr(obj, attr, None)
        if v is not None:
            try:
                got = [float(z) for z in v]
            except TypeError:
                got = [float(v)]
            break
    if not got:
        for a in ("x", "y", "z"):
            v = getattr(obj, a, None)
            if v is not None:
                got.append(float(v))
    q = getattr(obj, "rpy", None) or getattr(obj, "quat", None)
    if q is not None:
        got += [float(z) for z in q]
    return got or None


def status():
    r, ct = STATE["robot"], STATE["ct"]
    s = {"ctrl": CTRL_IP, "conn_ts": STATE["conn_ts"]}
    for k, fn in (("jointPos", lambda: list(r.jointPos({}))[:6]),
                  ("jointVel", lambda: list(r.jointVel({}))[:6]),
                  ("jointTorque", lambda: list(r.jointTorque({}))[:6])):
        try:
            s[k] = [round(float(v), 6) for v in fn()]
        except Exception as e:                                                   # noqa: BLE001
            s[k + "_err"] = str(e)[:80]
    for name in ("endInRef", "flangeInBase"):
        try:
            s[name] = _pose(r.cartPosture(getattr(ct, name), {}))
        except Exception as e:                                                   # noqa: BLE001
            s[name + "_err"] = str(e)[:80]
    for name in ("operateMode", "powerState"):
        try:
            s[name] = str(r.__getattribute__(name)({}))
        except Exception:                                                        # noqa: BLE001
            pass
    return s


def do_move(p, q, speed=30.0, dry=True):
    r, ct = STATE["robot"], STATE["ct"]
    cur = _pose(r.cartPosture(ct.endInRef, {})) or []
    plan = {"from": cur, "to": [p[0], p[1], p[2], q[0], q[1], q[2], q[3]], "speed": speed,
            "delta_mm": [round((p[i] - cur[i]) * 1000, 4) for i in range(3)] if len(cur) >= 3 else None}
    if dry:
        return {"dry": True, "plan": plan, "note": "仅计算; dry=false 才真下发"}
    r.moveAppend([p[0], p[1], p[2], q[0], q[1], q[2], q[3]], speed, True, ct.endInRef, {})
    r.moveStart()
    return {"dry": False, "sent": plan}


class H(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a):                                                   # 静音
        pass

    def do_GET(self):                                                            # noqa: N802
        if self.path.startswith("/health"):
            return self._send(200, {"ok": True, "sdk": STATE["robot"] is not None, "ctrl": CTRL_IP,
                                    "calls": STATE["calls"], "err": STATE["err"]})
        if self.path.startswith("/status"):
            if STATE["robot"] is None:
                try:
                    connect()
                except Exception as e:                                           # noqa: BLE001
                    return self._send(503, {"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:140])})
            STATE["calls"] += 1
            with LOCK:
                return self._send(200, {"ok": True, "status": status(), "ts": time.time()})
        return self._send(404, {"ok": False, "error": "未知路径 (GET /health | /status)"})

    def do_POST(self):                                                           # noqa: N802
        n = int(self.headers.get("Content-Length", 0) or 0)
        try:
            body = json.loads(self.rfile.read(n).decode() or "{}") if n else {}
        except Exception:                                                        # noqa: BLE001
            body = {}
        if STATE["robot"] is None:
            try:
                connect()
            except Exception as e:                                               # noqa: BLE001
                return self._send(503, {"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:140])})
        STATE["calls"] += 1
        try:
            with LOCK:
                if self.path.startswith("/reset"):
                    STATE["robot"].moveReset()
                    return self._send(200, {"ok": True, "note": "moveReset 完成"})
                if self.path.startswith("/stop"):
                    try:
                        STATE["robot"].stopMove()
                    except Exception:                                            # noqa: BLE001
                        STATE["robot"].moveReset()
                    return self._send(200, {"ok": True, "note": "stop 已发"})
                if self.path.startswith("/move_pose"):
                    p, q = body.get("p"), body.get("q")
                    if not (isinstance(p, list) and len(p) == 3 and isinstance(q, list) and len(q) == 4):
                        return self._send(400, {"ok": False, "error": "需要 p=[x,y,z], q=[x,y,z,w]"})
                    res = do_move(p, q, float(body.get("speed", 30.0)), bool(body.get("dry", True)))
                    return self._send(200, {"ok": True, "result": res})
        except Exception as e:                                                   # noqa: BLE001
            return self._send(500, {"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:180])})
        return self._send(404, {"ok": False, "error": "未知路径 (POST /reset | /stop | /move_pose)"})


def main() -> int:
    try:
        connect()
        print(json.dumps({"ready": True, "sdk": True, "ctrl": CTRL_IP, "port": PORT}), flush=True)
    except Exception as e:                                                       # noqa: BLE001
        STATE["err"] = "%s: %s" % (type(e).__name__, str(e)[:140])
        print(json.dumps({"ready": True, "sdk": False, "err": STATE["err"], "port": PORT}), flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
