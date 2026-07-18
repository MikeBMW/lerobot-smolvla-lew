#!/usr/bin/env python3
"""小芳守护服务 — HTTP心跳连接4090"""
import json, time, requests, threading
from http.server import HTTPServer, BaseHTTPRequestHandler

ORIN = "http://192.168.23.10:8765"
HB_URL = "http://datadrive.world/api/comfy/api/mac/heartbeat"
MAC_PORT = 8766


class MacHealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        # 转发录制请求到 Orin
        if "/record/start" in self.path:
            try:
                dur = 30
                if "duration" in self.path:
                    dur = int(self.path.split("duration=")[1].split("&")[0])
                r = requests.post(f"{ORIN}/record/start?duration={dur}", timeout=50)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(r.content)
                return
            except Exception as e:
                self.send_response(502)
                self.end_headers()
                self.wfile.write(str(e).encode())
                return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(b'{"online":true,"name":"MAC","service":"xiaofang"}')
    def log_message(self, *a): pass


def orin_status():
    try:
        h = requests.get(f"{ORIN}/health", timeout=3).json()
        r = requests.get(f"{ORIN}/record/status", timeout=3).json()
        return {"online": True, "health": h, "recording": r.get("recording", False)}
    except:
        return {"online": False}


def heartbeat_loop():
    while True:
        try:
            payload = {"mac_online": True, "orin": orin_status(), "ts": time.time()}
            requests.post(HB_URL, json=payload, timeout=8)
        except:
            pass
        time.sleep(5)


def http_loop():
    HTTPServer(("0.0.0.0", MAC_PORT), MacHealthHandler).serve_forever()


if __name__ == "__main__":
    threading.Thread(target=http_loop, daemon=True).start()
    heartbeat_loop()
