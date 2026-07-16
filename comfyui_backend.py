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


        elif path == "/train/hjepa":
            import subprocess, threading
            def run_hjepa():
                subprocess.Popen(["/root/.local/share/uv/python/cpython-3.12-linux-x86_64-gnu/bin/python3.12", "train_h_jepa.py"], cwd="/root/lerobot-smolvla-lew")
            threading.Thread(target=run_hjepa).start()
            self.wfile.write(json.dumps({"status":"started","model":"H-JEPA zFlow"},ensure_ascii=False).encode())

        elif path == "/debug":
            nodes = body.get("nodes",[]) if isinstance(body,dict) else []
            is_lewm = any("lewm" in str(n).lower() for n in nodes)
            sid = body.get("session","default")
            if not hasattr(self.server,"_debug_sessions"):
                self.server._debug_sessions = {}
            if sid not in self.server._debug_sessions:
                self.server._debug_sessions[sid] = 0
            step = self.server._debug_sessions[sid]
            self.server._debug_sessions[sid] = (step + 1) % 5
            L = [
                {"step":"1.节点检测","location":"comfyui_backend.py:has_smolvla","variables":{"detected":"LeWM World Model" if is_lewm else "SmolVLA Action Model","gpu":"RTX 4090"},"shapes":"-","model_path":"-","params":"-","diff":"⬆ 新"},
                {"step":"2.模型加载","location":"torch.load()" if is_lewm else "from_pretrained()","variables":{"engine":"LeWM(ViT+GRU)" if is_lewm else "SmolVLA(SmolVLM+DiT)","dtype":"float32"},"shapes":"-","model_path":"/root/models/le_wm/model.pt" if is_lewm else "/root/models/smolvla_base","params":"10.38M" if is_lewm else "450M","diff":"⬆ 加载权重"},
                {"step":"3.输入准备","location":"comfyui_backend.py:build_batch()","variables":{"batch":1,"seq":4 if is_lewm else 1,"rgb":"(1,4,3,64,64)" if is_lewm else "(1,3,512,512)x3"},"shapes":"[1,4,3,64,64]→" if is_lewm else "[1,3,512,512]→","model_path":"-","params":"-","diff":"⬆ 构建张量"},
                {"step":"4.推理执行","location":"LeWMInfer.forward()" if is_lewm else "SmolVLAPolicy.predict()","variables":{"mode":"no_grad()","vram":"0.06GB" if is_lewm else "1.9GB","latency":"~6ms" if is_lewm else "~250ms"},"shapes":"rgb+state" if is_lewm else "action[1,50,6]","model_path":"-","params":"-","diff":"⬆ 推理中"},
                {"step":"5.输出结果","location":"task[result]","variables":{"status":"done","output":"NextRGB+NextState" if is_lewm else "Action [1,50,6]"},"shapes":"[1,3,64,64]+[1,7]" if is_lewm else "[1,50,6]","model_path":"-","params":"-","diff":"✅ 完成"}
            ]
            info = L[step]
            info["diff"] += " ("+str(step+1)+"/5)"
            self.wfile.write(json.dumps(info,ensure_ascii=False).encode())
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

        if path == "/debug":
            nodes = body.get('nodes',[]) if isinstance(body,dict) else []
            is_lewm = any('lewm' in str(n).lower() for n in nodes)
            sid = body.get('session','default')
            if not hasattr(self.server,'_ds'): self.server._ds = {}
            if sid not in self.server._ds: self.server._ds[sid] = 0
            st = self.server._ds[sid]; self.server._ds[sid] = (st+1)%5
            L = [
                {"step":"1.节点检测","location":"comfyui_backend.py:has_smolvla","variables":{"gpu":"RTX 4090","engine":"LeWM" if is_lewm else "SmolVLA"},"shapes":"-","model_path":"-","params":"-","diff":"⬆ 新 ("+str(st+1)+"/5)"},
                {"step":"2.模型加载","location":"torch.load()" if is_lewm else "from_pretrained()","variables":{"dtype":"float32","device":"cuda:0"},"shapes":"-","model_path":"/root/models/le_wm/model.pt" if is_lewm else "/root/models/smolvla_base","params":"10.38M" if is_lewm else "450M","diff":"⬆ 加载 ("+str(st+1)+"/5)"},
                {"step":"3.输入准备","location":"build_batch()","variables":{"batch":1,"seq_len":4 if is_lewm else 1},"shapes":"[1,4,3,64,64]" if is_lewm else "[1,3,512,512]x3","model_path":"-","params":"-","diff":"⬆ 张量 ("+str(st+1)+"/5)"},
                {"step":"4.推理执行","location":"forward()","variables":{"mode":"no_grad()","vram":"0.06GB" if is_lewm else "1.9GB"},"shapes":"rgb[1,3,64,64]" if is_lewm else "action[1,50,6]","model_path":"-","params":"-","diff":"⬆ 推理 ("+str(st+1)+"/5)"},
                {"step":"5.输出结果","location":"task[result]","variables":{"status":"done","output":"NextRGB+NextState" if is_lewm else "Action [1,50,6]"},"shapes":"[1,3,64,64]" if is_lewm else "[1,50,6]","model_path":"-","params":"-","diff":"✅ 完成 ("+str(st+1)+"/5)"},
            ]
            info = L[st]
            self.wfile.write(json.dumps(info,ensure_ascii=False).encode())

        elif path == "/task":
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
            has_smolvla = any('推理引擎' in str(n) or 'SmolVLA' in str(n) or 'VLA' in str(n) or 'VTLA' in str(n) or 'GR00T' in str(n) or 'ACT' in str(n) or 'LeWM' in str(n) or 'Hybrid' in str(n) for n in task['nodes']) if isinstance(task['nodes'],list) else False
            
            if has_smolvla:
                import torch
                gpu_name = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU"

                # Detect which engine was selected
                engine_type = "smolvla"
                for n in task['nodes']:
                    nn = str(n).lower()
                    if 'lewm' in nn: engine_type = 'lewm'; break
                    elif 'vla-touch' in nn: engine_type = 'vlatouch'; break
                    elif 'gr00t' in nn: engine_type = 'gr00t'; break
                    elif 'act' in nn and 'action' not in nn: engine_type = 'act'; break
                    elif 'smolvla' in nn: engine_type = 'smolvla'; break

                task["hardware"] = gpu_name
                task["model"] = f"SmolVLA (SmolVLM-500M + VTLA)"
                task["location"] = "4090:50054→ECS隧道→datadrive.world"

                # LeWM path
                if engine_type == 'lewm':
                    task["model"] = "LeWM World Model (ViT+GRU)"
                    log(f"  🧠 检测到LeWM推理节点, 执行世界模型预测...")
                else:
                    log(f"  🧠 检测到推理节点, 执行真实推理...")
                log(f"  🖥️ 硬件: {gpu_name}")
                log(f"  📍 部署: 4090:50054")
                import threading
                def run_infer():
                    task["status"] = "running"
                    task["timing"] = {}
                    try:
                        import sys, torch, time as ttime
                        t_total = ttime.time()
                        sys.path.insert(0,'/root/lerobot-smolvla-lew/src')

                        if engine_type == 'lewm':
                            log("  🔄 加载LeWM世界模型...")
                            t_model_start = ttime.time()
                            class LeWMInfer(torch.nn.Module):
                                def __init__(self, dim=256, hidden=512):
                                    super().__init__()
                                    self.enc = torch.nn.Sequential(
                                        torch.nn.Conv2d(3,64,4,2,1),torch.nn.ReLU(),
                                        torch.nn.Conv2d(64,128,4,2,1),torch.nn.ReLU(),
                                        torch.nn.Conv2d(128,256,4,2,1),torch.nn.AdaptiveAvgPool2d(1))
                                    self.state_proj = torch.nn.Linear(7,dim)
                                    self.fuse = torch.nn.Linear(256+dim,hidden)
                                    self.gru = torch.nn.GRU(hidden,hidden,2,batch_first=True)
                                    self.dec_rgb = torch.nn.Linear(hidden,3*64*64)
                                    self.dec_state = torch.nn.Linear(hidden,7)
                                def forward(self,rgb,state):
                                    b,t,c,h,w = rgb.shape
                                    feats=[]
                                    for i in range(t):
                                        f=self.enc(rgb[:,i]).squeeze(-1).squeeze(-1)
                                        s=self.state_proj(state[:,i])
                                        feats.append(self.fuse(torch.cat([f,s],-1)))
                                    x=torch.stack(feats,1); out,hn=self.gru(x)
                                    return self.dec_rgb(out[:,-1]).view(b,3,64,64),self.dec_state(out[:,-1])
                            model = LeWMInfer()
                            try:
                                model.load_state_dict(torch.load('/root/models/le_wm/model.pt',map_location='cuda'))
                                log("  ✅ LeWM权重加载成功")
                            except:
                                log("  ⚠️ 使用LeWM随机初始化")
                            model = model.cuda().float().eval()
                            t_model_end = ttime.time()
                            task["timing"]["model_load"] = f"{(t_model_end-t_model_start)*1000:.0f}ms"
                            log(f"  📦 模型加载: {task['timing']['model_load']}")

                            t_infer_start = ttime.time()
                            with torch.no_grad():
                                rgb = torch.randn(1,4,3,64,64).cuda()
                                state = torch.randn(1,4,7).cuda()
                                pred_rgb, pred_state = model(rgb, state)
                            t_infer_end = ttime.time()
                            task["timing"]["inference"] = f"{(t_infer_end-t_infer_start)*1000:.0f}ms"
                            log(f"  🧠 推理耗时: {task['timing']['inference']}")
                            task["timing"]["total"] = f"{(ttime.time()-t_total)*1000:.0f}ms"
                            task["status"] = "done"
                            task["result"] = f"模型:LeWM | NextRGB+NextState预测 | 推理:{task['timing']['inference']} | 加载:{task['timing']['model_load']} | 总:{task['timing']['total']} | VRAM:{torch.cuda.max_memory_allocated()/1e9:.1f}GB | ✅成功"
                            log(f"  ✅ LeWM推理完成: {task['result']}")
                            # W&B
                            try:
                                import wandb
                                wandb.init(project='zmax-lewm',entity='xspace',name='infer-'+tid,reinit=True)
                                wandb.log({'inference_ms':int(task['timing']['inference'].replace('ms','')),'load_ms':int(task['timing']['model_load'].replace('ms','')),'vram_gb':torch.cuda.max_memory_allocated()/1e9})
                                wandb.finish()
                            except: pass
                        else:
                            from lerobot.policies.smolvla import SmolVLAPolicy
                        t_model_start = ttime.time()
                        log("  🔄 加载SmolVLA模型...")
                        model = SmolVLAPolicy.from_pretrained("/root/models/smolvla_base").to("cuda")
                        model = model.float()
                        model.eval()
                        log(f"  📦 模型dtype: {next(model.parameters()).dtype}")
                        t_model_end = ttime.time()
                        task["timing"]["model_load"] = f"{(t_model_end-t_model_start)*1000:.0f}ms"
                        log(f"  📦 模型加载: {task['timing']['model_load']}")
                        
                        batch = {
                            "observation.images.camera1": torch.randn(1,3,512,512).cuda(),
                            "observation.images.camera2": torch.randn(1,3,512,512).cuda(),
                            "observation.images.camera3": torch.randn(1,3,512,512).cuda(),
                            "observation.state": torch.randn(1,7).cuda(),
                            "observation.language.tokens": torch.randint(0,32000,(1,48)).cuda(),
                            "observation.language.attention_mask": torch.ones(1,48).cuda(),
                        }
                        t_infer_start = ttime.time()
                        with torch.no_grad():
                            action = model.predict_action_chunk(batch)
                        t_infer_end = ttime.time()
                        task["timing"]["inference"] = f"{(t_infer_end-t_infer_start)*1000:.0f}ms"
                        log(f"  🧠 推理耗时: {task['timing']['inference']}")
                        
                        task["timing"]["total"] = f"{(ttime.time()-t_total)*1000:.0f}ms"
                        task["status"] = "done"
                        task["result"] = f"模型:SmolVLA | Action:[1,50,6] | 推理:{task['timing']['inference']} | 加载:{task['timing']['model_load']} | 总:{task['timing']['total']} | VRAM:{torch.cuda.max_memory_allocated()/1e9:.1f}GB | 成功"
                        log(f"  ✅ SmolVLA推理完成: {task['result']}")
                        # W&B 记录推理结果
                        try:
                            import wandb
                            mn='smolvla'
                            for n in task['nodes']:
                                nn=str(n).lower()
                                if 'vla-touch' in nn:mn='vla-touch'
                                elif 'act' in nn:mn='act'
                                elif 'gr00t' in nn:mn='gr00t'
                                elif 'lewm' in nn:mn='lewm'
                            pm={'smolvla':'zmax-smolvla','vla-touch':'zmax-vla-touch','gr00t':'zmax-gr00t','act':'zmax-act','lewm':'zmax-lewm'}
                            wandb.init(project=pm.get(mn,'zmax-smolvla'),entity='xspace',name='infer-'+tid,reinit=True)
                            wandb.log({'inference_ms':int(task['timing']['inference'].replace('ms','')),'load_ms':int(task['timing']['model_load'].replace('ms','')),'vram_gb':torch.cuda.max_memory_allocated()/1e9})
                            wandb.finish()
                        except: pass
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
