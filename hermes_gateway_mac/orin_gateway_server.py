#!/usr/bin/env python3
"""
Orin Gateway Server — 在 Orin 上运行，HTTP API 暴露 ROS2 数据
Mac 端 Gateway 通过局域网 HTTP GET 获取实时数据
延迟: <50ms (局域网 HTTP vs SSH 500ms+)
"""
from http.server import HTTPServer, BaseHTTPRequestHandler
import json, subprocess, time, threading

import re
PORT = 8765
CACHE = {"joints": [], "gripper": 0, "force": {}, "tcp": {}, "estop": False, "ts": 0}
_lock = threading.Lock()

class OrinGateway(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/status":
            self._json({"status": "online", **CACHE})
        elif self.path == "/joints":
            self._json({"joints": CACHE["joints"], "ts": CACHE["ts"]})
        elif self.path == "/health":
            self._json({"online": True, "delay_ms": round((time.time()-CACHE["ts"])*1000, 2)})
        else:
            self._json({"error": "not found"})
    
    def _json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
    
    def log_message(self, *args): pass  # quiet

def poll_ros2():
    global CACHE
    while True:
        try:
            r = subprocess.run([
                "bash", "-c",
                "source /opt/ros/humble/setup.bash && "
                "source ~/0615/tashan_robot_so_20260630_163849_f98c30a_aarch64/install/setup.bash && "
                "export ROS_DOMAIN_ID=23 && "
                "ros2 topic echo --once /real_joint_states 2>/dev/null"
            ], capture_output=True, text=True, timeout=5)
            pos = []
            for line in r.stdout.split("\n"):
                m = re.search(r"^\s*-\s*([\d.\-]+)", line)
                if m: pos.append(float(m.group(1)))
            with _lock:
                CACHE["joints"] = pos[:6] if len(pos) >= 6 else CACHE["joints"]
                CACHE["ts"] = time.time()
        except: pass
        time.sleep(0.05)

if __name__ == "__main__":
    threading.Thread(target=poll_ros2, daemon=True).start()
    print(f"Orin Gateway: http://0.0.0.0:{PORT}")
    HTTPServer(("0.0.0.0", PORT), OrinGateway).serve_forever()
