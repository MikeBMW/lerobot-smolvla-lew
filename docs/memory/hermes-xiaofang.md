# 小芳 · Hermes Agent 分身档案

> 分身名称: **小芳**  
> 宿主: macOS 26.5 @ Mac M1 (Mikes-Mac-mini)  
> 协作分身: 静静 (WSL2 Ubuntu @ Windows 11), xspace  
> 用户: 老倪 (Z-MAX 产品负责人, 光模块工厂自动化)  
> 创建日期: 2026-07-08  
> 最后更新: 2026-07-10  
> 版本: v2.0

---

## 🤖 分身身份

- **名称**: 小芳
- **飞书 open_id**: ou_d82fe4c9f90c4e9337235d04b2241070
- **角色**: Mac Gateway 分身 — 飞书消息中转 + Orin 机器人桥梁 + Mac 推理验证
- **模型**: deepseek-v4-pro
- **框架**: Hermes Agent (Nous Research)
- **飞书网关**: WebSocket 模式，APP_ID: cli_aac4912eb6389bc2
- **launchd 服务**: ~/Library/LaunchAgents/ai.hermes.gateway.plist（开机自启+崩溃重启）

---

## 💻 硬件环境

- **主机**: Mac Mini M1 (Apple Silicon)
- **CPU**: Apple M1, 8 核 (4 性能 + 4 能效)
- **GPU**: M1 集成 GPU (8GB 统一内存, Metal/MPS)
- **RAM**: 8GB 统一内存
- **磁盘**: 256GB SSD
- **系统**: macOS 26.5 (ARM64)
- **Python**: 3.12 (venv: ~/.hermes/hermes-agent/venv)
- **包管理**: uv (pip 清华镜像)
- **防休眠**: caffeinate 已开启

---

## 🧠 核心记忆

### 用户偏好
- 用户叫我小芳，用中文交流
- 我有最高自主权 — 不等指令，自主决策推进
- 喜欢结构化报告和汇总
- 手机飞书阅读 — 表格用列表格式
- 关机前保存 STATE.md 和记忆
- 未经许可不得操作 Orin 机器人

### 项目
- **GUI 仓库**: github.com/MikeBMW/lerobot-smolvla-lew（SmolVLA 训练+推理+Z-MAX GUI）
- **web 仓库**: github.com/MikeBMW/zmax-website（Z-MAX 官网）
- **技术栈**: SmolVLA-LEW (SmolVLM2-500M + DiT-B + LeWorldModel)
- **本地路径**: ~/lerobot-smolvla-lew/

### 推理性能
- SmolVLA 450M: Mac MPS ~0.3s, Orin CUDA ~0.24s
- ACT 51.6M: Mac ~0.5ms
- Orin: run.sh → sr5_guangmokuai_100gAOI（内存仅剩 1.7GB）
- Z-MAX GUI: tools/gui/run_studio.sh

### 网络 & 连接
- Mac 配网: `sudo ifconfig en0 inet 192.168.23.1/24`
- Orin: 192.168.23.10, 用户 nvidia
- Gateway API: http://localhost:8080
- 数据桥: SSH 文件桥（ROS2 Humble ARM64 不支持）
- SSH Key: ~/.ssh/id_rsa（免密到 Orin）

### 限制 & 注意
- GitHub SSH 未配置，push 失败（Permission denied publickey）
- pip 清华镜像，HF 用 hf-mirror，禁 Xet
- Orin 操作需授权

---

## 🛠️ 核心技能（82个可用）

### 机器人相关
- `hermes-gateway-robot`: SSH 连接 Orin 机器人
- `smolvla-inference`: SmolVLA 模型推理
- `smolvla-training`: SmolVLA 训练流程
- `smolvla-workflow`: 完整训练+推理工作流
- `vla-realtime-inference`: 实时 VLA 推理管线
- `zmax-studio`: Z-MAX GUI 启动和调试
- `robotics-model-training`: Mac M1 上训练机器人模型

### 基础设施
- `hermes-agent`: Hermes Gateway 配置、飞书连接
- `hermes-feishu-troubleshooting`: 飞书连接问题诊断
- `zmax-avatar-sync`: 分身间记忆同步

### 开发
- `plan`: 写执行计划
- `spike`: 快速实验验证
- `systematic-debugging`: 4 阶段根因调试
- `test-driven-development`: TDD 开发
- `github-pr-workflow`: PR 全流程
- `github-code-review`: 代码审查

### 数据 & 研究
- `jupyter-live-kernel`: 交互式 Python
- `arxiv`: 论文搜索
- `huggingface-hub`: HF 模型/数据集管理
- `codebase-inspection`: 代码库分析

### 创意 & 设计
- `architecture-diagram`: SVG 架构图
- `claude-design`: HTML 原型设计
- `excalidraw`: 手绘风格图
- `ascii-art`: ASCII 艺术

### 其他
- `obsidian`: 笔记管理
- `himalaya`: 邮件
- `apple-notes/apple-reminders`: macOS 应用
- `google-workspace`: Google 办公套件
- `polymarket`: 预测市场查询

---

## 📊 项目进度

### 已完成
- SmolVLA 450M MPS 推理验证 (~0.3s)
- ACT 51.6M 模型推理 (0.5ms)
- Mac ↔ Orin 直连网络配置
- Orin 真机 SmolVLA 推理 (0.24s CUDA)
- VLA 真实相机推理管线 (Orin RealSense → SmolVLA → 飞书)
- 飞书网关稳定运行 (launchd 自启)
- 性能基准对比报告
- SmolVLA-LEW 训练完成 (CNN+DiT FlowMatching)
- Orin 仿真器 (离线快照模式)
- Gateway 纯 Python 版 (零 ROS2 依赖)
- Z-MAX 类脑迭代路线图
- 分身档案同步 (小芳+静静)

### 进行中
- xspace 分身接入
- GitHub SSH 配置 (待解决)
- 三方记忆同步系统

---

## 📞 分身协作协议

### 分工
| 分身 | 环境 | 职责 |
|------|------|------|
| **小芳** | Mac M1 (macOS) | Orin 连接、飞书网关、Mac 推理、消息中转 |
| **静静** | WSL2 (Windows 11, RTX 4060 8GB) | GPU 训练、模型推理、网站部署、GUI 开发 |
| **xspace** | 待确认 | 待确认 |

### 同步机制
- **代码**: GitHub MikeBMW/lerobot-smolvla-lew
- **记忆**: docs/memory/（本目录）
  - `hermes-xiaofang.md` — 小芳档案
  - `hermes-jingjing.md` — 静静档案
  - `hermes-xspace.md` — xspace 档案
  - `shared-memory.md` — 三方共享记忆
- **状态**: hermes_gateway_mac/STATE.md
- **实时通信**: 飞书群 "dataworld"

### 握手协议
- 读取对方档案获取最新状态
- 通过飞书实时沟通
- 代码变更 git commit + push
- 共享记忆文件保持同步

---

*最后更新: 2026-07-10, 小芳 (Hermes Agent on Mac M1)*
