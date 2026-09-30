# 静界科技 · Z-MAX 系统分工

> 2026-07-12 · 飞书群 dataworld

## 🎯 系统层分工

| 系统层 | 负责人 | 设备 | 内容 |
|:---:|------|------|------|
| **Sys-0** | 小芳 | Mac M1 / Orin | 安全层 (急停/力控/关节限位/光幕) |
| **Sys-1** | xspace | WSL2 RTX4060 | ACT 51.6M 高速执行底座 |
| **Sys-2** | web | RTX 4090 | VTLA + GR00T 云端大模型 |
| **Sys-11** | xspace | WSL2 RTX4060 | SmolVLA 450M 认知推理 |
| **Sys-12** | xspace | WSL2 RTX4060 | LeWorldModel 执行层 |

## 👥 角色卡

| 分身 | 角色 | 系统 | 环境 |
|------|------|:---:|------|
| **xspace/静静** | 🏗️ 总工/架构师 | Sys-1/11/12 | WSL2 RTX4060 |
| **web** | ☁️ 云端训练+前端 | Sys-2 | RTX 4090 |
| **小芳** | 🔧 硬件/安全/测试 | Sys-0 | Mac M1 + Orin |

## 🏗️ 架构

```
Sys-2 (web/4090)  VTLA + GR00T
    ↓ gRPC API
Sys-11 (xspace/4060) SmolVLA 450M
    ↓
Sys-1 (xspace/4060) ACT 51.6M 底座
    ↓ 共享接口
Sys-12 (xspace/4060) LeWorldModel
    ↓
Sys-0 (小芳/Mac+Orin) 安全层
    ↓
XMS5-R800 真机
```

## 🔗 仓库

| 仓库 | 负责人 |
|------|:---:|
| `lerobot-smolvla-lew` (GUI) | xspace(main) + 小芳(mac) |
| `zmax-website` (Web) | web |
