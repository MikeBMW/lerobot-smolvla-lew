# Z-MAX 开发宝典 · Development Bible

> **Z-MAX 多模态动作专家 — 具身智能开发全维度参考手册**
> 
> 版本: v1.0.2 | 编制: 智蜂创元(ZFCY)产品管理部 | 生效: 2026-07-06
> 
> 本文档是 Z-MAX 项目的唯一权威开发宝典，覆盖场景需求、系统设计、软件架构、
> 模型训练、硬件配置、数据管理、GUI操作手册、设计理念、开发经验和版本管理全部维度。

---

## 目录

1. [场景需求](#一场景需求)
2. [系统设计](#二系统设计)
3. [软件架构](#三软件架构)
4. [模型训练](#四模型训练)
5. [硬件配置](#五硬件配置)
6. [数据管理](#六数据管理)
7. [GUI 操作手册](#七gui-操作手册)
8. [设计理念](#八设计理念)
9. [网络与通信](#九网络与通信)
10. [开发经验](#十开发经验)
11. [版本管理](#十一版本管理)

---

## 一、场景需求

### 1.1 产业背景

高速光模块（800G/1.6T）是AI算力基础设施的核心硬件载体。光模块测试与装配环节高度依赖人工：
- 人工插拔力度不可控 → 良率受损
- 换型耗时 → 无法柔性生产
- 密集测试仓 → 难以人工作业

### 1.2 目标场景

| 场景 | 描述 | 精度要求 |
|------|------|---------|
| 固件加载 | 模块插入EVB测试座，触发固件烧录 | ±0.02mm |
| 老化仓上下料 | 将模块放入/取出高温老化仓 | ±0.05mm |
| 模块测试 | 插拔光模块进行电性能/光性能测试 | ±0.02mm |
| AOI检测 | 视觉检测模块外观缺陷 | 像素级 |
| P/F分类 | 根据测试结果自动分拣良品/不良品 | 100%准确 |

### 1.3 核心指标

| 指标 | 目标 | 备注 |
|------|------|------|
| 插拔精度 | ±0.02mm | 满足QSFP-DD/OSFP光模块插座公差 |
| 连续成功率 | >99% | 插拔工序成功率 |
| 关键工序良率 | ≥99.2% | 插拔工序的质量指标，非整体产线良率 |
| 力控带宽 | >10kHz | 关节力矩闭环控制频率 |
| 推理延迟 | <10ms | 端到端VLA推理（视觉→动作） |
| 控制周期 | 1ms | 实时伺服周期 |
| 节拍 | <5s/个 | 单模块处理时间 |
| 连续运行 | 7×24h | 支持换电 |
| ROI回收期 | 14~22月 | 单机替代3名操作工 |

### 1.4 竞品分析

| 维度 | Z-MAX (Z700) | 珞石 ROKAE | 说明 |
|------|-------------|-----------|------|
| 构型 | 轮式双臂 | 固定式单臂 | Z-MAX 移动+操作一体化 |
| 力控带宽 | >10kHz (关节) | <5Hz (外置) | 1000x 优势 |
| 力控精度 | <2N | >10N | 5x 优势 |
| 双臂协同 | 左取料+右插拔 | 不支持 | 并行效率提升 |
| AI引擎 | SmolVLA-LEW (VLM+VLA+世界模型) | 传统编程 | 泛化能力 |
| 部署方式 | 边缘Orin + 云端训练 | 工控机 | 灵活扩展 |

---

## 二、系统设计

### 2.1 产品定义

**Z-MAX 多模态动作专家** 是基于 LeRobot 框架的具身智能系统，面向光模块工厂精细操作场景。

**硬件载体：Z700 轮式双臂机器人**

### 2.2 四层系统架构

```
┌─────────────────────────────────────────────────────────┐
│                   Z-MAX 三层解耦架构                       │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  System 2 (L4 大脑层)                                    │
│  ┌─────────────────────────────────────────────────┐    │
│  │  任务规划 · 场景理解 · VLM推理 · 数据飞轮          │    │
│  │  SmolVLM2-500M + LeWorldModel(15M)               │    │
│  └─────────────────────────────────────────────────┘    │
│                         ↓↑                               │
│  Sys-12 (L3+ 引导系统)                                   │
│  ┌─────────────────────────────────────────────────┐    │
│  │  潜空间压缩 · 跨型号泛化 · 空间感知闭环            │    │
│  │  场景引导 · 认知闭环 · 评估分析                    │    │
│  └─────────────────────────────────────────────────┘    │
│                         ↓↑                               │
│  Sys-11 (L3 动作系统)                                    │
│  ┌─────────────────────────────────────────────────┐    │
│  │  视触觉语言动作模型(VTLA) · 端到端推理             │    │
│  │  SmolVLM2-500M 视觉 + DiT-B 动作头               │    │
│  └─────────────────────────────────────────────────┘    │
│                         ↓↑                               │
│  System 0 (L2 基石层)                                    │
│  ┌─────────────────────────────────────────────────┐    │
│  │  硬件工具箱 · EtherCAT驱动 · HAL抽象层             │    │
│  │  电机控制(1ms) · 相机采集 · 力控闭环(>10kHz)       │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 2.3 技术路线：Phase 0 → Phase 4

| Phase | 等级 | 名称 | 核心突破 | 策略包 |
|-------|------|------|---------|--------|
| **Phase 0** | L2 | 人工编排原子功能 | 产线流程验证 + 数据采集基线 | `zmax_unit_action` |
| **Phase 1** | L3 | 端到端VTLA | 感知→动作端到端 | `zmax_vtla` |
| **Phase 2** | L3+ | 潜空间泛化 | Z潜空间压缩 + 跨型号泛化 + 端侧部署 | `zmax_latent` |
| **Phase 3** | L4 | 精细感知闭环 | 3D空间感知 + 场景引导 + 认知闭环 | `zmax_spatial` |
| **Phase 4** | L4+ | 全域认知 | JEPA世界模型 + 3DGS + 视听融合 | `zmax_optional` |

---

## 三、软件架构

### 3.1 技术栈

| 组件 | 技术选型 | 说明 |
|------|---------|------|
| 基础框架 | LeRobot (HuggingFace) | 机器人学习PyTorch框架 |
| 视觉模型 | SmolVLM2-500M | 轻量级视觉语言模型 |
| 动作模型 | DiT-B (Diffusion Transformer) | 动作生成头 |
| 世界模型 | LeWorldModel (15M参数) | 场景预测+验证 |
| GUI框架 | PyQt5 (暗色主题) | XSpace Studio开发环境 |
| 仿真环境 | Gymnasium + MuJoCo | 强化学习仿真 |
| 数据格式 | LeRobot Dataset (.lrobot) | 支持视频+状态+动作 |
| 依赖管理 | conda (lerobot env) / uv | Python 3.12.13 |
| 版本控制 | Git + GitHub | MikeBMW/lerobot-smolvla-lew |

### 3.2 代码结构

```
lerobot-smolvla-lew/
├── src/lerobot/
│   ├── policies/               # 策略实现
│   │   ├── smolvla_lew/        # ★ SmolVLA-LEW 核心策略
│   │   │   ├── configuration.py   # SmolVLALewConfig
│   │   │   ├── modeling.py        # SmolVLALewPolicy
│   │   │   ├── processor.py       # 数据预处理
│   │   │   └── README.md
│   │   └── zmax_policies/      # Z-MAX 多阶段策略
│   │       ├── phase0_unit_action/
│   │       ├── phase1_zmax_vtla/
│   │       ├── phase2_zmax_latent/
│   │       ├── phase3_zmax_spatial/
│   │       └── phase4_zmax_optional/
│   ├── datasets/               # 数据集处理
│   ├── envs/                   # 环境配置
│   ├── robots/                 # 机器人抽象
│   ├── motors/                 # 电机驱动
│   ├── cameras/                # 相机驱动
│   └── processor/              # 数据管道
├── tools/
│   ├── gui/                    # ★ XSpace Studio GUI
│   │   ├── studio.py              # 主窗口 (4281行)
│   │   ├── training_backend.py    # 训练后台管理
│   │   ├── dataset_viewer.py      # 数据集查看器
│   │   ├── version_sync.py        # 版本同步模块
│   │   └── run_studio.sh          # 启动脚本
│   └── tcp_bridge/             # ★ TCP只读数据桥
│       ├── orin_forwarder.py          # Domain 42 测试转发
│       ├── orin_forwarder_domain23.py # 动态发现全量topic
│       ├── pc_receiver.py             # PC端接收+JSONL记录
│       ├── run_orin.sh               # Orin端启动
│       └── run_pc.sh                 # PC端启动
├── docs/                       # ★ 产品文档
│   ├── HELP-DEVELOPMENT-BIBLE.md   # 本文档 — 开发宝典
│   ├── L1-Z-MAX产品发布-v1.0.0.pptx
│   ├── L2-Z-MAX解决方案-v1.0.1.md
│   ├── L3-技术路线与开发指南-v1.0.0.md
│   ├── VERSION.md
│   ├── README.md
│   └── archive/                # 历史版本
├── ros_pc_ws/                  # ROS2 PC端工作空间
├── ros_orin_ws/                # ROS2 Orin端工作空间
├── scripts/                    # 工具脚本
└── pyproject.toml              # 项目配置 (LeRobot 0.5.2)
```

### 3.3 数据流架构

```
┌─────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────┐
│ 相机阵列 │───→│ SmolVLM2-500M │───→│ DiT-B 动作头  │───→│ 机器人   │
│ (RGB+D) │    │ 视觉编码      │    │ 动作生成      │    │ 执行     │
└─────────┘    └──────┬───────┘    └──────────────┘    └──────────┘
                      │                                       │
                      ▼                                       ▼
              ┌──────────────┐                       ┌──────────────┐
              │ LeWorldModel │←──────────────────────│ 传感器反馈    │
              │ (15M 参数)   │   预测 vs 实际          │ (力/位置)     │
              └──────────────┘                       └──────────────┘
```

### 3.4 ROS2 双栈架构

```
PC (WSL)                          Orin (192.168.23.10)
┌───────────────────┐             ┌─────────────────────────┐
│ ros_pc_ws/        │             │ ros_orin_ws/            │
│ smolvla_grpc_bridge│◄──gRPC──→│ arm_hardware_driver     │
│ (自包含gRPC桥)     │             │ camera_pub / joint_state │
│                   │             │ action_sub              │
│ TCP Bridge (只读)  │───TCP────→│ tcp_bridge (Server)     │
│ pc_receiver.py    │   :8765    │ orin_forwarder_*.py     │
└───────────────────┘             └─────────────────────────┘
```

---

## 四、模型训练

### 4.1 SmolVLA-LEW 架构

```
SmolVLA-LEW = SmolVLM2-500M (视觉编码) + DiT-B (动作生成) + LeWorldModel (验证)
```

| 组件 | 参数量 | 功能 |
|------|--------|------|
| SmolVLM2-500M | 500M | 多模态视觉-语言编码，理解场景+指令 |
| DiT-B | 130M | Diffusion Transformer 动作头，生成精确动作序列 |
| LeWorldModel | 15M | 世界模型，预测动作结果，验证安全性 |

### 4.2 训练环境

| 配置项 | 值 |
|--------|-----|
| Python 环境 | conda lerobot (Python 3.12.13) |
| PyTorch | 2.7.1+cu118 |
| CUDA | 11.8 |
| GPU | NVIDIA (训练用) / AGX Orin (推理用) |
| 启动命令 | `cd ~/lerobot-smolvla-lew && bash tools/gui/run_studio.sh` |

### 4.3 训练配置

```python
# SmolVLALewConfig 核心参数
@dataclass
class SmolVLALewConfig:
    # 视觉编码
    vision_encoder: str = "SmolVLM2-500M"
    image_size: int = 224
    num_frames: int = 4           # 输入帧数
    
    # 动作生成
    action_horizon: int = 16      # 预测步数
    action_dim: int = 12          # 动作维度
    diffusion_steps: int = 20     # 扩散步数
    
    # 世界模型
    world_model_dim: int = 256    # 潜在空间维度
    wm_prediction_horizon: int = 32
    
    # 训练
    batch_size: int = 64
    learning_rate: float = 1e-4
    max_epochs: int = 100
```

### 4.4 训练流程

1. **数据准备**: 通过 Phase 0 人工编排采集演示数据 → `.lrobot` 格式
2. **数据预处理**: `processor.py` 进行图像增强、归一化、帧采样
3. **训练启动**: GUI训练控制台 → `lerobot-train` CLI → SmolVLALewPolicy
4. **评估验证**: LeWorldModel 验证 → 成功率分析 → 动作回放
5. **部署推理**: ONNX/TRT 优化 → AGX Orin 边缘部署

---

## 五、硬件配置

### 5.1 Z700 轮式双臂机器人

| 组件 | 规格 | 说明 |
|------|------|------|
| 底盘 | 全向轮式 | 稳定灵活，产线间机动 |
| 机械臂 | 双臂力控 | 关节力控闭环 >10kHz |
| 左臂末端 | 集成夹爪+吸盘+腕部视觉 | 取料/扫码/放置 |
| 右臂末端 | 电动夹爪+力传感器+腕部视觉 | 插拔/AOI/分类 |
| 头部视觉 | 3D深度相机 Gemini 335L | 全局场景感知 |
| 鱼眼相机 | 4个 | 360°环绕感知 |
| 激光雷达 | 对角双雷达 | 导航+避障 |
| TOF传感器 | 4个 | 近距离避障 |
| 算力平台 | NVIDIA AGX Orin | 边缘AI推理 |
| 通讯 | WiFi + 以太网 | 产线信号交互 |
| 续航 | 基础4h，快充15min | 换电模式 |
| 安全 | 急停按钮+力控柔顺 | 人机协作安全 |

### 5.2 开发环境

| 组件 | 配置 |
|------|------|
| 开发机 | WSL2 (Ubuntu) @ Windows 10 |
| Python | conda lerobot (3.12.13) |
| GPU | NVIDIA CUDA 11.8 |
| Orin | NVIDIA Jetson AGX Orin @ 192.168.23.10 |
| 连接 | SSH免密 (ED25519) + TCP桥 |

---

## 六、数据管理

### 6.1 数据格式

Z-MAX 使用 LeRobot Dataset 格式 (`.lrobot`)：

```python
# 数据集结构
LeRobotDataset:
    metadata:
        fps: 30
        robot_type: "z700"
        tasks: ["grasp_pick", "insert_evb", "aoi_check"]
    episodes:
        - episode_0:
            frames: [...]
            states: [...]      # 关节角度/力矩
            actions: [...]     # 目标动作
            rewards: [...]     # 任务奖励
            videos: [...]      # H.264编码视频
```

### 6.2 数据飞轮

```
采集 → 训练 → 部署 → 反馈 → 采集
  ↑                         │
  └─────────────────────────┘
  
Phase 0 (人工采集) → Phase 1 (VTLA策略) → Phase 3 (闭环自改进)
```

### 6.3 开源数据集参考

| 数据集 | 来源 | 用途 |
|--------|------|------|
| `lerobot/pusht` | HuggingFace | IL 基准测试 |
| `lerobot/xarm_lift_medium` | HuggingFace | 抓取任务 |
| `lerobot/aloha_sim_insertion` | HuggingFace | 插拔任务参考 |

### 6.4 TCP 数据桥

**架构**: Orin (TCP Server :8765) → PC (TCP Client) — 只读模式，安全监控

**支持的模式**:
- **Domain 42** (测试隔离): `orin_forwarder.py` — 固定订阅 Float32MultiArray + CompressedImage
- **Domain 23** (真机监控): `orin_forwarder_domain23.py` — 动态发现所有topic，通用消息序列化

**当前真机状态** (2026-07-05 实测):
- 20个 ROS2 节点, 49个 topic
- 成功订阅 31个 topic (其余36个需自定义消息包)
- 实时数据: `real_joint_states`, `gripper_pos`, `robot_status`, `tower_light/status`

---

## 七、GUI 操作手册

### 7.1 XSpace Studio 概览

XSpace Studio 是 Z-MAX 的一站式开发环境，暗色主题，9大功能模块。

**启动方式**:
```bash
cd ~/lerobot-smolvla-lew
bash tools/gui/run_studio.sh
```

### 7.2 功能模块

#### 🏠 首页
- 项目概览、KPI指标、模块导航
- 快捷按钮：解决方案文档、PPT汇报、版本同步、同步到GitHub

#### 📊 数据集管理 (System 2 · L4大脑)
- 浏览 HuggingFace LeRobot 数据集
- 下载指定数据集到本地
- 查看数据内容（图像/视频/state）
- 支持 `.lrobot` 格式解析

#### 🏋️ 训练控制台 (Sys-11 · 动作系统)
- SmolVLA-LEW 端到端训练
- 训练参数可视化配置
- 实时训练曲线监控
- 后台调用 `lerobot-train` CLI

#### ✅ 评估分析 (Sys-12 · 引导系统)
- LeWorldModel 验证
- 动作回放分析
- 成功率统计
- 模型对比评估

#### 🔧 硬件工具箱 (System 0 · L2基石)
- 电机控制配置
- 相机参数设置
- 力控闭环参数
- 急停安全配置

#### ⚙️ 配置中心 (Sys-11 + Sys-12)
- SmolVLALewConfig 三层参数可视化编辑
- YAML 配置文件管理
- 训练超参数调优

#### 📈 实时监控 (Sys-11 + Sys-12)
- 训练曲线实时显示
- GPU 状态监控
- 推理延迟追踪
- 力控曲线可视化

#### 🤖 插拔场景 (Z700 · 双臂协同)
- Z700 轮式双臂 VTLA 插拔
- ROI 量化模型
- 力控闭环验证

#### 🔄 版本同步 (LeRobot · 上游管理)
- LeRobot 上游更新检查
- 安全同步（git merge）
- 冲突检测
- 版本状态展示

### 7.3 菜单栏

| 菜单 | 功能 |
|------|------|
| 文件(&F) | 打开项目目录 / GitHub仓库 / 同步代码 / 退出 |
| 视图(&V) | 快速跳转各功能模块 |
| **帮助文档(&H)** | **开发宝典 · L1/L2/L3文档 · 品牌竞品 · 版本管理 · Git指南** |
| 关于(&A) | Z-MAX 版本信息 / LeRobot 官方文档 |

### 7.4 WSL 启动注意事项

- **WSLg DISPLAY 问题**: 如果 GUI 无法启动，确认 Windows 端开启了 X Server
- **启动脚本**: 已内置 `export DISPLAY=:0` 解决 TCP display 连接问题
- **环境**: 优先使用 conda lerobot 环境

---

## 八、设计理念

### 8.1 核心理念：类脑计算 × 具身智能量产

Z-MAX 的终极目标是实现**类脑级别的具身智能**，并通过工业化落地让机器人真正量产。

### 8.2 设计原则

1. **三层解耦**: System 0 (硬件) → Sys-11/12 (动作/引导) → System 2 (大脑)
   - 每一层可独立升级、独立测试、独立部署
   
2. **渐进式智能**: Phase 0 → Phase 4 逐级增强
   - 从人工编排到全自主，每一步都有可交付价值
   
3. **数据驱动**: 数据飞轮闭环
   - 用真实产线数据训练，用世界模型验证，用部署反馈迭代
   
4. **边缘优先**: 推理在 Orin，训练在云端
   - 1ms 控制周期要求边缘推理，<10ms 延迟保证实时性
   
5. **安全第一**: 只读监控 + 力控柔顺 + 急停保护
   - TCP 桥只读模式不会误触真机
   - >10kHz 力控闭环防止意外碰撞

### 8.3 UX 设计理念

- **暗色主题**: 降低长时间操作的眼疲劳（GitHub 风格配色）
- **中文按钮**: 面向国内工程师，不用 emoji 代替文字
- **层级可视化**: 颜色编码区分系统层级
- **一致锚点**: 文档、GUI、版本号三重对齐

---

## 九、网络与通信

### 9.1 WSL ↔ Orin 网络拓扑

```
Windows Host (192.168.23.1/24)
    │
    ├── WSL2 (eth1 → 路由到 192.168.23.10)
    │   ├── SSH 免密 (ED25519)
    │   ├── TCP Bridge Client (:8765)
    │   └── gRPC Bridge (ros_pc_ws)
    │
    └── Orin (192.168.23.10, eth0)
        ├── SSH Server
        ├── TCP Bridge Server (:8765)
        ├── ros_orin_ws (Domain 23 真机 / Domain 42 测试)
        └── 20 ROS2 Nodes, 49 Topics
```

### 9.2 通信方案选择

| 方案 | 适用场景 | 状态 |
|------|---------|------|
| DDS (多播/单播) | 同网络ROS2节点发现 | ❌ WSL不支持 |
| TCP Bridge | 只读监控、数据采集 | ✅ 已部署 |
| gRPC Bridge | 控制指令下发 | 🔧 开发中 |
| SSH | 远程管理 | ✅ 已配置 |

### 9.3 TCP Bridge 使用

**Orin 端启动**:
```bash
ssh nvidia@192.168.23.10
cd ~/lerobot-smolvla-lew/tools/tcp_bridge
bash run_orin.sh
```

**PC 端接收**:
```bash
cd ~/lerobot-smolvla-lew/tools/tcp_bridge
bash run_pc.sh
```

---

## 十、开发经验

### 10.1 已知陷阱与解决方案

| 陷阱 | 现象 | 解决方案 |
|------|------|---------|
| PyQt5 subprocess.PIPE顺序 | Errno 9 | PIPE必须在STDOUT之前 |
| QComboBox下拉黑屏 | 黑色弹窗 | 全局setStyleSheet设置QAbstractItemView |
| f-string CSS花括号 | 解析错误 | 双写 {{}} 转义 |
| QThread GUI操作 | 崩溃 | 用pyqtSignal.emit() |
| 按钮样式泄漏 | background 影响子组件 | 用 background-color |
| WSL DDS发现不通 | 多播回包丢失 | 改用TCP Bridge |
| SSH非交互Python | 输出被吞 | 用 `python3 -c "import m; m.main()"` |
| WSLg DISPLAY连接失败 | Qt xcb连接拒绝 | export DISPLAY=:0 强制Unix socket |
| 磁盘空间不足 | E盘88%使用 | 禁止>100M下载，用完即清理 |
| conda环境冲突 | Python版本不对 | 启动脚本优先conda lerobot环境 |

### 10.2 备份规范

- 改动前先备份: `studio.py.bak.YYYYMMDD_HHMMSS`
- 文档归档: `docs/archive/` 保留所有历史版本
- Git 提交: 每个功能点独立提交

### 10.3 安全红线

- **严禁动真机控制 topic** (Domain 23)
- TCP Bridge 仅做只读订阅
- 任何控制指令需在 Domain 42 测试隔离环境先验证
- 真机急停按钮永远保持可触及状态

### 10.4 工作流

1. **改动前**: 备份 → 理解现有代码 → 制定方案
2. **改动中**: 小步提交 → 即时验证 → 保持简洁
3. **改动后**: 功能测试 → 文档同步 → 版本更新 → Git推送

---

## 十一、版本管理

### 11.1 版本号规范

```
完整版本号 = {LeRobot版本}-zmax.{Z-MAX版本}

示例: 0.5.2-zmax.1.0.2
      │      │     │
      │      │     └─ Z-MAX 自定义版本 (语义化)
      │      └─ 固定标识符
      └─ LeRobot 上游基线版本
```

| 段 | 含义 | 触发条件 |
|----|------|---------|
| **X** (主版本) | 架构变更 | 硬件平台升级、技术路线重大调整 |
| **Y** (次版本) | 功能增加 | 新增Phase、新场景、功能模块 |
| **Z** (修订版) | 错误修正 | 文档勘误、指标修正、bug修复 |

### 11.2 三层文档矩阵

| 层级 | 文件 | 用途 | 读者 |
|------|------|------|------|
| **L1** | `L1-Z-MAX产品发布-v{V}.pptx` | 管理层汇报、投资人路演 | CEO/CTO/投资人 |
| **L2** | `L2-Z-MAX解决方案-v{V}.md` | 客户解决方案 | 客户技术负责人 |
| **L3** | `L3-技术路线与开发指南-v{V}.md` | 研发实施指南 | 研发工程师 |
| **Brand** | `BRAND-品牌注册材料.pptx` | 商标注册、品牌审批 | 法务/品牌部 |
| **Bible** | `HELP-DEVELOPMENT-BIBLE.md` | 开发宝典(本文档) | 全员 |

**版本一致性规则**: L1/L2/L3/Bible 版本号必须保持同步。

### 11.3 一致性锚点

| 锚点 | v1.0.2 当前值 |
|------|--------------|
| 产品名称 | Z-MAX 多模态动作专家 |
| 硬件平台 | Z700 轮式双臂 |
| 插拔精度 | ±0.02mm |
| 成功率 | >99% |
| 关键工序良率 | ≥99.2% |
| 力控带宽 | >10kHz |
| 双臂协同 | 左取料 + 右插拔 |
| 技术路线 | Phase 0(L2) → Phase 1(L3) → Phase 2(L3+) → Phase 3(L4) → Phase 4(L4+) |
| 技术架构 | VLM规划 + VLA执行 + HIL强化学习 + 世界模型 |
| ROI回收期 | 14~22月 |

### 11.4 版本历史

| 版本 | 日期 | 说明 |
|------|------|------|
| v1.0.2 | 2026-07-06 | 基线产品发布：创建开发宝典(HELP-DEVELOPMENT-BIBLE.md)，整合所有维度信息；GUI帮助菜单重构；TCP数据桥集成；版本号全系统对齐 |
| v1.0.1 | 2026-07-04 | 修订：良率承诺精确化为"关键工序良率" |
| v1.0.0 | 2026-07-02 | 首次正式版。Z700硬件、Phase 0-4路线、双臂协同、ROI模型 |

### 11.5 版本发布流程

1. **产品经理确认**: 对齐 L1/L2/L3/Bible 所有一致性锚点
2. **更新 GUI**: `studio.py` 侧边栏标签 + `version_sync.py` zmax_ver 值
3. **更新文档**: `VERSION.md` + `README.md` 版本号和文档矩阵
4. **归档旧版**: 移入 `docs/archive/`
5. **Git 提交**: 
   ```bash
   git add -A
   git commit -m "release: Z-MAX v{X}.{Y}.{Z} — {说明}"
   git push origin main
   ```

### 11.6 关键文件清单

| 文件 | 需要同步的版本号位置 |
|------|-------------------|
| `docs/HELP-DEVELOPMENT-BIBLE.md` | 标题版本号 |
| `docs/VERSION.md` | 当前版本、版本历史表 |
| `docs/README.md` | 当前版本号 |
| `tools/gui/studio.py` | 侧边栏 "解决方案v{VER}" 按钮文本、文档路径 |
| `tools/gui/version_sync.py` | zmax_ver 变量 (第320行) |

---

> **📌 本文档由智蜂创元(ZFCY)产品管理部维护，与 Z-MAX 产品版本同步更新。**
> 
> 最后更新: 2026-07-06 | 当前版本: v1.0.2 | GitHub: https://github.com/MikeBMW/lerobot-smolvla-lew
