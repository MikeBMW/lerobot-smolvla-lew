# Z-MAX 仿真联调 & 模型性能基准报告

> 测试日期: 2026-07-10  
> 测试环境: Mac M1 (小芳, Client) + WSL2 RTX4060 (xspace/静静, Server)  
> 仿真框架: Z-MAX Simulation Protocol v1.0 (WebSocket JSON)

---

## 一、仿真系统架构

```
Mac (小芳 — Client)                    WSL2 (xspace — Server)
┌──────────────────────────┐          ┌──────────────────────────┐
│  simulation_client        │  WS JSON│  simulation_server        │
│  ┌──────────────────────┐ │◄───────►│  ┌──────────────────────┐ │
│  │ JointSimulator ×6    │ │sensor   │  │ SmolVLA 450M         │ │
│  │ ForceTorqueSim ×6    │ │  data   │  │ ACT 51.6M            │ │
│  │ CameraSim 640×480    │ │────────►│  │ Inference Engine     │ │
│  │ GripperSim           │ │         │  │                      │ │
│  │ TactileSim 4×4       │ │ action  │  │ Action Prediction    │ │
│  └──────────────────────┘ │◄────────│  └──────────────────────┘ │
│                            │         │                           │
│  发布频率: 30Hz           │         │  推理: CUDA/MPS          │
│  带宽需求: 0.25 Mbps      │         │  模型加载: ~1GB          │
└──────────────────────────┘          └──────────────────────────┘
```

---

## 二、仿真通信性能

| 指标 | 值 | 说明 |
|------|-----|------|
| 传感器包大小 | 1,061 Bytes | 含关节/力/相机/夹爪/触觉 |
| 动作包大小 | 287 Bytes | 6轴位置 + 夹爪 + 推理耗时 |
| 30Hz带宽需求 | 0.25 Mbps | 传感器上行 |
| 推荐最小带宽 | 0.38 Mbps | 含协议开销 |
| 话题数量 | 11 | /sim/* 命名空间 |
| Client独立模式速率 | 16,033 Hz | 无网络瓶颈时 |

---

## 三、模型推理性能对比

### 3.1 SmolVLA (450M) — 主力模型

| 平台 | 设备 | 推理延迟 | 帧率 | 显存 | 精度 |
|------|------|---------|------|------|------|
| **WSL2** | RTX 4060 8GB | 214.7ms | 4.7 FPS | 0.97 GB | fp16 |
| **Mac M1** | MPS | ~300ms | 3.3 FPS | 8GB共享 | fp16 |
| **Orin** | nvgpu | 240ms | 4.1 FPS | 7.4GB共享 | fp16 |

### 3.2 ACT (51.6M) — 快速执行模型

| 平台 | 设备 | 推理延迟 | 帧率 | 显存 | 精度 |
|------|------|---------|------|------|------|
| **WSL2** | RTX 4060 8GB | 8.4ms | 119.2 FPS | 0.28 GB | fp32 |
| **Mac M1** | MPS | ~0.5ms | 2,172 FPS | 0.22 GB | fp32 |
| **Orin** | nvgpu | 未测试 | — | — | — |

### 3.3 SmolVLA-LEW Mini (263K) — 自训练轻量模型

| 平台 | 设备 | 推理延迟 | 帧率 | 参数 |
|------|------|---------|------|------|
| **Mac M1** | MPS | ~0.5ms | ~2,000 FPS | 263K |

---

## 四、仿真集成测试结果

> 测试时间: 2026-07-10 | 测试脚本: `test_simulation_integration.py`

| 测试项 | 结果 | 说明 |
|--------|------|------|
| 协议编解码 | ✅ | action 289B, sensor 1061B |
| 传感器模拟器 | ✅ | 关节/力/相机/夹爪/触觉 5类全通过 |
| Client独立模式 | ✅ | 100包数据, 16,033 Hz |
| 吞吐量基准 | ✅ | 0.25 Mbps @30Hz |
| 话题名兼容性 | ✅ | 11话题, /sim/命名空间 |
| Client-Server联通 | ⏭ | 需WSL2端启动Server |

---

## 五、Z-MAX 双模型策略

```
产线任务分流:
  Level 1 (高速重复) → ACT 51.6M → Orin/Mac 本地推理 (2172 FPS)
  Level 2 (变种任务) → SmolVLA 450M → WSL2推理 → WebSocket下发
  Level 3 (新任务)   → SmolVLA微调 → Expert 100M快速适配
```

### 仿真模式下推荐配置

| 场景 | Server位置 | 模型 | 延迟 | 适用 |
|------|-----------|------|------|------|
| 本地快速验证 | Mac standalone | ACT | <1ms | 基础动作测试 |
| 端到端仿真 | WSL2 Server | SmolVLA | ~215ms | 完整感知-决策-执行 |
| 轻量仿真 | Mac MPS | SmolVLA | ~300ms | 离线VLA验证 |
| Orin端侧 | Orin本地 | SmolVLA | ~240ms | 真机部署前验证 |

---

## 六、已知限制

1. Mac无ROS2 Humble → WebSocket JSON替代ROS2 DDS
2. 相机仿真使用占位帧 → 真实推理需替换为实际图像
3. SmolVLA在Mac MPS上未量化 → 推理延迟~300ms
4. WebSocket单连接模式 → 多客户端需扩展

---

*报告自动生成, 仿真框架 v1.0*
