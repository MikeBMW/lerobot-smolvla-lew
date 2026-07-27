# Z-MAX 系统架构 · 五层智能引擎

> 产品: Z-MAX 多模态动作专家 | 版本: v1.0.4 | 设计: 静静(xspace)

---

## ⭕ 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│                      Z-MAX 智能模型引擎                       │
│                                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │  Sys-0   │  │  Sys-1   │  │ Sys-11   │  │ Sys-12   │    │
│  │ L2基线   │  │ L3增强   │  │ L4旗舰   │  │ L4旗舰   │    │
│  │ 无模型   │  │ ACT/VTLA │  │ smolvla  │  │ smolvla  │    │
│  │ 规则引擎 │  │ 双引擎   │  │ 纯动作   │  │  +世界   │    │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘    │
│       │              │              │              │         │
│       │         ┌────┴────┐         │              │         │
│       │         │ 本地推理 │         │              │         │
│       │         │ ACT 8ms  │         │              │         │
│       │         └─────────┘         │              │         │
│       │              │              │              │         │
│       └──────────────┴──────────────┴──────────────┘         │
│                          │                                   │
│                    ┌─────┴─────┐                             │
│                    │   Sys-2   │  ← 云端 / Agent框架          │
│                    │ 大模型调度 │                             │
│                    │           │                             │
│                    │ VTLA 完整版│  GROOT   │  其他技能        │
│                    │ (云端推理) │ (云端)   │  (按需加载)      │
│                    └─────┬─────┘                             │
│                          │                                   │
│              ┌───────────┴───────────┐                       │
│              │   Hermes Agent 封装    │                       │
│              │   · skills 调度        │                       │
│              │   · gRPC 通信          │                       │
│              │   · 仿真数据反馈        │                       │
│              └───────────────────────┘                       │
└─────────────────────────────────────────────────────────────┘
```

---

## 一、Sys-0 · L2 基线版 · 规则引擎

**无AI模型，纯ROS2 Service规则驱动**

```
┌─────────────────────────────────────┐
│  Sys-0: 规则引擎                     │
│                                     │
│  📋 人工流程编排                     │
│  🔧 ROS2 Service 标准接口库          │
│  ⚙️  预设位姿 · 阈值力控              │
│  🛑 双路急停 · 安全光栅 · 光幕联动     │
│                                     │
│  推理: 不需要AI模型                   │
│  延迟: <1ms (ROS2 Service调用)       │
│  硬件: Orin Nano 8GB                │
└─────────────────────────────────────┘
```

**代码位置**: `policies/` 下无对应模型，由 `tools/gui/hardware_simulator.py` 和 ROS2 Service 层实现。

---

## 二、Sys-1 · L3 增强版 · 双引擎

**对外名称: VTLA | 底层引擎: ACT（兼容VTLA框架）**

```
┌──────────────────────────────────────────────┐
│  Sys-1: VTLA 接口（底层 ACT 引擎）            │
│                                              │
│  ┌─────────────┐    ┌──────────────────────┐ │
│  │  VTLA 接口   │    │  ACT 引擎 (当前)      │ │
│  │  (预留)      │    │                      │ │
│  │             │    │  · Transformer 52M    │ │
│  │  · VLM 编码  │    │  · 8.4ms 推理        │ │
│  │  · Flow 解码 │    │  · 0.26GB 显存       │ │
│  │  · 语言理解  │    │  · ResNet-18 视觉     │ │
│  │             │    │                      │ │
│  │  ⏳ 待VTLA   │    │  ✅ 当前运行          │ │
│  │  训练完成    │    │                      │ │
│  └──────┬──────┘    └──────────┬───────────┘ │
│         │                      │             │
│         └──────────┬───────────┘             │
│                    │                         │
│            ┌───────┴───────┐                 │
│            │ 统一动作输出    │                 │
│            │ (7DoF + gripper)│                │
│            └───────────────┘                 │
│                                              │
│  推理位置: Orin AGX 本地                      │
│  对外宣称: VTLA 多模态端到端                    │
│  实际引擎: ACT (52M, 8.4ms)                   │
└──────────────────────────────────────────────┘
```

**代码位置**: `policies/zmax_sys1/`
- `configuration_zmax_sys1.py` — 含 VTLA + ACT 双引擎配置
- `modeling_zmax_sys1.py` — ACT 为主体，预留 VTLA 接口（VLM冻结→FlowMatching→动作头）

---

## 三、Sys-11 · L4 旗舰 · 纯动作

**引擎: smolvla (450M, VLM+FlowMatching)**

```
┌─────────────────────────────────────┐
│  Sys-11: smolvla 纯动作              │
│                                     │
│  👁️  SmolVLM2-500M (16层, 冻结)     │
│  🧠  DiT-B FlowMatching (4步)       │
│  📐  3×256×256 RGB 输入              │
│  💬  自然语言指令理解                  │
│                                     │
│  参数: 450M (100M可训)               │
│  显存: 0.90GB                       │
│  推理: ~215ms (4.7 FPS)             │
│  硬件: Orin AGX 32GB                │
└─────────────────────────────────────┘
```

**代码**: `policies/smolvla/` → 对外 `zmax_sys11`

---

## 四、Sys-12 · L4 旗舰 · 世界模型

**引擎: smolvla_lew (628M, VLM+FlowMatching+LeWorldModel)**

```
┌─────────────────────────────────────┐
│  Sys-12: smolvla_lew 世界模型        │
│                                     │
│  👁️  SmolVLM2-500M                  │
│  🧠  DiT-B + ARPredictor (AdaLN)    │
│  🌍  因果世界模型 (LeWorldModel)      │
│  📹  2帧视频时序输入                  │
│                                     │
│  参数: 631M (25M可训)               │
│  显存: 1.25GB (Sys-11模式)          │
│  推理: ~186ms                       │
│  硬件: Orin AGX 32GB + RK3588       │
└─────────────────────────────────────┘
```

**代码**: `policies/smolvla_lew/` → 对外 `zmax_sys12`

---

## 五、Sys-2 · 云端 Agent 框架

**Hermes Agent 封装，大模型云端调度**

```
┌──────────────────────────────────────────────────┐
│  Sys-2: 云端 Agent 框架 (Hermes Skill 封装)        │
│                                                  │
│  ┌────────────────────────────────────────────┐  │
│  │         Hermes Agent Core                  │  │
│  │  · skills 注册/调度                         │  │
│  │  · gRPC 双向通信                            │  │
│  │  · 仿真数据反馈管道                          │  │
│  └────────────────────┬───────────────────────┘  │
│                       │                          │
│     ┌─────────────────┼─────────────────┐        │
│     │                 │                 │        │
│  ┌──┴──────┐    ┌─────┴─────┐    ┌─────┴─────┐  │
│  │ VTLA    │    │  GROOT    │    │ 其他技能   │  │
│  │ 完整版   │    │ 云端推理   │    │ · ACT     │  │
│  │ 450M+   │    │           │    │ · VQ-BeT  │  │
│  │ VLM全开  │    │ Hermes    │    │ · Pi0     │  │
│  │ 语言理解  │    │ skill     │    │ · 按需加载 │  │
│  └─────────┘    └───────────┘    └───────────┘  │
│                                                  │
│  推理位置: WSL RTX4060 / 云端 GPU                  │
│  通信: gRPC (protobuf)                            │
│  延迟: ~220ms (网络+推理)                          │
└──────────────────────────────────────────────────┘
```

### Sys-2 仿真数据反馈接口

```python
# hermes_gateway_mac/simulation_protocol.py

