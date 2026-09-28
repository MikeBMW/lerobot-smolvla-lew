# Z-MAX 状态空间工程 · 工程实现包 (lerobot.engineering)

> 2026-09-28 架构迁移: 节点逻辑从 GUI 目录 (`tools/gui/node_logic.py`) 整体搬进本包。
> **逻辑在包里, GUI 只显示。** 这条是后续所有改动的第一原则。

## 为什么这么分

lerobot 的工程哲学是"能力有注册表、实现有归属、GUI/脚本只是调用方"。Z-MAX 之前把 141 条节点逻辑
(5129 行) 放在 `tools/gui/` 里, 后果: 逻辑与界面耦合、脚本要跨目录 import GUI 文件、路径靠
`dirname(__file__)/../..` 上溯(换个位置就指错)。现在按同一套哲学收口:

| 原来 | 现在 |
|---|---|
| `tools/gui/node_logic.py` (5129 行, 逻辑 + 注册 + 源码视图) | `lerobot/engineering/nodes/library.py` (逻辑) + `registry.py` + `runtime.py` + `sourceview.py` |
| `flows/state_space_obs.json` (仓库根的构图文件) | `lerobot/engineering/flows/state_space_obs.json` (package data) + `flows.py` 统一读写/校验/备份 |
| 各处的 `dirname(__file__)/../..` | `paths.py` 唯一路径真源 |
| 版本/档位靠人记 | `levels.py` 写死 L2/L3/L4/L5 **必须还能干的事** + `check()` 判据 |
| 改逻辑要懂 GUI 目录 | 改逻辑只改 `nodes/library.py` (或后续按档位拆分的模块) |

`tools/gui/node_logic.py` 现在是一层 **兼容壳 (33 行)**, 把包命名空间转发给老调用方 ——
`import node_logic` / `from node_logic import execute_node_logic, NODE_LOGIC` 照旧可用。

## 目录

```
src/lerobot/engineering/
├── __init__.py      对外 API (execute_node_logic / match_node / flows / levels / 141 条逻辑本体)
├── paths.py         路径真源: REPO_ROOT · LOGIC_FILE · FLOWS_DIR · GUI_DIR · DATA_DIR
├── registry.py      注册表: register() · match_node() · home_file() (逻辑在哪) · logic_globals()
├── runtime.py       执行派发: execute_node_logic() · _trace_exec() · _demo_node_output()
├── sourceview.py    源码视图: get_node_source/location · explain_node · save/restore/reload
├── flows.py         画布 JSON: load_canvas() · save_canvas()(原子+备份) · validate_*() · orphans()
├── levels.py        L2/L3/L4/L5 档位契约: LEVELS · band_map() · level_nodes() · check()
├── flows/
│   └── state_space_obs.json     画布真源 (87 节点 / 173 连线)
└── nodes/
    ├── library.py   141 条节点逻辑 + 148 个注册 key (唯一真源)
    └── by_level.py  档位索引 (自动生成): L2/L3/L4/L5 各有哪些节点↔key↔函数
```

仓库根的 `flows/state_space_obs.json` 变成**指向包内的软链**, 历史构图脚本照旧可读可写。

## 档位契约 (不许掉的功能)

`levels.check()` 会把下面这些真跑一遍 (节点在画布上 ∧ 每个节点能落到已注册逻辑):

| 档位 | 必须还能干的事 | 画布节点 |
|---|---|---|
| **L2 基础功能** | 分段感知(检测/触觉/2D→3D/质量) · 传感器融合→43D · 估计/预测/校正/前馈 · 动作调制+安全限幅 · 原子技能 SK01-08 · 执行器→物理闭环 · 肌肉记忆固化直通 | 25 |
| **L3 连续功能** | 长程序列规划 · 技能序列编排 · 跨段技能序列入库 · VLM 编码 + Flow-Matching 连续动作 | 5 |
| **L4 自主安全功能** | 工作安全(INTACT) · 物理世界导航 · 能力档位 · 标定/流形世界模型 · 恢复策略入库 · 势场联络 | 17 |
| **L5 场景理解 + 自动标注** | 视觉语言场景理解(VLM/DeepSeek) · 自动标注→监督 L2/L3/L4 · 任务指令解析 · 工程记忆 · 标注→自动训练 | 11 |

## 改东西的规矩

1. **节点逻辑只写 `nodes/library.py`** (或后续按档位拆出的模块), 不要写回 `tools/gui/`。
2. 画布 JSON 只经 `flows.save_canvas()` 写 (自动备份 + 校验失败拒写); 老脚本写 `flows/` 软链也通, 但新脚本请走包。
3. 任何路径从 `paths.py` 取, 不要再 `dirname(__file__)` 上溯。
4. 新增节点: ①`library.py` 写函数 ②`_reg(key, [关键字], doc, fn)` 注册 (关键字要和画布节点名对得上)
   ③画布 JSON 加节点/连线 ④`tools/verify_engineering.py` 必须过。
5. 改完必跑: `gui-venv311/bin/python tools/verify_engineering.py` (架构自检)
   + `gui-venv311/bin/python tools/verify_canvas_render.py` (渲染: 应仍是 87 节点项 / 172 连线项)。

## 迁移的验收证据 (2026-09-28)

* 注册表: **148 key** (迁移前 147 + 修掉一个历史重名 `ss_pred`, 见下)
* 逐字比对: 147 条逻辑中 **145 条函数源码与新包逐字相同**, 仅 2 条 (`intact` / `intact_dec`) 差一行
  路径写法 (`dirname(__file__)/../..` → `paths.REPO_ROOT`, 值相同)
* 87 个画布节点名 → 逻辑 key 映射: **除 `📈 先验动力学预测器` (旧=None 无法运行) 外逐字相同**
* 画布渲染: 迁移前后同为 **87 节点项 / 172 连线项**
* 档位审计 (`tools/canvas_level_audit.py`): 迁移前后同为
  **R1-运行时每帧 15 · R2-档位级真接 34 · R3-语义 13 · R4-终端 7 · R5-待建 3 · 真缺口 0**
* 顺带修掉的历史缺陷: `ss_pred` 被注册两次(先验动力学 / 流形专家), dict 覆盖 ⇒
  **「先验动力学预测器」这个画布节点从来没有可执行逻辑**; 现拆成 `ss_dyn`(dynamics.py) 与 `ss_pred`(manifold),
  只影响这 1 个节点的映射。
