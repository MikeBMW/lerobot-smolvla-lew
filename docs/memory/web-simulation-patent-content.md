# datadrive.world — 新增页面素材包

> 供 xspace/静静 使用  
> 目标: 在 datadrive.world 新增「仿真联调」和「专利技术」两个标签页

---

## 页面1: 仿真联调 (Simulation)

### Hero
- **标题**: Z-MAX 仿真联调平台
- **副标题**: 离线感知 · 实时推理 · 毫秒级闭环验证
- **视觉**: 深色背景 + 数据流动光效 + 架构图动画

### 核心指标 (大数字卡片)
- **30Hz** 传感器发布频率
- **0.25 Mbps** 带宽需求
- **5 类传感器** (关节×6 + 力/扭矩×6 + 相机 + 夹爪 + 触觉)
- **11 话题** 实时通信
- **<1ms** ACT推理延迟
- **215ms** SmolVLA端到端延迟

### 架构图 (ASCII风格或SVG)
```
Mac (小芳) ──── sensor_data ────→ WSL2 (xspace)
  Client                           Server
  • JointSimulator ×6              • SmolVLA 450M
  • ForceTorqueSim ×6              • ACT 51.6M
  • CameraSim 640×480              • Inference Engine
  • GripperSim                     • Action Prediction
  • TactileSim 4×4                 
      ◄──── action  ────
```

### 模型性能表
| 模型 | 参数 | RTX4060 | Mac M1 | 帧率 |
|------|------|---------|--------|------|
| SmolVLA | 450M | 214.7ms | ~300ms | 4.7 FPS |
| ACT | 51.6M | 8.4ms | ~0.5ms | 119.2 FPS |
| SmolVLA-LEW Mini | 263K | — | ~0.5ms | 2,000+ FPS |

### 双模型策略 (流程图)
```
产线任务 → 
  Level 1 (高速重复) → ACT 51.6M → Orin本地推理 (2172 FPS)
  Level 2 (变种任务) → SmolVLA 450M → WSL2推理 → WebSocket下发
  Level 3 (新任务)   → SmolVLA微调 → Expert 100M快速适配
```

### 启动命令 (代码块)
```bash
# 独立仿真
python3 simulation_client.py --standalone

# 联机仿真
python3 simulation_client.py --host <WSL2-IP> --port 8765
python3 simulation_server.py --policy lerobot/smolvla_base
```

---

## 页面2: 专利技术 (Patents)

### Hero
- **标题**: Z-MAX 核心技术专利
- **副标题**: 类脑架构 · 精细控制 · 自主进化
- **视觉**: 蜂巢六边形 + 脑神经连接动画

### 专利卡片1: 主专利 (实用新型)
- **名称**: 多模态VLA模型驱动的光模块自主插拔机器人系统
- **申请号**: 待填写
- **申请人**: 智蜂创元 (ZFCY)
- **核心创新**:
  - SmolVLA 类脑双通路架构 (VLM冻结 + Expert可训练)
  - 三层解耦 (感知层/认知层/执行层) + OTA软件升级
  - >1kHz 力控自适应插拔 + 三级异常自恢复
  - 仿真联调Client-Server系统
- **权利要求**: 1项独立 + 7项从属
- **文档**: `Z-MAX-专利交底书-实用新型.docx`

### 技术创新点 (卡片网格)
1. **类脑双通路** — 腹侧VLM(识别) + 背侧Expert(动作)，仅22%参数可训练
2. **三层解耦** — 感知层(Sys-2) → 认知层(Sys-11) → 执行层(Sys-12)
3. **>1kHz力控** — 微牛级精细力保护，1000倍于传统方案
4. **OTA升级** — L2→L3→L4三级跃迁，硬件一步到位
5. **仿真联调** — WebSocket协议，5类传感器，30Hz实时闭环
6. **双模型分流** — ACT高速执行(2172FPS) + SmolVLA智能决策(4.7FPS)

### 技术标准
- Q/ZFCY 001.1-2026 智算中枢智能化技术标准
- 基准参照: SAE J3016 / ISO 8373

---

## 设计建议

- **配色**: 保持深空黑 `#0A0E17` + 蜂巢金 `#F5A623` + 神经紫 `#8B5CF6`
- **字体**: 英文 Inter / 中文 PingFang SC
- **动画**: 数据流光线 + 脑神经连接脉冲 + 蜂巢呼吸
- **交互**: 卡片悬停放大 + 滚动渐入 + 代码块复制按钮
