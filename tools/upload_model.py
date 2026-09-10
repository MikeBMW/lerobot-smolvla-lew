#!/usr/bin/env python3
"""后台上传模型到 ECS 中转 (CICD 部署第一步)"""
import requests, time, sys

p = sys.argv[1] if len(sys.argv) > 1 else \
    'outputs/train/act_closed_loop/checkpoints/000500/pretrained_model/model.safetensors'
data = open(p, 'rb').read()
print(f"📤 上传 {len(data)//1024//1024}MB → ECS...", flush=True)
t0 = time.time()
r = requests.post('https://datadrive.world/api/relay/upload', data=data, timeout=600)
dt = round(time.time() - t0, 1)
print(f"HTTP {r.status_code} | {dt}s | {r.text[:200]}", flush=True)
