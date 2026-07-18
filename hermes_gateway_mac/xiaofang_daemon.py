#!/usr/bin/env python3
"""小芳守护服务 — Mac端常驻, 中继Orin↔4090"""
import time, requests, json, os, subprocess, threading
from http.server import HTTPServer, BaseHTTPRequestHandler

ORIN = "http://192.168.23.10:8765"
LOG = "/tmp/xiaofang_daemon.log"
MAC_PORT = 8766


class MacHealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(b'{"online":true,"name":"MAC","service":"xiaofang_daemon","port":8766}')
    def log_message(self, *a): pass

def http_loop():
    s = HTTPServer(("0.0.0.0", MAC_PORT), MacHealthHandler)
    s.serve_forever()

def log(msg):
    with open(LOG, "a") as f:
        f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")

def orin_health():
    try:
        r = requests.get(f"{ORIN}/health", timeout=3)
        return r.json()
    except:
        return {"online": False}

def orin_record_status():
    try:
        r = requests.get(f"{ORIN}/record/status", timeout=3)
        return r.json()
    except:
        return {"recording": False}

def heartbeat_loop():
    """每30秒检查Orin状态, 记录心跳"""
    while True:
        h = orin_health()
        rs = orin_record_status()
        alive = h.get("online", False) or rs.get("recording", False)
        status = "🟢" if alive else "🔴"
        log(f"{status} Orin health={h.get('online')} record={rs.get('recording')}")
        time.sleep(30)

if __name__ == "__main__":
    log("=== 小芳守护服务启动 ===")
    threading.Thread(target=http_loop, daemon=True).start()
    threading.Thread(target=heartbeat_loop, daemon=True).start()

    # 常驻, 等待用户操作
    while True:
        try:
            h = orin_health()
            print(f"\r[{time.strftime('%H:%M:%S')}] Orin: {'🟢' if h.get('online') else '🔴'}  recording: {orin_record_status().get('recording')}", end="")
        except:
            print(f"\r[{time.strftime('%H:%M:%S')}] 🔴 Orin unreachable", end="")
        time.sleep(5)
