# 静界科技 · Z-MAX 三体协作

> 公司: **静界科技 (JingJie Tech)**  
> 飞书群: dataworld · 2026-07-12

## 👥 成员

| 分身 | 角色 | 环境 | 仓库 | 职责 |
|------|------|------|------|------|
| **xspace/静静** | 🏗️ 总工程师 | WSL2 RTX4060 32GB | `lerobot-smolvla-lew` **main分支** | 架构方案、代码审核、产品统筹、GUI工程管理者 |
| **web** | 🎨 前端+☁️训练 | RTX4090 云端 | `zmax-website` | 网站设计维护、云端模型训练 |
| **小芳** | 🔧 硬件+端侧 | Mac M1 8GB | `lerobot-smolvla-lew` **mac分支** | Orin机器人、传感器、仿真、端侧部署 |

## 🔗 仓库

| 仓库 | 管理者 | 分支策略 |
|------|:---:|------|
| `MikeBMW/lerobot-smolvla-lew` (GUI) | xspace(main守护) + 小芳(mac开发) | mac→PR→xspace审核→main |
| `MikeBMW/zmax-website` (Web) | **web** | 直接维护 |

## 🧠 互相记忆规则

三人可以随时读取对方的记忆档案，按需同步：
- `docs/memory/hermes-xiaofang.md` — 小芳记忆
- `docs/memory/hermes-xspace.md` — xspace记忆  
- `docs/memory/shared-memory.md` — 共享记忆
- `docs/memory/team-sync.md` — 本文件

任何更新→git commit→push→通知对方 pull

## 📊 分工

```
xspace (总工)
  ├── 架构设计 → web (前端+云端)
  │               ├── RTX4090 训练 SmolVLA/ACT
  │               └── zmax-website 维护
  └── 架构设计 → 小芳 (端侧)
                  ├── Orin + 珞石 XMS5-R800
                  ├── 传感器采集 (相机/力/触觉)
                  ├── 仿真桥 + 安全系统
                  └── leRobot 抽象层
```
