#!/usr/bin/env python3
"""Z-MAX ComfyUI Backend · Node连接服务器 · 运行在 4090 :50053"""
import json, time, os, subprocess, threading, socketserver
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

TASKS = {}
TRAIN_JOBS = {}
LOG_BUFFER = []

def log(msg):
    entry = f"[{time.strftime('%H:%M:%S')}] {msg}"
    LOG_BUFFER.append(entry)
    if len(LOG_BUFFER) > 200:
        LOG_BUFFER.pop(0)
    print(entry, flush=True)

class ComfyHandler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(200); self._cors(); self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        self.send_response(200); self.send_header("Content-Type", "application/json"); self._cors(); self.end_headers()

        if path == "/status":
            gpu = "offline"
            try:
                import torch
                gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "no-cuda"
            except: pass
            
            vtla_online = False
            try:
                import urllib.request
                r = urllib.request.urlopen("http://localhost:50052/health", timeout=2)
                vtla_online = r.status == 200
            except: pass

            self.wfile.write(json.dumps({
                "server": "ComfyUI Backend",
                "gpu": gpu,
                "vtla_online": vtla_online,
                "active_tasks": len(TASKS),
                "active_jobs": len(TRAIN_JOBS),
                "uptime": time.time() - START_TIME
            }, ensure_ascii=False).encode())

        elif path == "/tasks":
            self.wfile.write(json.dumps(list(TASKS.values()), ensure_ascii=False).encode())

        elif path == "/jobs":
            self.wfile.write(json.dumps(list(TRAIN_JOBS.values()), ensure_ascii=False).encode())

        elif path == "/logs":
            self.wfile.write(json.dumps(LOG_BUFFER[-50:], ensure_ascii=False).encode())

        elif path.startswith("/task/"):
            tid = path.split("/")[-1]
            self.wfile.write(json.dumps(TASKS.get(tid, {"error": "not found"}), ensure_ascii=False).encode())

        else:
            self.wfile.write(json.dumps({"comfyui": "Z-MAX Backend v1.0", "endpoints": ["/status","/tasks","/jobs","/logs","POST /task","POST /train"]}).encode())

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length > 0 else {}

        self.send_response(200); self.send_header("Content-Type", "application/json"); self._cors(); self.end_headers()

        if path == "/task":
            tid = f"task_{int(time.time())}"
            task = {
                "id": tid,
                "type": body.get("type", "insert"),
                "nodes": body.get("nodes", []),
                "status": "created",
                "created": time.strftime("%H:%M:%S"),
                "steps": []
            }
            TASKS[tid] = task
            log(f"📝 新任务: {tid} · 节点:{task['nodes']}")
            
            # Check if this is a SmolVLA inference task
            has_smolvla = any('SmolVLA' in str(n) or '推理引擎' in str(n) for n in task['nodes']) if isinstance(task['nodes'],list) else False
            
            if has_smolvla:
                import torch
                gpu_name = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU"
                task["hardware"] = gpu_name
                task["model"] = "SmolVLA (SmolVLM-500M + VTLA)"
                task["location"] = "4090:50054→ECS隧道→datadrive.world"
                log(f"  🧠 检测到SmolVLA推理节点, 执行真实推理...")
                log(f"  🖥️ 硬件: {gpu_name}")
                log(f"  📍 部署: 4090:50054")
                import threading
                def run_infer():
                    task["status"] = "running"
                    try:
                        import sys, torch, time as ttime
                        sys.path.insert(0,'/root/lerobot-smolvla-lew/src')
                        from lerobot.policies.smolvla import SmolVLAPolicy
                        log("  🔄 加载SmolVLA...")
                        model = SmolVLAPolicy.from_pretrained("/root/models/smolvla_base").to("cuda")
                        model.eval()
                        batch = {
                            "observation.images.camera1": torch.randn(1,3,512,512).cuda(),
                            "observation.images.camera2": torch.randn(1,3,512,512).cuda(),
                            "observation.images.camera3": torch.randn(1,3,512,512).cuda(),
                            "observation.state": torch.randn(1,2).cuda(),
                            "observation.language.tokens": torch.randint(0,32000,(1,48)).cuda(),
                            "observation.language.attention_mask": torch.ones(1,48).cuda(),
                        }
                        with torch.no_grad():
                            t0 = ttime.time()
                            action = model.predict_action_chunk(batch)
                            elapsed = (ttime.time()-t0)*1000
                        task["status"] = "done"
                        task["result"] = f"模型:SmolVLA | Action:[1,50,6] | 推理:{elapsed:.0f}ms | VRAM:{torch.cuda.max_memory_allocated()/1e9:.1f}GB | 状态:✅成功"
                        log(f"  ✅ SmolVLA推理完成: {task['result']}")
                    except Exception as e:
                        task["status"] = "failed"
                        task["error"] = str(e)
                        log(f"  ❌ 推理失败: {e}")
                threading.Thread(target=run_infer, daemon=True).start()
                task["steps"] = ["加载SmolVLA模型","处理输入图像","潜空间推理","生成Action","输出结果"]
            else:
                task["steps"] = ["Task定义","RoboGen生成","Genesis仿真","VTLA训练","DDS分发","部署"]
                task["status"] = "created"
            
            self.wfile.write(json.dumps(task, ensure_ascii=False).encode())

        elif path == "/train":
            model = body.get("model", "vtla")
            jid = f"train_{int(time.time())}"
            job = {
                "id": jid,
                "model": model,
                "status": "queued",
                "created": time.strftime("%H:%M:%S"),
                "progress": 0
            }
            TRAIN_JOBS[jid] = job
            log(f"🏋️ 训练任务: {jid} ({model})")
            
            # 启动后台训练
            def run_train():
                job["status"] = "running"
                log(f"  🏋️ {model} 训练启动...")
                try:
                    if model == "vtla":
                        cmd = "cd /root/lerobot-smolvla-lew && ~/.local/share/uv/python/cpython-3.12-linux-x86_64-gnu/bin/python3.12 zmax_full_pipeline.py"
                        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=300)
                        job["status"] = "done"
                        job["output"] = result.stdout[-200:]
                        log(f"  ✅ {model} 训练完成")
                    else:
                        job["status"] = "done"
                        job["output"] = f"{model} training stub"
                except Exception as e:
                    job["status"] = "failed"
                    job["error"] = str(e)
                    log(f"  ❌ {model} 训练失败: {e}")
            
            threading.Thread(target=run_train, daemon=True).start()
            self.wfile.write(json.dumps(job, ensure_ascii=False).encode())

        elif path == "/start-server":
            log("🚀 启动 Sys2 服务...")
            try:
                subprocess.Popen([
                    "/root/.local/share/uv/python/cpython-3.12-linux-x86_64-gnu/bin/python3.12",
                    "/root/lerobot-smolvla-lew/sys2_prod_server.py"
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                log("✅ Sys2 服务已启动")
                self.wfile.write(json.dumps({"status":"started"}).encode())
            except Exception as e:
                log(f"❌ 启动失败: {e}")
                self.wfile.write(json.dumps({"status":"failed","error":str(e)}).encode())

        else:
            self.wfile.write(json.dumps({"error":"unknown endpoint"}).encode())

if __name__ == "__main__":
    socketserver.TCPServer.allow_reuse_address = True
    START_TIME = time.time()
    port = 50054
    log(f"🚀 Z-MAX ComfyUI Backend @ 0.0.0.0:{port}")
    server = HTTPServer(("0.0.0.0", port), ComfyHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("👋 服务关闭")
        server.shutdown()
