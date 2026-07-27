# Z-MAX 数据闭环 v2 · Data Flywheel

> 2026-07-13 · 三体分工重定义

---

## 👥 角色分工

| 分身 | 核心职责 | 平台 |
|:---:|------|------|
| **小芳** | 旁路仿真 + 混合模型配置 + 部署Orin | Mac M1 |
| **xspace** | 数据层 + 下发训练任务 | WSL2 RTX4060 |
| **web** | 全部模型训练 | RTX4090 |

---

## 🏗️ 数据闭环

```
Orin (真机)
  │ 采集 RealSense + joint + force + gripper
  ▼
小芳 (Mac 旁路仿真)
  │ 混合真实数据+仿真配置
  │ Sys-1 ACT 42ms 推理
  │ 保存为训练集
  ▼
xspace (数据层)
  │ 下载 MetaWorld 数据集
  │ 下发训练任务到 4090
  │ 质量审核
  ▼
web (训练)
  │ Sys-10 ACT 51.6M   → 底座模型
  │ Sys-11 SmolVLA 450M → 认知推理
  │ Sys-12 LeWorldModel → 世界模型
  │ Sys-11+12 混合模型  → 认知+预测
  │ Sys-21 VTLA         → 视觉语言
  │ Sys-22 GR00T        → 具身智能
  ▼
小芳 (部署)
  │ 量化 + Orin Nano/AGX 部署
  │ 验证推理
  ▼
Orin (执行闭环)
```

## 📦 小芳交付物

| 模块 | 状态 | 说明 |
|------|:---:|------|
| Orin Gateway | ✅ | FastAPI HTTP 数据流 |
| 实时波形 | ✅ | Chart.js 6轴监控 |
| ACT 推理 | ✅ | 42ms MPS |
| 仿真桥 | ✅ | 442kHz |
| 部署管线 | ✅ | Edge-deployment 文档 |
| 混合数据 | ⏳ | 待 RealSense 图像流 |

## 📊 训练模型清单 (web)

| 模型 | 参数 | 训练时间(估) |
|:---:|:---:|:---:|
| Sys-10 ACT | 51.6M | ~2h/epoch |
| Sys-11 SmolVLA | 450M | ~8h/epoch |
| Sys-12 LeWorldModel | ~200M | ~4h/epoch |
| Sys-11+12 混合 | ~650M | ~12h/epoch |
| Sys-21 VTLA | ~1B | ~24h/epoch |
| Sys-22 GR00T | ~1.5B | ~48h/epoch |
