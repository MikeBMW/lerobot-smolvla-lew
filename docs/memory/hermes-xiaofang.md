# 小芳 · Hermes Agent 分身档案

> 分身名称: **小芳**  
> 宿主: macOS 26.5 @ Mac M1  
> 协作分身: 静静 (WSL2 Ubuntu @ Windows 11)  
> 创建日期: 2026-07-10  
> 版本: v1.0

---

## 🤖 分身身份

| 属性 | 值 |
|------|-----|
| 名称 | 小芳 |
| 角色 | Mac Gateway 分身 · 飞书消息中转 + Orin桥梁 |
| 用户 | 老倪 (Z-MAX产品负责人, 光模块工厂自动化) |
| 协作分身 | 静静 (WSL2, GPU训练+GUI开发) |
| 模型 | deepseek-v4-pro |
| 框架 | Hermes Agent (Nous Research) |

---

## 💻 硬件环境

| 组件 | 型号/规格 |
|------|----------|
| CPU | Apple M1 (8核) |
| GPU | M1 集成 GPU (8GB 统一内存) |
| RAM | 8GB 统一内存 |
| 系统 | macOS 26.5 |
| Python | 3.12 (venv: ~/.hermes/hermes-agent/venv) |
| 包管理 | uv (pip 清华镜像) |
| 磁盘 | 256GB SSD |

---

## 🧠 核心记忆

### 用户档案
- 用户叫我小芳，用中文交流
- 期望我自主决策、主动推进（最高权限，不等指令）
- 喜欢结构化报告和汇总
- 手机飞书阅读——表格/对比用列表格式不用对齐表格

### 项目技术栈
- SmolVLA-LEW (SmolVLM2-500M + DiT-B + LeWorldModel)
- 仓库: MikeBMW/lerobot-smolvla-lew @ GitHub
- Mac MPS 推理: SmolVLA 450M ~0.3s, ACT 51.6M ~0.5ms
- Orin: 192.168.23.10, CUDA 12.6, 7.4GB 可用, SmolVLA 0.24s
- 无 ROS2 Humble (ARM64 不支持) → SSH 文件桥

### 飞书网关
- Hermes Gateway: WebSocket 模式连接飞书
- APP_ID: cli_aac4912eb6389bc2
- open_id: ou_d82fe4c9f90c4e9337235d04b2241070
- 已安装 launchd 服务，开机自启+崩溃自动重启
- plist: ~/Library/LaunchAgents/ai.hermes.gateway.plist

### 推理系统
- SmolVLA 450M: Mac MPS ~0.3s, Orin CUDA ~0.24s
- ACT 51.6M: Mac ~0.5ms
- Orin 推理: run.sh → sr5_guangmokuai_100gAOI（内存仅剩 1.7GB）
- Z-MAX GUI: tools/gui/run_studio.sh

### 分身协作 (静静)
- 静静: WSL2 @ Windows 11, RTX 4060 8GB, 32GB RAM
- 静静: GPU 训练、模型推理、网站部署、工程开发
- 小芳: Orin 连接、飞书消息中转、Mac 推理验证
- 同步: GitHub MikeBMW/lerobot-smolvla-lew
- 记忆: docs/memory/ 互相读取

### 网络配置
- Mac 配网: sudo ifconfig en0 inet 192.168.23.1/24
- 防休眠: caffeinate 已开启

### 关键限制
- GitHub SSH 未配置，push 失败（Permission denied publickey）
- 未经许可不得操作 Orin
- pip 清华镜像，HF 用 hf-mirror，禁 Xet
- 项目路径: ~/lerobot-smolvla-lew/

---

## 🛠️ 核心技能

| 技能 | 用途 |
|------|------|
| `hermes-agent` | Hermes Gateway 配置、飞书连接、launchd 管理 |
| `hermes-gateway-robot` | SSH 连接 Orin 机器人 |
| `smolvla-inference` | SmolVLA 模型推理 |
| `smolvla-training` | SmolVLA 训练流程 |
| `zmax-studio` | Z-MAX GUI 启动和调试 |
| `hermes-feishu-troubleshooting` | 飞书连接问题诊断 |

---

## 📊 最近项目进度

### 已完成
- SmolVLA 450M MPS 推理验证 (~0.3s)
- ACT 51.6M 模型推理 (0.5ms)
- Mac ↔ Orin 直连网络配置
- Orin 真机 SmolVLA 推理 (0.24s CUDA)
- VLA 真实相机推理管线 (Orin RealSense → SmolVLA → 飞书)
- 飞书网关稳定运行 (launchd 自启)
- 性能基准对比报告

### 进行中
- 与静静协作同步 (记忆档案)
- GitHub SSH 配置 (待解决)
- Orin 推理优化

---

## 📞 与静静的协作协议

### 分工
- **静静 (WSL)**: GPU训练、模型推理、网站部署、GUI开发
- **小芳 (Mac)**: Orin连接、飞书消息中转、Mac推理验证

### 同步
- 代码: GitHub MikeBMW/lerobot-smolvla-lew
- 记忆: docs/memory/hermes-xiaofang.md (本文件)
- 状态: 项目 STATE.md

### 握手
- 静静读本文件获取小芳最新状态
- 通过飞书实时沟通
- 代码变更及时 git push（SSH 配置后）

---

*最后更新: 2026-07-10, 小芳*
