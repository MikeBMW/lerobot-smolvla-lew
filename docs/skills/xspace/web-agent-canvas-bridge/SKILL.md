---
name: web-agent-canvas-bridge
description: "Use when 让 web/远程 agent 用提示词操纵本机状态空间功能(画布节点+中转通道)。"
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [canvas, node, relay, agent, prompt, readonly, state-space, zmax]
    related_skills: [zmax-state-space-architecture, http-relay-service, zmax-console]
---

# Web 智能体桥 (画布节点 ↔ 远程 agent 提示词)

## When to Use
- 老倪式需求: 「开通一个状态空间 L5 的新节点, 用于与 web 的 agent 交换信息 —— 远程通过提示词操纵状态空间的功能」。
- 要给任何"远程/网页智能体 ↔ 本机系统"做提示词通道, 且**不允许**远程触发物理动作 (只读红线)。
- 新建画布节点并要**档位级真接** (不是画个框就算接上)。

## 架构 (三层, 已验证)
```
web agent ──POST /api/relay/agent/prompt──▶ ECS 中转 (append-only jsonl + 游标)
                                              ▲ 本机 5s 轮询 GET ?after=N (只读幂等)
本机 L5 桥 WebAgentBridge.dispatch ──▶ 只读功能白名单 (11 项) ──▶ 回执 POST /agent/reply
web agent ◀──GET /api/relay/agent/reply?after=N────────────┘
```
画布侧只加 **1 节点 2 连线** (入=能力清单, 出=提示词意图→L5 主路); 回执走中转 = **画布外副作用** (保持图面简洁)。

## 落地清单 (照抄, 每步都要证据)
1. **中转通道 (纯追加, 不动既有数据闭环)**: 在 ECS relay 加 `agent/{prompt,reply,status}` 路由, 落盘 jsonl + `?after=N` **只读游标** (对比 `/command` 单槽覆盖: 后一条会吃掉前一条 → agent 消息必须不丢)。
   补丁纪律: 锚点唯一性断言 (⚠️ `if path == "/command":` 在 do_GET/do_POST 各出现一次 → 用 `def do_POST(self):\n path=...` 当锚点) + `ast.parse` + 远端备份 + 重启后**回归既有端点**。
2. **真源模块** `<repo>/src/lerobot/policies/left_right/state_space/web_agent_bridge.py`: 功能白名单 (只读/仿真内/通知) + `dispatch(prompt)` + `poll_once()` (游标持久化) + `watch()`; **硬红线** = 动作类正则 (插入/抓取/夹爪/移动/拍照/示教/下发/改配置) 命中 → 拒答 + 写审计 jsonl。
3. **画布节点**: 用构图工具 (`tools/canvas_add_web_agent_node.py` 六断言: id 唯一 / int 坐标 / 零重叠 / 行带 / 目标节点左侧同行 / 连线端口存在且前向无重复) + 备份。⚠️ 行带背景节点 (params.bg/row_bg) 是整行矩形, **必须排除**在重叠判定外。
4. **运行时真接**: `node_logic._reg` + `_EXTERNAL_LOC` (指向真源码, VSCode 可跳) + 真执行函数 (调真源模块, 不是打印)。审计确认: `tools/canvas_level_audit.py` → 该节点 **R2-档位级真接** · ⚠无执行注册 0 · 真缺口 0。
5. **能力清单**: `capability_levels.py` 加层级键 + `L5-Cxx` 条目; ⚠️ `verification_dialog.py` 与自检循环**硬编码 ("L2","L3","L4")** → 新层必须同时补进这些元组, 否则清单里看不见。
6. **常驻**: systemd `zmax-web-agent-bridge.service` (**User=ubuntu**, 别用 root: 会在仓库 reports/ 里写 root 属主文件 → 用户态工具全部 PermissionError) · `Restart=always` · `PYTHONUNBUFFERED=1` (否则日志空)。
7. **取证**: `tools/verify_web_agent_node.py` (位置/零重叠/连线/声明/注册/离线派发真数据/红线拒答+审计/**公网端到端**/游标幂等/执行器真调用/只读字段/服务 enabled+active), 目标 27/27。

## Pitfalls
| 坑 | 症状 | 修法 |
|---|---|---|
| 游标跳队尾用 `after=1e9` | 新提示词也被过滤 → 端到端"拉不到" | seq 是小整数; 用 `GET /agent/status` 的 `last_prompt.seq` 当游标 |
| 常驻服务抢走取证消息 | 自己的 poll 返回空 (服务 5s 也在轮询) | 取证期间 `systemctl stop`, `finally` 里 start |
| systemd 用 root | reports/ 出现 root 属主 state/audit → PermissionError | `User=ubuntu` + `chown` 已有产物 |
| CLI 与真源模块同名 | `import web_agent_bridge` 导到自己 → "Module is not callable" | CLI 换名 (本次 `tools/ss_web_agent.py`) |
| 管道掩盖真 rc | `python x.py \| tail` 里 x.py 崩了也报 rc=0 (实测 FileNotFoundError 被掩盖) | 不接管道, 用 subprocess 取真 rc; 判据看输出标记 |
| 硬编码别的机器路径 | `os.chdir("/home/xspace/...")` → 引擎 rollout 直接挂 | 按 `__file__` 推仓库根 |
| 只读红线写成注释 | 远程一句提示词就"顺手"触发动作 | 白名单 + 正则拒答 + 审计落盘 + 取证里必须有拒答案例 |

## 验证清单
```bash
./gui-venv311/bin/python tools/verify_web_agent_node.py          # 27/27 (含公网端到端)
./gui-venv311/bin/python tools/canvas_level_audit.py             # 新节点 R2 真接 · 真缺口 0
./gui-venv311/bin/python tools/ss_web_agent.py --list            # 能力清单
./gui-venv311/bin/python tools/ss_web_agent.py --ask "画布有多少节点"   # 离线派发
sudo systemctl is-enabled zmax-web-agent-bridge      # enabled + active
```
参考实证: `<repo>/docs/TASK_LEDGER_20260925.md` · `reports/sim2real_preflight_*.md`。
