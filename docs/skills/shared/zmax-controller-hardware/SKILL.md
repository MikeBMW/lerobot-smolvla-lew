---
name: zmax-controller-hardware
description: "Z-MAX 控制器硬件选型 & 均胜电子供应链 — 域控制器规格、接口定义、电源管理、传感器融合、供应商管理"
category: robotics
---

# Z-MAX 控制器硬件 & 供应链

## 触发条件
- 涉及 Z-MAX 控制器硬件选型、接口定义
- 涉及均胜电子 (Joyson) 供应链
- 涉及域控制器 (DCU)、BMS、传感器融合模块
- 涉及机器人控制器与传感器/执行器的接口规格

## 核心知识点

### 均胜电子
- 全球汽车电子供应商，总部宁波
- 核心产品: 域控制器、BMS、座舱电子、安全系统
- Z-MAX 相关性: DCU 可作为机器人中央计算平台

### 控制器架构 (方案A)
- 主SoC: NVIDIA AGX Orin (275 TOPS)
- 安全MCU: Infineon TC397 (ASIL-D)
- 内存: 32GB LPDDR5
- 接口: GMSL2×8 + EtherCAT×2 + CAN-FD×4 + 10GbE×2

### 关键接口
- 控制器↔机械臂: EtherCAT 1ms周期
- 控制器↔视觉: GMSL2 6Gbps
- 控制器↔力传感器: EtherCAT/SPI 100μs
- 急停/使能: 硬线IO <1ms

### 供应商管理
- 文档: `docs/supply-chain-joyson-controller.md`
- 备选: 德赛西威IPU04 (DCU), NXP S32G (MCU), ATI Nano17 (力传感器)

## 工作流
1. 需求分析 → 查看供应链文档
2. 选型决策 → 方案A(均胜DCU) vs 方案B(自研+均胜模块)
3. 接口确认 → 参考第四节接口定义
4. 备选评估 → 参考第五节供应商表

## 参考文档
- `docs/supply-chain-joyson-controller.md` — 完整供应链文档
- `docs/L2-Z-MAX解决方案-v1.0.1.md` — Z700硬件规格
- `docs/Orin运维手册.md` — Orin平台运维
