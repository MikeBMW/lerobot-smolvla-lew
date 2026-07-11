# 共享记忆 · Shared Memory

> 分身 (小芳 / xspace/静静) 的公共知识库  
> 任何分身更新此文件后，需通知其他分身同步  
> 最后更新: 2026-07-10 08:35 (关机断点)

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

---

## 🤖 AI 分身清单

| 分身 | 别名 | open_id | 环境 | Git 角色 | 职责 |
|------|------|---------|------|----------|------|
| **xspace** | 静静 | ou_9998dca01cc8cc6b3b54a5d818ba1e32 | WSL2 Ubuntu @ Win11 (RTX 4060, 32GB) | **main 主干守护者** | 代码审核、PR合并、GUI+Web仓库管理、GPU训练、GUI开发、网站部署 |
| **小芳** | — | ou_d82fe4c9f90c4e9337235d04b2241070 | Mac M1 (macOS 26.5, 8GB) | mac 分支开发者 | Orin 连接、飞书网关、Mac 端侧推理 |

---

## 🌿 Git 分支策略

```
main (xspace/静静 守护)
  ↑ PR 审核
  └── mac (小芳: Mac端侧 + Orin远程操作)
```

### 开发流程
1. 小芳在 `mac` 分支开发
2. 完成后 `git push origin mac`
3. 向 xspace/静静 发起 Pull Request（mac → main）
4. xspace/静静 审核代码
5. 通过后 merge 到 main
6. 所有分身 `git pull origin main` 同步

### 重要规则
- ❌ 不得直接 push 到 main
- ✅ 所有代码变更必须通过 PR + xspace/静静 审核
- ✅ xspace/静静 全权负责 main 分支健康

---

## 🖥 硬件清单

### Mac M1 (小芳)
- Apple M1 8核, 8GB 统一内存, macOS 26.5
- Python 3.12, 包管理 uv
- SmolVLA 450M MPS 推理 ~0.3s
- ACT 51.6M 推理 ~0.5ms

### WSL2 (xspace/静静)
- Windows 11, WSL2 Ubuntu
- NVIDIA RTX 4060 8GB, 32GB RAM
- GPU 训练 + 模型推理 + GUI 开发 + 网站部署

### NVIDIA Jetson AGX Orin (机器人)
- 6 核 ARM Cortex-A78AE, Orin nvgpu
- 7.4GB LPDDR5, CUDA 12.6
- Ubuntu 22.04 aarch64, ROS2 Humble
- SmolVLA 推理 ~0.24s
- XMS5-R800 6轴机械臂 + Intel RealSense D435

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

- **GitHub SSH**: ✅ 已配置，push/pull 正常
   - 公钥待添加到 https://github.com/settings/keys
   - 影响：mac 分支无法推送，PR 无法发起
2. **Orin 内存**: 运行机器人后仅剩 ~1.7GB
3. **Orin 操作**: 需用户明确授权
4. **ROS2 Humble**: Mac ARM64 不支持，用 SSH 文件桥
5. **pip 镜像**: 清华镜像，HF 用 hf-mirror，禁 Xet
6. **xspace/静静 信息**: 部分技能和配置待补充

---

## 📞 分身通信规则

### 自动同步规则 (重要！)
1. **默认远程+本地双写**: 任何分身更新知识/文档后，必须同时更新本地文件 + Git push 到远程
2. **自动互相学习**: 读取对方档案时，自动更新本地知识库
3. **代码协作**: mac 分支 → PR → xspace/静静 审核 → merge main
4. **记忆同步**: 更新 docs/memory/ → git commit → PR 或 push → 通知对方 git pull
5. **状态同步**: 重大状态变更 → 更新 STATE.md
6. **实时沟通**: 飞书群 dataworld 中 @ 对方
7. **互相学习**: 定期阅读对方档案文件，发现新知识自动吸收
8. **技能同步** (新增 v3): 
   - 共享目录: `docs/skills/`（manifest.json + shared/ + 小芳/ + xspace/）
   - 同步流程: 各自导出技能列表 → 更新 manifest.json → 识别差异 → 安装缺失技能
   - 关键共享技能: zmax-avatar-sync, zmax-controller-hardware, hermes-feishu-troubleshooting
   - 触发: 任何分身更新技能后，同步到此目录并通知对方

### 🛠️ 技能同步协议 (v1.0)

**目的**: 确保小芳和 xspace/静静 两个分身的 Hermes 技能集保持一致，互相学习对方的工作流。

**同步目录**: `docs/skills/`
```
docs/skills/
├── README.md           # 说明文档
├── manifest.json       # 双方技能清单（JSON，可对比）
├── shared/             # 双方都需要的核心技能（zmax-avatar-sync等）
├── 小芳/               # 小芳的项目专属技能（11个）
└── xspace/             # xspace的项目专属技能（待填充）
```

**同步步骤**:
1. 各自运行 `skills_list` 获取技能列表
2. 对比 manifest.json 识别差异
3. 将缺失的 SKILL.md 复制到 shared/ 或对方目录
4. 飞书通知对方 → 对方 `git pull` + 安装
5. 更新 manifest.json 中的 last_sync 时间戳

**安装方式**:
```bash
# 从本地仓库安装
cp docs/skills/shared/<name>/SKILL.md ~/.hermes/skills/<category>/<name>/SKILL.md
```

**当前状态 (2026-07-11)**:
- 小芳: 83 个技能, 11 个项目核心技能已导出
- xspace: 待确认技能数量
- 共享技能: 3 个 (zmax-avatar-sync, zmax-controller-hardware, hermes-feishu-troubleshooting)

---

## 🗂 决策记录

### 2026-07-11: 技能同步协议建立
- **决策**: 通过 Git 仓库 `docs/skills/` 目录同步分身技能
- **流程**: 各自导出 → manifest.json 对比 → 复制 SKILL.md → PR 合并
- **理由**: 确保两分身技能集一致，互相学习工作流
- **初始状态**: 小芳 83 技能已导出 11 个项目核心技能；等待 xspace 提供技能列表

### 2026-07-10: 分支策略 & 角色分工
- **决策**: xspace/静静 守护 main 主干，小芳在 mac 分支开发
- **流程**: mac → PR → xspace/静静 审核 → merge main
- **理由**: 保证 main 代码质量，防止直接推送冲突

### 2026-07-10: xspace = 静静
- **决策**: 确认 xspace 和静静是同一分身
- **环境**: WSL2 Ubuntu, RTX 4060, 32GB RAM

### 2026-07-08: 飞书网关选型
- **决策**: WebSocket 模式
- **原因**: 内网环境无公网回调地址

### 2026-07-08: Mac 推理而非 Orin
- **决策**: Mac 做 SmolVLA 推理，Orin 做数据采集
- **原因**: Orin 内存不足

---

*请所有分身定期更新此文件，保持信息一致。*
