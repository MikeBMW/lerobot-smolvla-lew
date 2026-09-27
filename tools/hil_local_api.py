#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hil_local_api.py — 🙋 HIL 人机在环 · **局域网本地 API** (手机 APP / 工位现场页用)

为什么要有它 (2026-09-27 老倪: 「veh.5.010 状态空间的 HIL 人机在环节点, 接入我的手机 APP,
从这个点我要通过 APP 跟状态空间交互, 人机在环」):
  原来的 HIL 链路是绕公网的: 桥每 N 秒 POST https://datadrive.world/api/relay/hil/state,
  网页 hil.html 读它、写回的指示再由桥取回。手机在现场连的是**局域网**, 再绕一圈公网没有意义;
  现场页(8791/room)需要本地就能读到状态、本地就能把人的指示交给**同一个大脑**。

**同一个大脑(关键)**: 本服务直接 import state_space/hil_bridge 的 build_snapshot / handle_instruction
  ⇒ 画布 n_hil 节点、datadrive 的 hil.html、手机 APP 三处看到的是**同一份状态**、**同一套指示处理**,
    红线也一并在同一个地方生效: 动作类指示一律拒答(只记为待授权), 真动只走 /ctl/* 那套两步授权+限时。

接口(只有 GET/POST, 只产出判读/建议/记录, 不产生任何机械臂动作):
  GET  /hil/state  → {"ok":1, "snapshot":{…}, "pause":bool, "instructions":[最近N条]}
  POST /hil/say    {"text":"…"} → {"ok":1, "reply":"…", "verdict":"…"}
  GET  /health     → {"ok":1, "hil":…}
"""
import importlib.util
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = "/home/ubuntu/zmax_rel"

# ⚠️ 必须按**文件路径**加载核心模块: 若直接 `import hil_bridge`, 从 tools/ 起进程时会先命中
#   tools/hil_bridge.py(只是 CLI 壳, 没有 build_snapshot/handle_instruction) ⇒ 运行时 AttributeError。
#   核心模块是纯 stdlib ⇒ 按路径加载最稳最快, 不用把 torch/lerobot 那条包 import 链拉起来。
_CORE = os.path.join(ROOT, "src/lerobot/policies/left_right/state_space/hil_bridge.py")
_spec = importlib.util.spec_from_file_location("zmax_hil_core", _CORE)
HB = importlib.util.module_from_spec(_spec)
sys.modules["zmax_hil_core"] = HB
_spec.loader.exec_module(HB)

PORT = int(os.environ.get("ZMAX_HIL_LOCAL_PORT", "8795"))
REPORTS = HB.REPORTS
INSTR_LOG = os.path.join(REPORTS, "hil_instructions.jsonl")
PAUSE_FLAG = os.path.join(REPORTS, "hil_pause.flag")
_LOCK = threading.Lock()
_LAST = {"ts": 0.0, "snap": None}


def _snapshot(force=False):
    """带 2s 缓存的快照 (手机上页面 2~3 秒刷一次, 不必每次重算)"""
    with _LOCK:
        if not force and _LAST["snap"] and (time.time() - _LAST["ts"]) < 2.0:
            return _LAST["snap"]
    try:
        snap = HB.build_snapshot()["snapshot"]
    except Exception as e:                                          # noqa: BLE001
        snap = {"error": "%s: %s" % (type(e).__name__, str(e)[:160])}
    with _LOCK:
        _LAST["snap"] = snap
        _LAST["ts"] = time.time()
    return snap


def _recent_instructions(n=20):
    out = []
    try:
        with open(INSTR_LOG, encoding="utf-8") as f:
            lines = f.readlines()[-n:]
        for ln in lines:
            try:
                out.append(json.loads(ln))
            except Exception:                                       # noqa: BLE001
                pass
    except Exception:                                               # noqa: BLE001
        pass
    return out


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "zmax-hil-local/1.0"

    def log_message(self, format, *args):  # noqa: A002                                  # 静音
        pass

    def _send(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):                                            # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):                                                # noqa: N802
        p = self.path.split("?")[0].rstrip("/") or "/"
        if p == "/health":
            return self._send({"ok": 1, "hil": "local", "port": PORT, "reports": REPORTS})
        if p in ("/", "/hil/state", "/hil"):
            s = _snapshot()
            return self._send({"ok": 1, "ts": time.strftime("%F %T"),
                               "pause": os.path.isfile(PAUSE_FLAG),
                               "instructions": _recent_instructions(),
                               "snapshot": s})
        return self._send({"ok": 0, "err": "no route %s" % p}, 404)

    def do_POST(self):                                               # noqa: N802
        p = self.path.split("?")[0].rstrip("/") or "/"
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n).decode() or "{}")
        except Exception:                                           # noqa: BLE001
            body = {}
        if p in ("/hil/say", "/say"):
            text = (body.get("text") or "").strip()
            if not text:
                return self._send({"ok": 0, "err": "空指示"}, 400)
            snap = _snapshot()
            try:
                reply, verdict = HB.handle_instruction(text, snap)
            except Exception as e:                                  # noqa: BLE001
                return self._send({"ok": 0, "err": "%s: %s" % (type(e).__name__, str(e)[:160])}, 500)
            return self._send({"ok": 1, "ts": time.strftime("%F %T"), "text": text,
                               "reply": reply, "verdict": verdict})
        return self._send({"ok": 0, "err": "no route %s" % p}, 404)


def main():
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), H)
    print("🙋 HIL 本地 API 在听 0.0.0.0:%d (同一个大脑: %s)" % (PORT, HB.__file__), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
