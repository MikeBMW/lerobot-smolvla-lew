#!/usr/bin/env python3
"""Orin HTTP Gateway — 读 /tmp/joints.json 提供 HTTP API"""
from http.server import HTTPServer, BaseHTTPRequestHandler
import json, time, os

PORT = 8765
JOINT_FILE = "/tmp/joints.json"

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/joints":
            try:
                with open(JOINT_FILE) as f:
                    data = json.load(f)
                self._json(data)
            except:
                self._json({"error": "no data"})
        elif self.path == "/health":
            age = time.time() - (os.path.getmtime(JOINT_FILE) if os.path.exists(JOINT_FILE) else 0)
            self._json({"online": age < 5, "age_ms": round(age*1000)})
        else:
            self._json({"endpoints": ["/joints", "/health"]})
    
    def _json(self, data):
        self.send_response(200); self.send_header("Content-Type","application/json"); self.end_headers()
        self.wfile.write(json.dumps(data).encode())
    def log_message(self, *a): pass

HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
