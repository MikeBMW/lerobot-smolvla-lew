---
name: zmax-groot
description: NVIDIA Isaac GR00T N1.7 — 通用具身推理模型 (Sys-2云端引擎)
tags: [zmax, sys2, groot, nvidia, cloud, vla]
version: 1.0.0
platforms: [linux]
metadata:
  model: NVIDIA/Cosmos-Reason2-2B
  vram: 8-16GB
  latency: ~500ms
  source: https://github.com/NVIDIA/Isaac-GR00T
---

# Z-MAX Sys-2 · GR00T Skill

NVIDIA Isaac GR00T N1.7 通用具身推理模型。Cosmos-Reason2-2B骨干 + Flow Matching DiT动作解码，40步动作horizon，原生LeRobot接口。

## 部署位置

AutoDL RTX4090 (106.75.239.80:23) `/root/Isaac-GR00T/`

## 架构

```
GR00T N1.7
├── Backbone: Cosmos-Reason2-2B (Qwen3-VL, 2B参数)
├── Action Head: Flow Matching DiT (16层/32头/1024维)
├── Action Horizon: 40步, 132-dim
├── Inference: 4步Flow ODE
└── Interface: Gr00tPolicy (LeRobot兼容)
```

## 关键配置

- `model_type`: Gr00tN1d7
- `backbone`: nvidia/Cosmos-Reason2-2B
- `action_horizon`: 40
- `hidden_size`: 1024
- `num_inference_timesteps`: 4
- `diffusion_model_cfg.num_layers`: 16

## 使用方法

```python
from gr00t import Gr00tPolicy
model = Gr00tPolicy.from_pretrained("nvidia/GR00T-N1-7")
action = model.predict(obs)
```

## 集成点

- Sys-2 Agent: `hermes skill:zmax-groot`
- gRPC Server: `/root/groot_server.py :50052`
- 仿真反馈: 接收 `SimFeedback` JSON → 动作输出

## 性能预估

- RTX4090 24GB: 可运行, 推理~500ms/帧
- 显存: 8-12GB (bf16)
- 吞吐: 2 FPS
