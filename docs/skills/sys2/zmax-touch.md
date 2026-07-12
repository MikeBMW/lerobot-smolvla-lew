---
name: zmax-touch
description: VLA-Touch — 触觉增强的视觉-语言-动作模型 (Sys-2 辅助引擎)
tags: [zmax, sys2, touch, tactile, vla, nus]
version: 1.0.0
platforms: [linux]
metadata:
  paper: RA-L 2026
  source: https://github.com/jxbi1010/VLA-Touch
  requirement: LLM API (GPT-4 / Claude)
---

# Z-MAX Sys-2 · VLA-Touch Skill

VLA-Touch: Enhancing Vision-Language-Action Models with Dual-Level Tactile Feedback (RA-L 2026, NUS). 双层触觉反馈增强VLA模型，完美补充Z-MAX的力/触觉感知。

## 部署位置

AutoDL RTX4090 (106.75.239.80:23) `/root/VLA-Touch/`

## 架构

```
VLA-Touch
├── LLM Planner (GPT-4/Claude): 任务分解与规划
├── Tactile Encoder: 双层触觉编码
│   ├── Level 1: 属性分类 (硬度/粗糙度/重量)
│   └── Level 2: 原始触觉图像编码
├── VLA Controller: 视觉+语言+触觉 → 动作
└── Residual Controller: bridge数据集微调
```

## 触觉数据接口

```python
# 已注册Z-MAX触觉传感器 (均胜电子)
tactile_data = {
    "force": float[6],          # 六维力/力矩 (1kHz)
    "tactile_array": float[16], # 触觉阵列 (200Hz, 0.1N精度)
    "gripper": int,             # 夹爪开合度 (0-255)
}
```

## 集成点

- Sys-2 Agent: `hermes skill:zmax-touch`
- 触觉数据流: 小芳ROS2 → gRPC → VLA-Touch推理
- 与其他skill互补: zmax-groot (通用) + zmax-touch (精细力控)

## 性能

- LLM推理: ~1-3s (API调用)
- 触觉编码: <10ms (本地)
- 适用场景: 精密插拔力控 · 异常检测 · 材质识别
