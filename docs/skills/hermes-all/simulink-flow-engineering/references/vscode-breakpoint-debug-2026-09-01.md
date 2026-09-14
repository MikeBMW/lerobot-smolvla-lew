# VSCode 断点调试根因修复 (2026-09-01, v3.3.4 aacd2e58)

## 症状
老倪: 右键节点 → VSCode 打开源代码 → 关旧程序 → F5 全新调试进程 → 新控制台 →
点 ▶运行 → node_metaworld_data 的断点不进。

## 排查链
1. `node_metaworld_data` 在 node_logic.py:756, 注册 `_reg("data", ["metaworld 数据", "metaworld数据"], ..., node_metaworld_data)`。
2. `match_node` 最长匹配: 画布「📦 metaworld_peg」→ 命中 `metaworld_peg`(13 字符, node_metaworld_peg),
   不是 `data`(node_metaworld_data)。只有「📦 metaworld 数据源」类名字命中 data。
3. `start_sim` 路由 (simulink_module.py:5802):
   - 状态空间画布 (params.state_space) → `_start_state_space_sim` → `_ss_tick` 每帧执行一个节点 (execute_node_logic)
   - Z700 画布 (含 ◉ LeftRightPolicy) → **`on_train` 直接训练, 不执行节点逻辑** → 节点函数断点永不触发
   - 有环节节点 → `_start_canvas_flow` (NODE_RUN_ACTIONS 匹配的节点才执行)
   - 无环节 → `_exec_topological` 全执行
4. 上轮双保险 (ZMAX_DEBUG_BREAK=1 + execute_node_logic 里 debugpy.breakpoint()) 已提交 launch.json。
5. **根因**: `open_in_vscode` (simulink_module.py:11147-11172) 每次右键都用硬编码 cfg 模板
   **重写 `.vscode/launch.json`** — 模板里没有 env → 上轮加的 `ZMAX_DEBUG_BREAK=1` 被右键一步覆盖丢失
   (git diff 实锤: `- "env": {"ZMAX_DEBUG_BREAK": "1"}`)。
6. 用户流程 = 右键(覆盖) → F5(读覆盖后的 launch.json, 无 env) → debugpy.breakpoint() 不触发 → 断点永不命中。

## 修复
1. `open_in_vscode` 模板写死 env: `{"name": "🚀 全新调试进程 (studio.py)", ..., "env": {"ZMAX_DEBUG_BREAK": "metaworld"}}`
   — 右键重写不丢失 (根治)。
2. `execute_node_logic` 断点过滤升级:
   ```python
   _brk = os.environ.get("ZMAX_DEBUG_BREAK")
   if _brk:
       try:
           import debugpy
           if _brk == "1" or _brk in name:
               debugpy.breakpoint()
       except Exception:
           pass
   ```
   值 = 节点名子串: `metaworld` → 只停数据源节点 (免逐节点 F5); `1` → 全停; 未设 → 无害。
3. launch.json 当前文件同步恢复 env。

## 验证 (ad-hoc)
- launch.json 🚀全新调试进程 env == {"ZMAX_DEBUG_BREAK": "metaworld"}
- open_in_vscode 模板含 `"env": {"ZMAX_DEBUG_BREAK": "metaworld"}`
- execute_node_logic: 「📦 metaworld 数据源」→ breakpoint 触发; 「📊 43D obs 输入」→ 不触发; env=1 → 全停; 无 env → 不触发
- 用 gui-venv311/bin/python 跑 (debugpy 只在 gui-venv311, 系统 python3 无)

## 验证坑 (假通过)
测"非目标节点不停"用了「🧠 左脑 MLP」— 它 match 返回 None (left_brain 注册关键词是
`["LeftBrainMLP"]`, 不含 "左脑") → execute_node_logic 在断点逻辑**之前** `if key is None: return None`
→ 断言假通过。必须用真能匹配的节点名 (如「📊 43D obs 输入」→obs43) 验证过滤逻辑。
左脑/右脑节点名 (🧠 左脑 MLP / 🧠 右脑 WM) 在 node_logic 里实际匹配不到任何 key!

## 给用户的调试操作顺序
1. 右键节点 → VSCode 打开源代码 (此时 launch.json 已带 env)
2. 关旧 GUI, VSCode 重开文件夹 (让 launch.json 刷新), F5 全新调试进程
3. 加载状态空间画布 → ▶运行 → 播到 📦 数据源节点时强制停 (终端先出 "📦 数据源: ..." 日志)
4. 断点别设在函数第一行 (`module = ctx["module"]`) — docstring 是函数第一语句, debugpy 入口行对齐问题;
   设在第二三条语句 (如 `source = p.get("source", "metaworld")`) 最稳
5. 若仍不停: VSCode 调试控制台底部输出贴出来 — 说明进程没连上调试器
