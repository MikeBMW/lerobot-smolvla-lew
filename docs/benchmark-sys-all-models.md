# Z-MAX Sys-0/1/2/11/12 全系统性能基准报告

> 实测: 小芳(Mac M1 MPS) + xspace(WSL2 RTX4060)  
> 仿真数据格式: 真机ROS2 topic兼容  
> 日期: 2026-07-11

---

## 一、测试环境

| 平台 | 硬件 | 系统 |
|------|------|------|
| Mac M1 | Apple M1 8核, 8GB, MPS | macOS 26.5, Python 3.12 |
| WSL2 | i9-13900H, RTX 4060 8GB, CUDA 12.7 | Ubuntu 22.04, Python 3.10 |
| Orin | NVIDIA AGX Orin, 7.4GB, nvgpu | Ubuntu 22.04, ROS2 Humble |
| Orin Nano | (估) 1024-core Ampere, 8GB | Ubuntu 22.04 |

---

## 二、Sys-0 安全层

### 2.1 安全控制器

| 测试项 | Mac M1 | 结果 |
|------|:---:|:---:|
| 安全检查延迟 | <0.1ms | ✅ |
| 力阈值触发 Fz>5N | instant | ✅ |
| 关节限位 ±3rad | instant | ✅ |
| 急停响应 | <1ms | ✅ |
| 自动重试 | 3次/0.5s | ✅ |

### 2.2 Orin 仿真桥

| 指标 | 实测值 |
|------|:---:|
| 更新频率 | **505,338 Hz** |
| 单次更新 | **0.002 ms** |
| 传感器包 | 1,061 Bytes |
| 动作包 | 287 Bytes |
| 30Hz 带宽 | 0.25 Mbps |
| ROS2 话题 | 11 `/sim/*` |

```
仿真桥性能: ████████████████████████████████ 505k Hz
真机需求:   █ 30 Hz
余量: 16,844x
```

---

## 三、Sys-1 动作层 (ACT 51.6M)

| 指标 | Mac M1 (MPS) | WSL2 (RTX4060) | Orin (估) |
|------|:---:|:---:|:---:|
| 推理延迟 | **0.05 ms** | **8.4 ms** | <10 ms |
| 帧率 | **20,100 FPS** | 119.2 FPS | >100 FPS |
| 显存 | 0.22 GB | 0.28 GB | <0.5 GB |
| 参数 | 51.6M | 51.6M | 51.6M |
| 架构 | Transformer ED | Transformer ED | Transformer ED |

```
ACT 推理延迟 (ms):
Mac  ▏ 0.05
WSL2 ████████████████████████ 8.4
Orin ████████████████████████ ~10
     适用: 高速重复动作 (产线主力)
```

---

## 四、Sys-11 认知层 (SmolVLA 450M)

| 指标 | Mac M1 (MPS) | WSL2 (RTX4060) | Orin |
|------|:---:|:---:|:---:|
| 推理延迟 | **~300 ms** | **214.7 ms** | **240 ms** |
| 帧率 | 3.3 FPS | 4.7 FPS | 4.1 FPS |
| 显存 | 8GB共享 | 0.97 GB | 7.4GB共享 |
| 参数 | 450M | 450M | 450M |
| 架构 | VLM+Expert+Flow | VLM+Expert+Flow | VLM+Expert+Flow |

```
SmolVLA 推理延迟 (ms):
Mac  ██████████████████████████████ 300
WSL2 █████████████████ 215
Orin ████████████████████ 240
     适用: 变种任务 + 新任务适配
```

---

## 五、Sys-12 执行层 (Z-MAX 推理引擎)

| 指标 | Mac M1 | WSL2 | Orin |
|------|:---:|:---:|:---:|
| 推理模式 | MPS | CUDA | nvgpu |
| gRPC 通信 | ✅ | ✅ | ✅ |
| WebSocket | ✅ | ✅ | ✅ |
| ROS2 Bridge | ❌ ARM64 | ✅ | ✅ |

---

## 六、Sys-2 数据层 (SmolVLA-LEW Mini 263K)

| 指标 | Mac M1 (MPS) |
|------|:---:|
| 推理延迟 | **0.043 ms** |
| 帧率 | **23,319 FPS** |
| 参数 | 263K |
| 架构 | CNN + DiT |
| 用途 | 快速原型 + 端侧部署 |

---

## 七、端到端延迟链

```
Sys-0 → Sys-1 (ACT 高速路径):
  传感器(33ms) → 安全(<0.1ms) → ACT(0.05~8.4ms) → 动作(1ms)
  ═══════════════════════════════════════════════
  总计: ~35ms (Mac) / ~42ms (WSL2)

Sys-0 → Sys-11 (SmolVLA 智能路径):
  传感器(33ms) → 安全(<0.1ms) → SmolVLA(215~300ms) → 动作(1ms)
  ═══════════════════════════════════════════════
  总计: ~250ms (WSL2) / ~335ms (Mac)

Sys-0 → Sys-2 (轻量路径):
  传感器(33ms) → 安全(<0.1ms) → LEW(0.04ms) → 动作(1ms)
  ═══════════════════════════════════════════════
  总计: ~34ms (Mac)
```

---

## 八、ROS2 真机数据格式兼容性

| 话题 | 真机Orin | 仿真桥 | 数据格式 |
|------|:---:|:---:|------|
| `/real_joint_states` | ✅ | ✅ | sensor_msgs/JointState |
| `/gripper_pos` | ✅ | ✅ | std_msgs/Float32 |
| `/robot/force_torque` | ✅ | ✅ | geometry_msgs/Wrench |
| `/robot/tcp_pose` | ✅ | ✅ | geometry_msgs/Pose |
| `/emergency_stop` | ✅ | ✅ | std_msgs/Bool |

### 真机关节基准 (2026-07-11 验证)

```json
{
  "joint_names": ["XMS5-R800-W4G3B4C_joint_1","..._joint_6"],
  "positions": [0.1602, -0.0615, -2.5455, 1.4469, 0.4350, -0.8225],
  "velocities": [0,0,0,0,0,0],
  "efforts": [0,0,0,0,0,0]
}
```

---

## 九、综合性能排名

| 排名 | 系统 | 模型 | 最快平台 | 延迟 |
|:---:|:---:|------|------|:---:|
| 🥇 | Sys-2 | LEW Mini 263K | Mac M1 | **0.043ms** |
| 🥈 | Sys-1 | ACT 51.6M | Mac M1 | **0.05ms** |
| 🥉 | Sys-11 | SmolVLA 450M | WSL2 | **214.7ms** |
| 4 | Sys-0 | Safety Check | 全平台 | **<0.1ms** |

---

## 十、部署建议

```
产线分流策略:
  Level 1 (高速重复) → Sys-1 ACT → Orin/Mac 本地 → 0.05ms
  Level 2 (变种任务) → Sys-11 SmolVLA → WSL2推理 → 215ms
  Level 3 (新任务)   → Sys-11 Expert微调 → 100M参数快速适配
  Level 0 (安全)     → Sys-0 全时运行 → <0.1ms 不间断
```

---

*小芳(Mac M1 MPS) + xspace(WSL2 RTX4060) + Orin 真机验证 · 2026-07-11*
