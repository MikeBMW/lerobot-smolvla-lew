# SmolVLA vs ACT 性能对比报告

> 测试日期: 2026-07-09  
> 硬件环境: WSL2 Ubuntu, Intel i9-13900H, NVIDIA RTX 4060 Laptop 8GB  
> 软件环境: CUDA 11.8, PyTorch 2.7.1, LeRobot (本地开发版)  
> 测试数据: PushT (SmolVLA) / Aloha Sim Transfer Cube (ACT)

---

## 模型信息

| | SmolVLA | ACT |
|---|---------|-----|
| 模型ID | lerobot/smolvla_base | lerobot/act_aloha_sim_transfer_cube_human |
| 架构 | VLM(350M) + Expert(98M) + Flow Head(1.5M) | Transformer Encoder-Decoder |
| 视觉编码 | SmolVLM2-500M (12层Vision+16层Text) | ResNet-18 |
| 动作预测 | Flow Matching (ODE 10步) | 直接回归 (action chunk) |
| 参数量 | 450M | 52M |
| 可训练参数 | 100M (22%) | 52M (100%) |
| 输入 | 3×512×512 图像 + 状态 + 语言 | 1×480×640 图像 + 状态(14D) |
| 输出 | 50步×6D 动作 | 100步×14D 动作 |

---

## 性能测试

| 指标 | SmolVLA | ACT | ACT优势 |
|------|---------|-----|---------|
| GPU显存(加载) | 0.93 GB | 0.22 GB | 4.2× |
| GPU显存(峰值) | 0.97 GB | 0.28 GB | 3.5× |
| 推理延迟(avg) | 214.7 ms | 8.4 ms | 25.6× |
| 帧率(FPS) | 4.7 | 119.2 | 25.6× |
| 每帧能耗 | ~30J | ~1.2J | ~25× |

> 延迟测量: 20轮平均, 含GPU同步, 预热5轮

---

## 架构对比

```
SmolVLA:
  图像 → VLM → Connector → Text Model → hidden
                                           ↓ Cross-Attn
                                       Expert → Flow Match → 动作

ACT:
  图像 → ResNet → 特征 ──┐
                          ├→ Transformer Encoder → Decoder → 动作
  状态 → Proj ──────────┘
```

---

## 适用场景

| 场景 | 推荐 | 原因 |
|------|------|------|
| 固定产线重复操作 | ACT | 极快(119FPS), 省显存(0.22GB) |
| 多任务/多指令 | SmolVLA | VLM理解自然语言指令 |
| 新场景快速适配 | SmolVLA | VLM冻结, 只微调Expert 100M |
| 嵌入式/边缘设备 | ACT | 52M参数, 可在Orin上运行 |
| 精细力控操作 | SmolVLA | Flow Matching轨迹平滑 |
| 视频理解 | SmolVLA | VLM可处理视频输入 |

---

## Z-MAX 双模型策略

```
产线任务分类:
  Level 1 (重复操作) → ACT  → Orin本地推理
  Level 2 (变种任务) → SmolVLA → WSL推理 → gRPC下发
  Level 3 (新任务)   → SmolVLA微调 → 100M快速适配
```

---

*报告自动生成, 硬件信息: `nvidia-smi` + `lscpu`*
