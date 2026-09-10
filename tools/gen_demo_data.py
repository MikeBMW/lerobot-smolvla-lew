#!/usr/bin/env python3
"""生成 Z-MAX 闭环模拟数据: 300帧 ≈ 10秒 @30fps → LeRobot npz (供 ACT 训练验证)"""
import numpy as np, json, time
from pathlib import Path

OUT = Path.home() / "lerobot-smolvla-lew" / "data" / "closed_loop"
OUT.mkdir(parents=True, exist_ok=True)

N = 300          # 10秒 @30fps
N_JOINT = 7      # 6轴 + 夹爪
N_ACTION = 6
N_CHUNK = 7      # ACT chunk_size

rng = np.random.default_rng(42)
t = np.linspace(0, 2 * np.pi, N)

# 关节轨迹: 正弦插拔运动
states = np.stack([0.5 + 0.4 * np.sin(t + i * 0.7) for i in range(N_JOINT)], axis=1).astype(np.float32)
# 动作: 从当前状态推出 (前向差分 + 噪声)
actions = np.stack([np.gradient(states[:, i]) * 50 for i in range(N_JOINT - 1)], axis=1).astype(np.float32)
# 观测图像: 简单合成 (3,64,64) 归一化
obs = np.zeros((N, 3, 64, 64), dtype=np.float32)
for i in range(N):
    obs[i, 0] = 0.3 + 0.2 * np.sin(t[i])
    obs[i, 1] = 0.3 + 0.2 * np.cos(t[i])
    obs[i, 2] = 0.4

npz = OUT / "task_closed_loop.npz"
np.savez_compressed(npz, observations=obs, states=states, actions=actions,
                    task_name="zmax_closed_loop", fps=30)
print(f"✅ 数据集: {npz} ({npz.stat().st_size//1024}KB)")
print(f"   states {states.shape} / actions {actions.shape} / obs {obs.shape}")
