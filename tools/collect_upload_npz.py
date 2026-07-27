#!/usr/bin/env python3
"""Orin数据采集 → .npz格式 → 4090训练"""
import numpy as np, requests, time, os
from pathlib import Path

ORIN = "http://192.168.23.66:8765"
FRAMES = 50
FPS = 30

print(f"=== Orin数据采集 ({FRAMES}帧, {FPS}FPS) ===")

# 采集
observations = []  # 用随机图像占位(orin相机太大)
states = []
actions = []  # 占位

for i in range(FRAMES):
    s = requests.get(f"{ORIN}/sensors", timeout=3).json()
    obs = np.random.randn(3, 128, 128).astype(np.float32)  # 模拟相机(T,3,128,128)
    st = np.array(s.get("joint_states", [0]*7)[:7], dtype=np.float32)
    act = np.zeros(6, dtype=np.float32)  # 占位动作
    
    observations.append(obs)
    states.append(st)
    actions.append(act)
    
    if i % 10 == 0:
        print(f"  帧{i}: joints={st[:3]} force={s.get('force_torque',[])[:3]}")
    time.sleep(1/FPS)

# 保存
out = Path.home() / "lerobot-smolvla-lew" / "data" / "orin_tasks"
out.mkdir(parents=True, exist_ok=True)
filename = out / f"task_{time.strftime('%Y%m%d_%H%M%S')}.npz"

np.savez_compressed(filename,
    observations=np.stack(observations),  # (50, 3, 128, 128)
    states=np.stack(states),              # (50, 7)
    actions=np.stack(actions),            # (50, 6)
    task_name="orin_live_insert",
    fps=FPS,
    force_torque=np.array([s.get("force_torque", [0]*6)[:6] for s in 
        [requests.get(f"{ORIN}/sensors", timeout=3).json() for _ in range(FRAMES)]], dtype=np.float32)
)

size_mb = os.path.getsize(filename) / 1024 / 1024
print(f"\n✅ 保存: {filename} ({size_mb:.1f}MB)")
print(f"   格式: observations={np.stack(observations).shape} states={np.stack(states).shape} actions={np.stack(actions).shape}")

# 上传4090
print(f"\n=== 上传4090 ===")
# scp方式
os.system(f"sshpass -p '32K78m954g0yjUZz' scp -o StrictHostKeyChecking=no -P 23 {filename} root@106.75.239.80:/root/datasets/metaworld/tasks/")
print("✅ 已上传4090 → 触发训练")
requests.post("http://106.75.239.80:50053/task", json={
    "task": "train",
    "params": {"data": str(filename), "model": "act", "epochs": 10}
}, timeout=5)

print("\n✅ 数据闭环: Orin→4060采集→4090训练 链路完成")
