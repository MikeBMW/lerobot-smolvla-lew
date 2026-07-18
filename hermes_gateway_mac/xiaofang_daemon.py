#!/usr/bin/env python3
"""小芳常驻守护 — 转发+心跳+自动上传"""
import json, time, requests, threading, os, re, glob, subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler

ORIN = "http://192.168.23.10:8765"
HB_URL = "http://datadrive.world/api/comfy/api/mac/heartbeat"
UPLOAD_URL = "http://datadrive.world/api/comfy/api/mac/upload"
MAC_HEALTH_PORT = 8766
FORWARD_PORT = 8769
LAST_RECORD_DIR = None  # 已上传的录制目录


# ─── 转发器(8769): Orin 代理 ───
class ForwardHandler(BaseHTTPRequestHandler):
    def _reply(self, data, code=200):
        self.send_response(code)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        if isinstance(data, str): data = data.encode()
        self.wfile.write(data)

    def do_GET(self):
        if "status" in self.path:
            self._reply(requests.get(ORIN + "/record/status", timeout=5).content)
        elif "record" in self.path:
            m = re.search(r"duration=(\d+)", self.path)
            d = int(m.group(1)) if m else 30
            self._reply(requests.post(ORIN + f"/record/start?duration={d}", timeout=50).content)
        else:
            h = requests.get(ORIN + "/health", timeout=3).json()
            rs = requests.get(ORIN + "/record/status", timeout=3).json()
            online = h.get("online", False) or rs.get("recording", False)
            self._reply(f'{{"online":{str(online).lower()}}}')

    def do_POST(self):
        if "record" in self.path:
            m = re.search(r"duration=(\d+)", self.path)
            d = int(m.group(1)) if m else 30
            self._reply(requests.post(ORIN + f"/record/start?duration={d}", timeout=50).content)
        else:
            self._reply(requests.get(ORIN + "/health", timeout=3).content)


# ─── 健康端(8766): 本地状态 ───
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(b'{"online":true,"name":"MAC","forwarder_port":8769}')
    def log_message(self, *a): pass


# ─── 心跳+自动上传 ───
def check_and_forward():
    """检测Orin上新录制文件, 自动上传到4090"""
    global LAST_RECORD_DIR
    try:
        rs = requests.get(ORIN + "/record/status", timeout=5).json()
        if rs.get("recording", False):
            return  # 正在录制, 等待完成

        # 找出Orin上最新的录制目录
        out = subprocess.run(
            ["ssh", "tashan@192.168.23.10", "ls -dt /tmp/zmax_* 2>/dev/null | head -1"],
            capture_output=True, text=True, timeout=10
        )
        latest = out.stdout.strip()
        if not latest or latest == LAST_RECORD_DIR:
            return  # 无新数据
        LAST_RECORD_DIR = latest

        # 有新的录制文件! 压缩并上传
        print(f"[AUTO] 发现新录制: {latest}")
        out2 = subprocess.run(
            ["ssh", "tashan@192.168.23.10", f"tar czf /tmp/upload_latest.tar.gz -C $(dirname {latest}) $(basename {latest}) && wc -c < /tmp/upload_latest.tar.gz"],
            capture_output=True, text=True, timeout=60
        )
        size = out2.stdout.strip()
        print(f"[AUTO] 压缩完成: {size} bytes")

        # SCP到本地, 再POST到4090
        subprocess.run(
            ["scp", "tashan@192.168.23.10:/tmp/upload_latest.tar.gz", "/tmp/mac_forward.tar.gz"],
            timeout=120
        )
        print(f"[AUTO] SCP到本地完成")

        # HTTP POST上传到4090
        with open("/tmp/mac_forward.tar.gz", "rb") as f:
            r = requests.post(UPLOAD_URL, data=f, timeout=180)
            print(f"[AUTO] 上传4090: HTTP {r.status_code}")
    except Exception as e:
        print(f"[AUTO] 转发失败: {e}")


def heartbeat_loop():
    while True:
        try:
            rs = requests.get(ORIN + "/record/status", timeout=5).json()
            recording = rs.get("recording", False)
            payload = {"mac_online": True, "orin": {"online": True, "recording": recording}, "ts": time.time()}
            requests.post(HB_URL, json=payload, timeout=8)
        except:
            pass
        # 每15秒检测是否有新录制完成需转发
        check_and_forward()
        time.sleep(15)


def serve_forever(port, handler):
    s = HTTPServer(("0.0.0.0", port), handler)
    s.serve_forever()


if __name__ == "__main__":
    threading.Thread(target=serve_forever, args=(MAC_HEALTH_PORT, HealthHandler), daemon=True).start()
    threading.Thread(target=serve_forever, args=(FORWARD_PORT, ForwardHandler), daemon=True).start()
    print(f"[小芳] 健康端 :{MAC_HEALTH_PORT}, 转发端 :{FORWARD_PORT}")
    heartbeat_loop()
