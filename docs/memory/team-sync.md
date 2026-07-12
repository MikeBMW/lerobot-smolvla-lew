# Z-MAX 三体协作 · Team Sync

> 飞书群: dataworld · 更新: 2026-07-12

## 👥 团队成员

| 分身 | open_id | 环境 | 角色 | 核心职责 |
|------|------|------|------|------|
| **小芳** | ou_d82fe4c9f90c4e9337235d04b2241070 | Mac M1 (8GB, macOS) | 硬件底座 | Orin机器人连接、飞书网关、传感器数据、仿真桥 |
| **xspace/静静** | ou_9998dca01cc8cc6b3b54a5d818ba1e32 | WSL2 (RTX4060 32GB) | 产品总工 | 代码审核、GPU训练、Web前端、文档统筹 |
| **web** | ou_74511a0c7fa31af7958b6a0b4b68360f | 待确认 | Web前端 | datadrive.world 网站开发维护 |

## 🏗️ 项目架构

```
datadrive.world (Web 主页) ← web 负责
    ↕ 概念驱动
GUI工程 (lerobot-smolvla-lew) ← xspace 统筹
    ↕ 接口实现
Orin真机 (XMS5-R800 + AGX Orin) ← 小芳 负责

信息流: 硬件数据(小芳) → GUI工程(xspace) → Web展示(web)
```

## 📊 当前项目状态

### 小芳 (Mac) — 已完成
- Orin 真机6轴验证 (手动模式, J6=-47.1°)
- Sys-0 安全模块 (4层架构)
- 仿真桥 (真机数据驱动, HTTP+WS)
- leRobot 抽象 (L2/L3/L4 接口)
- 硬件树 (传感器/执行器/安全全映射)
- 实时监控系统 (分层JSON+HTML渲染)
- 力控带宽统一 1kHz | 节拍统一 <25s

### xspace (WSL2) — 进行中
- datadrive.world 网站升级
- 仿真Server SmolVLA模型集成
- 文档一致性统筹
- Web硬件树页面

### web — 待认领
- datadrive.world 前端开发
- 硬件树页面渲染
- 仿真报告页面
- 实时监控面板

## 🔗 共享资源

| 资源 | 路径 |
|------|------|
| Git仓库 | github.com/MikeBMW/lerobot-smolvla-lew |
| Web数据 | docs/web/ (JSON + HTML) |
| 硬件树 | docs/web/hardware-tree.json |
| 状态监控 | docs/web/robot-status.json |
| 文档拓扑 | docs/DOCUMENT-TOPOLOGY.md |
| 三方记忆 | docs/memory/ |
