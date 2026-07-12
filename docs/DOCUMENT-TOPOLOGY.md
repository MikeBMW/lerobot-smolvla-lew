# Z-MAX 文档拓扑 v1.0

> 信息一致性保证：Web(概念展示) ↔ GUI(工程实现) ↔ 文档(解决方案)  
> 维护: 小芳(硬件) + xspace(产品总工)

## 信息流向

```
顶层: datadrive.world (Z-MAX主页)
  ├── 公司简介 (智蜂创元)
  ├── 产品介绍 (Z700 L2/L3/L4)
  ├── 技术栈 (SmolVLA + 类脑架构)
  ├── 仿真联调 (实时数据 + 性能)
  ├── 专利技术 (交底书 + 标准)
  ├── 硬件树 (传感器/执行器/安全)
  ├── 文档中心 (本索引)
  └── 实时监控 (Orin状态)

         ↓ 概念驱动

GUI工程: lerobot-smolvla-lew/
  ├── src/lerobot/robots/zmax_orin/  ← leRobot抽象
  ├── src/lerobot/policies/zmax_sys*/ ← 模型实现
  ├── hermes_gateway_mac/             ← 仿真+安全
  └── docs/                           ← 全部文档

         ↓ 工程实现

Orin真机: XMS5-R800 + AGX Orin
  └── ROS2 51 topics, 15 nodes
```

## 文档映射

| 层级 | Web标签页 | 源文档 | GUI代码 |
|:---:|------|------|------|
| L2 | 产品介绍 | `L2-Z-MAX解决方案-v1.0.4.md` | `zmax_sys1/` |
| L3 | 产品介绍 | `L3-技术路线-v1.0.4.md` | `zmax_sys11/` |
| L4 | 产品介绍 | `Z-MAX-硬件平台-L2-L3-L4方案.md` | `zmax_sys12/` |
| — | 技术栈 | `Z-MAX-类脑计算方案.md` | `smolvla_lew/` |
| — | 仿真联调 | `benchmark-sys-all-models.md` | `simulation_*.py` |
| — | 专利技术 | `Z-MAX-专利交底书-实用新型.docx` | `docs/patents/` |
| — | 硬件树 | `hardware-spec-L2-L3-L4.json` | `zmax_orin/` |
| — | 实时监控 | `robot-status.json` | `collect_full_status.py` |

## PPT/培训材料

| 材料 | 文件 | 关联章节 |
|------|------|------|
| 产品发布 | `L1-Z-MAX产品发布-v1.0.4.pptx` | L2方案 |
| 产品培训 | `Z-MAX产品培训-L2基线版.pptx` | L2操作 |
| 硬件配置 | `Z-MAX基线版硬件配置培训.pptx` | L2硬件 |
| 交付物 | `Z-MAX基线版交付物培训.pptx` | L2交付 |
| 品牌 | `BRAND-品牌注册材料.pptx` | 公司介绍 |

## 竞品参考

| 文档 | 关联 |
|------|------|
| `竞品分析-具身智能人形机器人-2026Q3.md` | 产品定位 |

## 标准规范

| 标准 | 文件 |
|------|------|
| Q/ZFCY 001.1-2026 | `Z-MAX产品等级定义-L1-L5标准.md` |
| Q/ZFCY 001.2-2026 | 硬核基座(规划) |
| Q/ZFCY 001.3-2026 | 数据飞轮(规划) |

## 供应链

| 文档 | 关联组件 |
|------|------|
| `supply-chain-joyson-controller.md` | 均胜域控制器 |
| `docs/供应链/` 全部PDF | Orin域控/Thor域控/电池包 |
