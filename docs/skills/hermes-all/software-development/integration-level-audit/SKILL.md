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
8. **接口开着但没人调 (0 客户端的孤立服务/action)**: 服务端在、类型对、名字能列出来 —— 但**没有任何调用方**。
   实测 MoveIt 的 `/move_action` (moveit_msgs/action/MoveGroup) 与 `/execute_trajectory` 都挂着服务端，
   而 `Action clients` 均为 **0** ⇒ 这条出口是空跑的；真正的规划输出走的是 JSON 文件 + DDS 镜像。
   查法: `ros2 action list -t --include-hidden-topics` → `ros2 action info <名>` (看 clients/servers 计数)。
   ⇒ 报口径时三样都要给: **接口在哪 · 谁在真跑 · 哪条只是留着的出口**; 只说"action 有输出"就是把旁路当主线。

🔴 **判"接口/节点不存在"之前先核 ROS 域**：域不对会让存在的实体**全部凭空消失** (假阴性)。
实测同一个容器里 `ROS_DOMAIN_ID=42`，在默认域 0 下扫也是"空"，结论"没有 action"完全错。
凡是要下"不存在/没接"的结论，先 `echo $ROS_DOMAIN_ID` 对齐域；**action 类话题还默认隐藏，
必须加 `--include-hidden-topics`**，否则拿 `ros2 topic list` 的反面结论同样不可信。

## 接入下一级前的硬约束 (先量化再动手)

- **延迟预算**: 单步耗时 vs 目标帧率必须先量 (实例: INTACT 单步 316ms, paper 权重/GPU —— 说"每帧调用"前得先回答帧率够不够)。计算图/大模型接进实时回路时, 316ms 是真实工程约束, 不是细节。
- **推荐推序**: ① **只读旁路** (每帧真调, 结果进数据总线/可视化, **动作不参与下发**) → 先量延迟与稳定性; ② **接管某段** (输出真驱动执行) → 必须**同口径 A/B + 不回退证明**; ③ **硬件**。
- **不回退红线**: 新模型接管不得让插拔任务成功率/性能回退。先回归, 再交付。
- 老倪式验收: 要**视频或数据实证**, 口头不算; 他更关心"改了什么", 不关心过程。

## 输入级取证: 「模型/节点吃的是哪份数据、返回什么」

L2/L3 过了(确实每帧被调用)之后, 还有一层常被追问: **它吃的是哪张图/哪份数据**。这时输出四样:
**代码位置(文件+行号: 实例化/调用/返回值落台账, 并说明调用在后台 worker 而不是路由里)** · **能点开的图 URL** ·
**返回值原样 JSON + 逐字段一行** · **同源硬证据 = 取回图的像素 md5 == 台账里记的 md5**。

铁律:
- "给人看的产物"与"模型吃的输入"是**两份东西**, 各自命名/各自台账; 改了模型输入口径, 把别的接口里的旧字段**全部同步**,
  否则两个接口自己打架(实测发生过: 一个接口写着模型吃判据图, 另一个说吃 960 临时图)。
- 临时产物**只在会入队干活的那条路径上写**, 清理时**跳过待处理队列里的文件**, 队列设上限; 喂模型前先判存在。
  把写操作放在"抓帧"函数里 ⇒ 连"只看一眼"的请求也写, 实测 9 分钟泄漏 2180 张。
- 跑同源闸前**先确认两边的 `n` 是不是同一个计数器**(检测序号 vs 帧号), 再拿它当 join key;
  在线系统一直在动 ⇒ 按帧对齐才下结论, 对不齐就说"未对齐", 不硬凑。
- 详见 `references/runtime-model-input-observability.md`; 可重跑闸 `scripts/verify_model_input_same_source.py`。

## 参考

### 🆕 档位级验收工具与两条硬纪律 (2026-09-24)

