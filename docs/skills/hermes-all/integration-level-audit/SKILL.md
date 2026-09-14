---
name: integration-level-audit
description: "Use when 判定模型/节点是否真的接进执行链 — 节点级 vs 档位级分级取证, 孤岛/假接入识别."
version: 1.0.0
author: Hermes Agent
license: MIT
tags: [integration-audit, wiring, canvas-node, honesty, evidence, real-chain]
metadata:
  hermes:
    tags: [integration-audit, wiring, canvas-node, honesty, evidence, real-chain]
    related_skills: [zmax-state-space-architecture, zmax-console, robot-policy-eval]
trigger: "Use when the user asks「X 集成进去了么 / 真的接上了么 / 是每帧调用么 / 谁发出的指令」about a model, algorithm, node or module — or before you yourself claim '接入完毕' in a delivery. Especially when a component runs standalone (selftest/评测通过) and the question is whether the live execution chain actually calls it."
---

# 集成层级审计 (节点级 ≠ 档位级)

## 为什么需要

用户 (老倪) 对工程真实性零容忍, 高频追问「**实际怎么执行的**」, 且明确: **节点双击自检不算接上**,
"模型/类必须被真实链路每帧调用"。所以声称"已接入"之前必须**分级取证**, 否则就是把演示当交付。

**结论公式: 组件能单步真跑 ≠ 它进了那条每帧执行链。**

## 四级阶梯 (逐级给证据, 别跳级, 别含糊)

| 级 | 名称 | 判据 (全部可查) |
|---|---|---|
| L0 | 封装 | 文件在位: 契约/数据源/适配器/节点/自检 + 跨进程 worker (若有独立 venv) |
| L1 | 单步真跑 | 自检 A 闸通过 (拒绝零动作) + 真权重路径 chunk **非零且随观测变化**; 画布双击/右键/⏭单步真出动作 |
| L2 | **档位链** | ①注册 (`_reg("<key>")` / 工厂注册表) ②图上节点存在 **且 links 里有连线** ③**档位/能力清单里有此名** ④引擎与面板文案不再写"未接入" |
| L3 | 硬件 | 真机 IO 真实现 (不是 `NotImplementedError` 预留), 或有明确的仿真等价物 |

## L2 审计命令 (照抄, 5 步)

```bash
# ① 注册
grep -n '_reg("<key>"' tools/gui/node_logic.py
grep -rn '<key>' src/**/node_registry.py          # 其它工程的注册表
# ② 节点在位 + ③ 孤岛检查 (节点在位 ≠ 接入)
python3 -c "
import json;d=json.load(open('flows/state_space_obs.json'))
nid='ssintact'
print('节点在位:', any(n['id']==nid for n in d['nodes']))
print('连线数:', len([l for l in d['links'] if nid in (l.get('f'),l.get('t'))]))"
# ④ 档位/能力清单
grep -rn '<key>' src/lerobot/verification/capability_levels.py
# ⑤ 代码自己的诚实标注 (引擎/面板是否仍写"未接入")
grep -rn '未接入\|S3 前\|占位' tools/gui/state_space_sim_real.py
```

**孤岛 (links 数 = 0) 是最强信号**: 节点画在图上、能被双击, 但没进任何链路。
⑤ 尤其有用 —— 好代码自己就标了"未接入引擎", 汇报前先读它, 别和它打架。

## 回答模板 (老倪认这种结构)

> 「节点级已集成: 注册 / 单步真跑 / 防假闸 三项都有实测 (贴数字)。
> 档位级**还没接**: 工程图 0 连线、能力清单无此名、面板明写"未接入引擎"、IO 只到 Sim。
> 差的正是 S3 适配。」

**禁止**一句"接上了"或"已经集成"。分级的答案才既诚实又可执行。

## 假接入的常见形态 (审计时逐个排)

1. 节点在图上但 **0 连线** → 画上去了没接线。
2. 注册了但**档位/能力清单里没有** → L4 档 ▶运行/单步永远不会调它 (只有双击才跑)。
3. 引擎/面板写着"未接入", 汇报却说"已接入" → 直接自相矛盾, 以代码为准。
4. IO 是 `NotImplementedError` 预留, 却称"输出直连硬件"。
5. 自检只测**形状/有限性** → 全零 chunk 也算通过 (必须有"非零 + 非常量 + 随观测变化"判据 + 零动作硬闸)。
6. 输入是**合成/占位数据** (npz 无渲染帧 → 造运动序列) 却当成真实感知。
7. 用**占位数值**冒充真实输出 (写死 conf 0.99 / 抄真值当检测结果) —— 老倪红线第一条。

## 接入下一级前的硬约束 (先量化再动手)

- **延迟预算**: 单步耗时 vs 目标帧率必须先量 (实例: INTACT 单步 316ms, paper 权重/GPU —— 说"每帧调用"前得先回答帧率够不够)。计算图/大模型接进实时回路时, 316ms 是真实工程约束, 不是细节。
- **推荐推序**: ① **只读旁路** (每帧真调, 结果进数据总线/可视化, **动作不参与下发**) → 先量延迟与稳定性; ② **接管某段** (输出真驱动执行) → 必须**同口径 A/B + 不回退证明**; ③ **硬件**。
- **不回退红线**: 新模型接管不得让插拔任务成功率/性能回退。先回归, 再交付。
- 老倪式验收: 要**视频或数据实证**, 口头不算; 他更关心"改了什么", 不关心过程。

## 参考

- `references/intact-l4-audit-2026-09-12.md` — INTACT 节点实测快照 (L1 证据数字 / 孤岛 / 面板原文 / 回答样例)。
- 画布架构与"孤立节点/断头"既有铁律: `zmax-state-space-architecture` (user-owned, 只读参考)。
- 画布节点三处注册与跨 venv 桥: `cross-venv-model-canvas-node` (user-owned, 只读参考)。
