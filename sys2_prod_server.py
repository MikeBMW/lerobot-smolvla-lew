#!/usr/bin/env python3
"""Z-MAX Sys2 生产服务 — 4090 上的 VTLA/GR00T 推理 API"""
import json, sys, os, time
sys.path.insert(0, '/root/lerobot-smolvla-lew/src')
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'

import torch, numpy as np
from http.server import HTTPServer, BaseHTTPRequestHandler

DEVICE = torch.device("cuda")
MODELS = {}

def load_vtla():
    from lerobot.policies.smolvla import SmolVLAPolicy
    from transformers import AutoTokenizer
    from lerobot.policies.smolvla.modeling_smolvla import resize_with_pad
    from lerobot.utils.constants import OBS_LANGUAGE_TOKENS, OBS_LANGUAGE_ATTENTION_MASK
    
    t0 = time.time()
    # Override config to use local model path
    import json as _json
    cfg = _json.load(open('/root/models/smolvla_base/config.json'))
    cfg['vlm_model_name'] = '/root/models/smolvlm2-500m'
    _json.dump(cfg, open('/root/models/smolvla_base/config.json','w'))
    
    model = SmolVLAPolicy.from_pretrained("/root/models/smolvla_base").to(DEVICE).eval()
    tokenizer = AutoTokenizer.from_pretrained("/root/models/smolvlm2-500m")
    
    def predict(obs):
        B=1
        img = obs.get('image', torch.rand(B,3,480,640,device=DEVICE))
        if isinstance(img, list): img = torch.tensor(img,device=DEVICE).reshape(B,3,480,640)
        img = resize_with_pad(img,512,512,pad_value=0)*2-1
        state = obs.get('state', torch.zeros(B,14,device=DEVICE))
        if isinstance(state, list): state = torch.tensor(state,device=DEVICE).reshape(B,-1)
        task = obs.get('task', 'complete the task')
        enc = tokenizer(str(task), return_tensors="pt", padding="max_length", max_length=48, truncation=True)
        batch = {
            "observation.images.camera1": img,
            "observation.images.camera2": torch.ones(B,3,512,512,device=DEVICE)*-1,
            "observation.images.camera3": torch.ones(B,3,512,512,device=DEVICE)*-1,
            "observation.state": state,
            OBS_LANGUAGE_TOKENS: enc["input_ids"].to(DEVICE),
            OBS_LANGUAGE_ATTENTION_MASK: enc["attention_mask"].to(torch.bool).to(DEVICE),
        }
        with torch.no_grad():
            action = model.predict_action_chunk(batch)
        return action[0,0,:].cpu().tolist()
    
    return {"name":"vtla","params_M":round(sum(p.numel() for p in model.parameters())/1e6),
            "load_s":round(time.time()-t0,1),"predict":predict}

class Sys2Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self._json({"status":"ok","gpu":"RTX 4090","vram_gb":round(torch.cuda.get_device_properties(0).total_memory/1e9,1),
                        "models":list(MODELS.keys()),"ready":len(MODELS)>0})
        else:
            self._json({"service":"Z-MAX Sys2","endpoints":["GET /health","POST /predict"]})
    
    def do_POST(self):
        if self.path == '/predict':
            cl = int(self.headers.get('Content-Length',0) or 0)
            body = json.loads(self.rfile.read(cl)) if cl > 0 else {}
            engine = body.get('engine','vtla')
            obs = body.get('observation',{})
            
            if engine in MODELS:
                t0 = time.time()
                action = MODELS[engine]['predict'](obs)
                lat = (time.time()-t0)*1000
                self._json({"action":action,"model_used":engine,"latency_ms":round(lat,1),"status":"ok"})
            else:
                self._json({"action":[0.0]*14,"model_used":"fallback","status":"model_not_loaded"})
        else:
            self._json({"error":"unknown"})
    
    def _json(self, data):
        self.send_response(200); self.send_header('Content-Type','application/json')
        self.send_header('Access-Control-Allow-Origin','*'); self.end_headers()
        self.wfile.write(json.dumps(data).encode())
    def log_message(self,*a): pass

# Load models
print("Loading VTLA...")
MODELS['vtla'] = load_vtla()
print(f"✅ VTLA: {MODELS['vtla']['params_M']}M params, {MODELS['vtla']['load_s']}s load")

# Start server
port = 50052
print(f"\n🚀 Sys2 Server @ 0.0.0.0:{port}")
print(f"   Models: {list(MODELS.keys())}")
print(f"   Health: http://10.23.24.0:{port}/health")
HTTPServer(('0.0.0.0', port), Sys2Handler).serve_forever()