`tools/canvas_level_audit.py` — 逐节点四件套取证: ①执行注册 ②源码映射有效性 ③引擎引用 ④连线数,
落盘 `reports/canvas_level_audit_<ts>.{json,md}` (逐节点表 + 逐连线缺口表)。

**纪律 1: 判"有没有执行注册"必须 import 真分派函数, 不许自己写正则。**
自写 `_reg\("key"` 正则漏掉**循环注册** (`for _skid,…: _reg(_skid,…)` → SK01-08) → 8 个真节点被误判"缺注册"。
正确做法: `from node_logic import match_node; match_node(画布节点名)` — 与 GUI 双击分派逐字同源。

**纪律 2: 解析 `_EXTERNAL_LOC` 路径不许用 `\(([^)]*)\)`, 更不许按 basename glob。**
嵌套括号 `os.path.join(...)` 会在第一个 `)` 处截断; 按 basename 搜会命中 `gui-venv311/site-packages/torch/.../planner.py`
(同名文件!) → 整片 57 条映射被误判失效。正确做法: **按字面量片段顺序拼绝对路径取最长存在后缀**, 并排除 venv/site-packages。

**判据分层 (别把软指标当缺陷)**: 硬判据 = ①有执行注册 ②不孤岛; 源码映射缺失只是"展示回退到节点函数"(合法)。
一次实测: 70 节点 → R1 每帧 16 · R2 档位级真接 31 · R3 语义 13 · R4 终端 7 · R5 待建 3 · ⚠ 0;
152 连线 → 双端运行时 17 · 单端 67 · 双端非运行时 68 · **真缺口(端点无注册) 0**。

**6 类"画布有节点但没执行函数"的修法 (实测有效, 全是真实现只是没接上)**:
| 症状 | 修法 | 实例 |
|---|---|---|
| 关键词对不上 (函数本来就在) | 给已有 `_reg` 的 match 列表**加画布节点名的独特子串** | ss_llm←"长程序列规划器"; ss_skill←"技能序列编排"; ss_mem_l2←"肌肉记忆操作"; ss_mem_l3←"记忆: 海马体" |
| 真没注册 | 写 `node_xxx(ctx)` 真执行函数 + `_reg` + `_EXTERNAL_LOC` 三件套 | n_board_frame (board_frame_module.run); n_l2_muscle (技能 JSON + ROS2 桥只读) |
⚠ 加关键词时必须查**最长匹配**冲突: 别加"长程序列规划"(会抢 🚀 L3 · 长程序列规划), 用更长的独特串。

- `references/orchestrator-model-chain-not-running-2026-09-29.md` — **点了一个档位+▶运行但"模型一条都没跑到"的审计法**:
  编排首阶段崩 (只在分支里赋值的局部变量 → UnboundLocalError) / fatal vs non_fatal (槽位未演示·val 空·训练零检出
  都是可选输入缺口, 不该掐断整链) / 终态三档 done·**done_with_gaps**·failed / 软链补 val 的 jpg-vs-txt 坑 /
  逐节点断点清单走注册表 / 三种调试入口边界 (demo 播放不重跑节点函数; 编排与训练是子进程) /
  **503 先 curl 本机 `/snapshot/<cam>.jpg` 判"没帧"而不是"大模型限流"**。
- `scripts/canvas_node_debug_map.py` — 画布节点 → 注册 key → 执行函数 → **文件:行** 全表 (只读) + 未注册/孤岛计数;
  给"逐节点 VSCode 断点"用的落点清单 (走 `registry.match_node` + `sourceview`, 与 GUI 双击分派同源)。
- `references/intact-l4-audit-2026-09-12.md` — INTACT 节点实测快照 (L1 证据数字 / 孤岛 / 面板原文 / 回答样例)。
- 画布架构与"孤立节点/断头"既有铁律: `zmax-state-space-architecture` (user-owned, 只读参考)。
- 画布节点三处注册与跨 venv 桥: `cross-venv-model-canvas-node` (user-owned, 只读参考)。
