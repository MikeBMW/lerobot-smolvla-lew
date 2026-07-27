# Z-MAX 模型性能报告 · 仿真联调基准

> 版本: v1.0.4 | 日期: 2026-07-10 | 硬件: RTX 4060 8GB · WSL2 · CUDA 11.8

---

## 一、已训练模型总览

| 模型 | 数据集 | 训练步数 | 参数量 | 最终Loss | Loss降幅 |
|:--|:--|--:|--:|--:|--:|
| **SmolVLA-FlowMatching** | `lerobot/pusht` | 200 | 450M (可训100M) | 2.1 | — |
| **SmolVLA-FlowMatching** | `lerobot/metaworld_mt50` | 300 | 450M (可训100M) | 2.1 | — |
| **SmolVLA-MLP-1024** | `lerobot/metaworld_mt50` | 500 | 14.7M | 0.085 | 81.1% |

---

## 二、推理性能基准

| 指标 | SmolVLA (450M) | ACT (52M) | SmolVLA-MLP (14.7M) |
|:--|--:|--:|--:|
| GPU显存(加载) | 0.93 GB | 0.22 GB | — |
| GPU显存(峰值) | 0.97 GB | 0.28 GB | — |
| 推理延迟 | **214.7 ms** | **8.4 ms** | — |
| 帧率(FPS) | 4.7 | 119.2 | — |
| 架构 | VLM+FlowMatching | Transformer | MLP-1024 |

---

## 三、仿真联调架构 (Client/Server)

```
┌─ 小芳 (Mac M1 · ROS2 Client) ──────────┐
│                                          │
│  📷 摄像头节点 → /camera/rgb              │
│  💪 力传感器 → /force_torque              │
│  ✋ 触觉阵列 → /tactile                    │
│  📡 接收Action ← /robot/action            │
│                                          │
└──────────────┬───────────────────────────┘
               │ gRPC / TCP Bridge
┌──────────────┴───────────────────────────┐
│  静静 (WSL RTX4060 · gRPC Server)        │
│                                          │
│  🧠 SmolVLA推理 (~215ms/帧)              │
│  🧠 ACT推理 (~8ms/帧)                    │
│  📊 性能监控 + 数据记录                    │
│                                          │
└──────────────────────────────────────────┘
```

### 通信协议
- **传输**: gRPC (protobuf)
- **图像**: 3×512×512 RGB, JPEG压缩
- **力/触觉**: float32数组 (6D力 + 16D触觉)
- **动作**: 50步×6D float32
- **延迟预算**: 网络<5ms + 推理215ms = ~220ms/帧

---

## 四、适用场景矩阵

| 场景 | 推荐模型 | 推理位置 | 延迟 | 原因 |
|:--|:--|:--|--:|:--|
| 固定重复操作 | ACT 52M | Orin本地 | 8.4ms | 极快+省显存 |
| 多任务/多指令 | SmolVLA 450M | WSL(gRPC) | 215ms | VLM理解自然语言 |
| 快速原型验证 | SmolVLA-MLP 14.7M | Orin本地 | <5ms | 极简+极快 |
| 精细力控操作 | SmolVLA 450M | WSL(gRPC) | 215ms | FlowMatching轨迹平滑 |
| 离线仿真调试 | 任意 | WSL本地 | — | 无网络延迟 |

---

*报告基于实际训练输出 · outputs/*/training_meta.json*
