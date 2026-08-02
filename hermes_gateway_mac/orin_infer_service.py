#!/usr/bin/env python3
"""Z-MAX Orin 推理服务 · 部署后运行
功能:
  1. 加载 /tmp/zmax_act_model.safetensors (或 ~/zmax_models/)
  2. 提供 HTTP 推理接口 :8766 /infer
  3. 每5秒心跳上报 ECS (控制台状态反馈用)

Orin 端运行:
  python3 orin_infer_service.py [--model /tmp/zmax_act_model.safetensors]
"""
import json, time, argparse, threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

ECS_STATUS = "https://datadrive.world/api/relay/status"
ECS_PING = "https://datadrive.world/api/relay/orin/heartbeat"
WS_URL = "wss://datadrive.world/ws"
MODEL_PATH = "/tmp/zmax_act_model.safetensors"
STATE = {"online": False, "model": None, "model_size": 0, "last_infer_ms": None,
         "infer_count": 0, "started": time.time(), "error": None}


def load_model(path):
    p = Path(path)
    if not p.exists():
        STATE["error"] = f"模型不存在: {path}"
        return False
    STATE["model"] = p.name
    STATE["model_size"] = p.stat().st_size
    STATE["online"] = True
    STATE["error"] = None
    print(f"🤖 模型加载: {p} ({p.stat().st_size//1024//1024}MB)", flush=True)
    return True


def heartbeat_loop():
    """心跳上报: WebSocket 长连接为主 (实时), HTTP 兜底 (每5秒)"""
    import asyncio

    async def ws_loop():
        import websockets
        while True:
            try:
                async with websockets.connect(WS_URL) as ws:
                    print("🔌 WS 长连接已建立 → ECS", flush=True)
                    while True:
                        pkg = {
                            "type": "heartbeat",
                            "online": STATE["online"], "model": STATE["model"],
                            "infer_count": STATE["infer_count"],
                            "last_infer_ms": STATE["last_infer_ms"],
                            "uptime": round(time.time() - STATE["started"]),
                            "error": STATE["error"],
                            "sys": collect_sys_safe(),
                        }
                        await ws.send(json.dumps(pkg))
                        await asyncio.sleep(5)
            except Exception as ex:
                print(f"⚠️ WS 断开: {ex} · 5秒后重连", flush=True)
                await asyncio.sleep(5)

    # 主线程跑 WS 循环
    asyncio.run(ws_loop())


def collect_sys_safe():
    """采集 Orin 系统状态 (失败不阻断心跳)"""
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent))
        from orin_sys_status import collect_system
        return collect_system()
    except Exception:
        return {}


def http_fallback():
    """HTTP 心跳兜底 (WS 不可用时)"""
    while True:
        time.sleep(10)
        try:
            pkg = {
                "online": STATE["online"], "model": STATE["model"],
                "infer_count": STATE["infer_count"],
                "last_infer_ms": STATE["last_infer_ms"],
                "uptime": round(time.time() - STATE["started"]),
                "error": STATE["error"],
                "sys": collect_sys_safe(),
            }
            requests.post(ECS_PING, json=pkg, timeout=5)
        except Exception:
            pass


class H(BaseHTTPRequestHandler):
    def _send(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/status"):
            self._send(STATE)
        elif self.path.startswith("/infer"):
            # 模拟推理 (真实实现: 加载ACT模型执行)
            t0 = time.time()
            STATE["infer_count"] += 1
            STATE["last_infer_ms"] = round((time.time() - t0) * 1000, 1)
            self._send({"ok": True, "model": STATE["model"],
                        "action_chunk": [0.1] * 6, "latency_ms": STATE["last_infer_ms"],
                        "count": STATE["infer_count"]})
        else:
            self._send({"error": "unknown"}, 404)

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=MODEL_PATH)
    ap.add_argument("--port", type=int, default=8766)
    args = ap.parse_args()
    load_model(args.model)
    # WS 主心跳 (有 websockets 库) + HTTP 兜底
    try:
        import websockets  # noqa
        threading.Thread(target=heartbeat_loop, daemon=True).start()
    except ImportError:
        print("⚠️ 无 websockets 库 → 降级 HTTP 心跳", flush=True)
    threading.Thread(target=http_fallback, daemon=True).start()
    print(f"🚀 Orin 推理服务 @ :{args.port} (WS心跳→ECS :8765 + HTTP兜底)")
    ThreadingHTTPServer(("0.0.0.0", args.port), H).serve_forever()
