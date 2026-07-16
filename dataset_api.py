#!/usr/bin/env python3
"""MetaWorld 数据集接收与训练调度 API
数据链路: xspace(4060) → 4090:/root/datasets/ → 训练 → /root/models/deployed/ → 小芳(Mac)
"""
import http.server, json, os, subprocess, threading, time, sys

DATASET_DIR = "/root/datasets"
MODEL_DIR = "/root/models"
DEPLOY_DIR = "/root/models/deployed"
PORT = 50055
TASKS = {}

class DatasetHandler(http.server.BaseHTTPRequestHandler):
    def _json(self, data, code=200):
        self.send_response(code)
        self.send_header('Content-Type','application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data,ensure_ascii=False).encode())

    def do_GET(self):
        if self.path == '/status':
            return self._json({'status':'ready','datasets':os.listdir(DATASET_DIR)})
        if self.path.startswith('/tasks'):
            return self._json(TASKS)
        self._json({'error':'not found'},404)

    def do_POST(self):
        if self.path == '/dataset/upload':
            length = int(self.headers.get('Content-Length',0))
            data = json.loads(self.rfile.read(length))
            name = data.get('name','unknown')
            scene = data.get('scene','unknown')
            path = f"{DATASET_DIR}/{name}_{scene}.json"
            with open(path,'w') as f:
                json.dump(data,f,ensure_ascii=False,indent=2)
            return self._json({'status':'ok','path':path,'size':len(json.dumps(data))})

        if self.path == '/train/start':
            length = int(self.headers.get('Content-Length',0))
            cfg = json.loads(self.rfile.read(length))
            tid = f"train_{int(time.time())}"
            TASKS[tid] = {'status':'queued','config':cfg,'created':time.time()}
            # Start training in background
            t = threading.Thread(target=run_training,args=(tid,cfg))
            t.start()
            return self._json({'task_id':tid,'status':'queued'})

def run_training(tid, cfg):
    TASKS[tid]['status'] = 'running'
    try:
        model = cfg.get('model','smolvla')
        scene = cfg.get('scene','pick-place')
        epochs = cfg.get('epochs',100)
        # Training would go here
        TASKS[tid]['status'] = 'done'
        TASKS[tid]['model_path'] = f"{DEPLOY_DIR}/{model}_{scene}.pt"
    except Exception as e:
        TASKS[tid]['status'] = 'failed'
        TASKS[tid]['error'] = str(e)

print(f"📦 数据集API @ 0.0.0.0:{PORT}")
print(f"   接收: POST /dataset/upload")
print(f"   训练: POST /train/start")
print(f"   状态: GET /status")
http.server.HTTPServer(("0.0.0.0",PORT), DatasetHandler).serve_forever()