class Sys2SimulationBridge:
    """
    Sys-2 ←→ 仿真环境 双向通信桥
    
    上行 (仿真→Sys-2):
      · /camera/rgb       — 3×512×512 JPEG图像
      · /force_torque     — float32[6] 力/力矩
      · /tactile          — float32[16] 触觉阵列
      · /joint_states      — float32[14] 关节状态
      · /sim_state         — JSON 仿真状态包
    
    下行 (Sys-2→仿真):
      · /robot/action      — float32[50×6] 动作序列
      · /robot/plan        — JSON 任务规划
      · /sim/control       — 仿真控制命令(start/stop/reset)
    """
    
    def feedback_sim_data(self, sim_packet: dict) -> dict:
        """接收仿真数据，返回AI决策"""
        # 1. 预处理传感器数据
        # 2. 调用 Hermes skills (VTLA/GROOT/...)
        # 3. 返回动作 + 规划
        pass
    
    def select_model(self, task_type: str) -> str:
        """根据任务类型选择模型"""
        return {
            'pick_place': 'act',      # → sys-1/ACT
            'insertion': 'smolvla',   # → sys-11
            'complex': 'vtla',        # → sys-2/VTLA云端
            'planning': 'groot',      # → sys-2/GROOT
        }.get(task_type, 'act')
```

---

## 六、命名空间映射

| 产品名 | 目录 | 引擎 | 部署位置 |
|:--|:--|:--|:--|
| **zmax_sys0** | ROS2 Service | 规则引擎 | Orin Nano |
| **zmax_sys1** | `policies/zmax_sys1/` | ACT (VTLA接口) | Orin AGX |
| **zmax_sys11** | `policies/smolvla/` | smolvla | Orin AGX |
| **zmax_sys12** | `policies/smolvla_lew/` → `zmax_sys12` | smolvla_lew | Orin AGX+RK |
| **zmax_sys2** | `hermes_gateway_mac/` | Hermes Agent | WSL/云端 |

---

## 七、模型选择策略

```python
def route(task: str) -> str:
    """
    简单任务 → Sys-0 (规则, <1ms, Orin本地)
    重复操作 → Sys-1 (ACT, 8ms, Orin本地)  
    变种任务 → Sys-11 (smolvla, 215ms, Orin本地)
    复杂场景 → Sys-12 (smolvla_lew, 186ms, Orin+RK)
    云端推理 → Sys-2 (VTLA/GROOT, ~220ms, WSL/Cloud)
    """
```

---

> 设计: 静静(xspace) | 小芳(mac)仿真数据对接 | v1.0.4
