#!/usr/bin/env python3
"""Z-MAX 数据闭环中转服务 · ECS 39.102.211.79
链路: Orin采集 → Mac(8769) → ECS中转(:39053, nginx反代) → 静静4060本地训练
端点:
  POST /upload       上传数据 (json 或 二进制 npz) → 存 /root/zmax-relay/data/
  GET  /latest       拉取最新数据包 (拉取即删)
  GET  /status       链路状态/心跳
  GET  /packages     数据包列表
约束: 缓冲总量 ≤100M, 超限自动删最旧; latest 拉取后即删, 中转不留存
"""
import json, time, os, http.server, glob
from pathlib import Path

DATA_DIR = Path("/root/zmax-relay/data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
START = time.time()
MAX_BUF = 100 * 1024 * 1024  # 缓冲总量上限 100M

def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)

def enforce_buf_limit():
    """缓冲总量 ≤100M：超了删最旧"""
    pkgs = sorted(glob.glob(str(DATA_DIR / "*")), key=os.path.getmtime)
    total = sum(os.path.getsize(p) for p in pkgs)
    while total > MAX_BUF and pkgs:
        oldest = pkgs.pop(0)
        try:
            sz = os.path.getsize(oldest)
            os.remove(oldest)
            total -= sz
            log(f"🧹 超限清理: {os.path.basename(oldest)} (-{sz//1024}KB)")
        except Exception:
            pass

class H(http.server.BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(200); self._cors(); self.end_headers()

    def _send(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors(); self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/status":
            pkgs = sorted(glob.glob(str(DATA_DIR / "*.json")))
            latest = pkgs[-1] if pkgs else None
            info = None
            if latest:
                try:
                    with open(latest) as f: info = json.load(f).get("meta", {})
                except Exception: pass
            self._send({"relay":"Z-MAX ECS中转 v1","uptime":round(time.time()-START),
                        "packages":len(pkgs),"latest":os.path.basename(latest) if latest else None,
                        "latest_meta":info})
        elif path == "/packages":
            pkgs = sorted(glob.glob(str(DATA_DIR / "*.json")))
            self._send([{"name":os.path.basename(p),"size":os.path.getsize(p),
                         "mtime":time.strftime("%H:%M:%S", time.localtime(os.path.getmtime(p)))} for p in pkgs])
        elif path == "/latest":
            pkgs = sorted(glob.glob(str(DATA_DIR / "*.json")))
            if not pkgs:
                self._send({"error":"no data yet"}, 404); return
            latest = pkgs[-1]
            with open(latest) as f:
                obj = json.load(f)
            # 拉取后即删，中转不留存
            try:
                os.remove(latest)
                log(f"📤 已转发并删除 {os.path.basename(latest)}")
            except Exception:
                pass
            self._send(obj)
        else:
            self._send({"relay":"Z-MAX ECS中转 v1","endpoints":["POST /upload","GET /latest","GET /status","GET /packages"]})

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/upload":
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            # 支持 json 或 原始 npz 字节
            try:
                obj = json.loads(raw)
                name = obj.get("name") or f"pkg_{time.strftime('%Y%m%d_%H%M%S')}.json"
                if not name.endswith(".json"): name += ".json"
                meta = obj.get("meta", {})
                frames = obj.get("frames", obj.get("data", []))
                meta["received_at"] = time.time()
                meta["relay"] = "ECS"
                meta["frames"] = len(frames) if isinstance(frames, list) else "?"
                obj["meta"] = meta
                with open(DATA_DIR / name, "w") as f:
                    json.dump(obj, f, ensure_ascii=False)
                log(f"📥 收到数据 {name} | {meta.get('frames')}帧 | {len(raw)}B")
                enforce_buf_limit()
                self._send({"ok":True,"name":name,"frames":meta.get("frames"),"size":len(raw)})
            except json.JSONDecodeError:
                name = f"pkg_{time.strftime('%Y%m%d_%H%M%S')}.npz"
                with open(DATA_DIR / name, "wb") as f:
                    f.write(raw)
                log(f"📥 收到二进制 {name} | {len(raw)}B")
                enforce_buf_limit()
                self._send({"ok":True,"name":name,"size":len(raw)})
        else:
            self._send({"error":"unknown endpoint"}, 404)

if __name__ == "__main__":
    port = 39053
    log(f"🚀 Z-MAX 数据中转服务 @ :{port} (data→{DATA_DIR})")
    http.server.ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
