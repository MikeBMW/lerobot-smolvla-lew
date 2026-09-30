#!/usr/bin/env python3
"""Orin Gateway — 内置ros2轮询, 刷新 /tmp/joints.json + HTTP API"""
from http.server import HTTPServer, BaseHTTPRequestHandler
import json, subprocess, time, threading, re, os

PORT = 8765
JOINT_FILE = "/tmp/joints.json"
_cache = []

def poll():
    global _cache
    while True:
        try:
            r = subprocess.run(["bash", "-c",
                "source /opt/ros/humble/setup.bash && "
                "source ~/0615/tashan_robot_so_20260630_163849_f98c30a_aarch64/install/setup.bash && "
                "export ROS_DOMAIN_ID=23 && ros2 topic echo --once /real_joint_states 2>/dev/null"
            ], capture_output=True, text=True, timeout=5)
            pos = []
            for line in r.stdout.split("\n"):
                m = re.search(r"^\s*-\s*([\d.\-]+)", line)
                if m: pos.append(round(float(m.group(1)), 4))
            if len(pos) >= 6:
                _cache = pos
                with open(JOINT_FILE, "w") as f:
                    json.dump(pos, f)
        except: pass
        time.sleep(0.1)

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/joints":
            self._json({"joints": _cache})
        elif self.path == "/health":
            self._json({"online": len(_cache)==6})
        else:
            self._json({"endpoints": ["/joints","/health"]})
    def _json(self, d):
        self.send_response(200); self.send_header("Content-Type","application/json"); self.end_headers()
        self.wfile.write(json.dumps(d).encode())
    def log_message(self, *a): pass

threading.Thread(target=poll, daemon=True).start()
HTTPServer(("0.0.0.0", PORT), H).serve_forever()
