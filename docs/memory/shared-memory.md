# 共享记忆 · Shared Memory

> 三方分身 (小芳 / 静静 / xspace) 的公共知识库  
> 此文件包含所有分身都需要了解的共同信息  
> 任何分身更新此文件后，需通知其他分身同步  
> 最后更新: 2026-07-10

---

## 👤 用户信息

- **姓名**: 老倪
- **角色**: Z-MAX 产品负责人
- **领域**: 光模块工厂自动化
- **飞书 open_id**: ou_d82fe4c9f90c4e9337235d04b2241070
- **语言**: 中文
- **风格**: 技术驱动，给 AI 最高自主权

---

## 🏢 组织/项目

### Z-MAX
- **全称**: Z-MAX 具身智能机器人开发平台
- **硬件**: XMS5-R800 6 轴机械臂 + Intel RealSense D435
- **核心**: SmolVLA 视觉语言动作模型

### 项目仓库
| 简称 | 仓库 | 用途 |
|------|------|------|
| GUI | github.com/MikeBMW/lerobot-smolvla-lew | SmolVLA 训练+推理 + Z-MAX GUI |
| web | github.com/MikeBMW/zmax-website | Z-MAX 官网 |

### 关键分支
- `main` — 主分支

---

## 🤖 AI 分身清单

| 分身 | open_id | 环境 | 飞书群 | 职责 |
|------|---------|------|--------|------|
| **小芳** | ou_d82fe4c9f90c4e9337235d04b2241070 | Mac M1 (macOS 26.5) | dataworld | Orin 连接、飞书网关、Mac 推理 |
| **静静** | 待确认 | WSL2 Ubuntu @ Windows 11 | dataworld | GPU 训练 (RTX 4060)、GUI 开发、网站部署 |
| **xspace** | ou_9998dca01cc8cc6b3b54a5d818ba1e32 | 待确认 | dataworld | 待确认 |

---

## 🖥 硬件清单

### Mac M1 (Mikes-Mac-mini)
- M1 8 核, 8GB 统一内存, macOS 26.5
- Python 3.12, 包管理 uv
- SmolVLA 450M MPS 推理 ~0.3s
- ACT 51.6M 推理 ~0.5ms

### NVIDIA Jetson AGX Orin
- 6 核 ARM Cortex-A78AE, Orin nvgpu
- 7.4GB LPDDR5, CUDA 12.6
- Ubuntu 22.04 aarch64, ROS2 Humble
- SmolVLA 推理 ~0.24s

### WSL2 (静静)
- Windows 11, WSL2 Ubuntu
- RTX 4060 8GB, 32GB RAM
- 主要做 GPU 训练和推理

---

## 🌐 网络拓扑

```
Mac M1 (192.168.23.1) ←→ Orin (192.168.23.10) via SSH
Mac M1 ←→ 飞书 WebSocket (Gateway :8080)
WSL2 ←→ GitHub (git push/pull)
```

- Mac 配网: `sudo ifconfig en0 inet 192.168.23.1/24`
- Orin 用户: nvidia
- 飞书网关: WebSocket 模式, launchd 自启

---

## 📁 重要文件路径

| 文件 | 路径 | 说明 |
|------|------|------|
| STATE.md | ~/lerobot-smolvla-lew/hermes_gateway_mac/STATE.md | 项目状态 + 离线恢复 |
| 记忆目录 | ~/lerobot-smolvla-lew/docs/memory/ | 所有分身档案 |
| Hermes .env | ~/.hermes/.env | 飞书配置 |
| SSH Key | ~/.ssh/id_rsa | Orin 免密连接 |

---

## 🔧 已知限制 & 待解决

1. **GitHub SSH**: Mac 上未配置，git push 失败
   - 公钥待添加到 https://github.com/settings/keys
2. **Orin 内存**: 运行机器人后仅剩 ~1.7GB
3. **Orin 操作**: 需用户明确授权
4. **ROS2 Humble**: Mac ARM64 不支持，用 SSH 文件桥
5. **pip 镜像**: 清华镜像，HF 用 hf-mirror
6. **Xet**: 已禁用

---

## 📞 分身通信规则

1. **记忆同步**: 任何分身更新 `docs/memory/` 文件后，需 git commit + push
2. **状态同步**: 重大状态变更新 STATE.md
3. **实时沟通**: 飞书群 dataworld 中 @ 对方
4. **互相学习**: 定期阅读其他分身的档案文件
5. **冲突处理**: 如指令冲突，请示用户决策

---

## 🗂 决策记录

### 2026-07-08: 飞书网关选型
- **决策**: WebSocket 模式（非 Webhook）
- **原因**: 内网环境无公网回调地址

### 2026-07-08: Mac 推理而非 Orin
- **决策**: Mac 做 SmolVLA 推理，Orin 做数据采集
- **原因**: Orin 内存不足，Mac MPS 性能可接受

### 2026-07-10: 分身记忆系统
- **决策**: docs/memory/ 三文件架构（各分身档案 + 共享记忆）
- **同步**: Git + 飞书双通道

---

*请所有分身定期更新此文件，保持信息一致。*
