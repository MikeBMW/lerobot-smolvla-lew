# 状态空间运行播放截断 + GUI 调试手段 (2026-09-01, f63a59a8 + 3e168d1b)

## 症状链 (VSCode 断点调试第二/三轮, 承接 vscode-breakpoint-debug-2026-09-01.md)
- 修好 launch.json env 覆盖问题后, 用户 F5 全新调试进程点 ▶运行, node_metaworld_data 断点仍不进。
- 断点能进之后又报: "studio.py is not responding" + 仿真波形/操作视频窗口一直最前面、关不掉。

## 根因②: ▶运行播放截断 — 后排节点永不执行 (断点进不去的最终根因)
- `_start_state_space_sim` 跑引擎 → `_ss_tick`(80ms QTimer) 每帧执行
  `execute_node_logic(self, self._ss_order[min(_ss_round, len-1)], label="▶运行")` 一个节点。
- 播放轮数 `n_rounds = len(io_trace)` = 引擎 io_trace 帧数 (500 步 / io_every=25, 实测只有 14 帧)。
- 状态空间画布 22 个功能节点, 📦 metaworld 数据源排 _ss_order 第 17 位 → 动画播到第 14 帧
  (📐2D→3D) 就 `_ss_finish()` → **数据源/LLM 等后排节点从未执行** → 断点永不进、数据源"假激活"。
- 修复 (simulink_module.py _ss_tick):
  ```python
  n_rounds = len(io_trace) if io_trace else min(len(tr["t"]), 20)
  n_rounds = max(n_rounds, len(self._ss_order))   # 整轮节点逻辑必执行
  ```
  动画 idx 计算 `int(_ss_round / max(1, n_rounds-1) * (len(t)-1))` 在 _ss_round=n_rounds-1 时恰好
  = len(t)-1, 全程有界; io_trace feed 已有 `_ss_round < len(io_trace)` 保护, 不越界。
- 诊断信号 (实锤): `/tmp/simulink_log.txt` 中仿真从 📡传感器融合 播到 📐2D→3D 就"仿真完成",
  全程无「📦 数据源:」日志 (node_metaworld_data 内部 log)。
- 验证: 模拟 n_rounds=max(14,22)=22 循环, 断言数据源节点第 17 帧进入执行序列、idx∈[0,499]。

## 现象学: 断点暂停 = 主线程冻结 (不是 bug)
- debugpy 断点命中 → 主线程停在调试器 → Qt 事件循环不跑 → 所有窗口点 × 无反应 (关不掉) +
  Windows 弹 "studio.py is not responding"。F5 继续即恢复。向用户解释"停在断点了", 别当卡死修。
- 弹窗"一直在最前面" = `_show_nonmodal` (simulink_module.py:9297) 统一
  `setWindowFlags(... | Qt.WindowStaysOnTopHint)` — 防 WSLg 下弹窗不可见的设计, 双击弹窗保留。

## 修复: 运行模式自动弹窗抑制 (3e168d1b)
- _ss_tick 播放时 execute_node_logic 执行 node_ss_scope(📊仿真波形, _ss_order[10]) /
  node_ss_video(🎥操作视频, [11]) 会自动弹置顶大窗口, 打断运行/调试。
- 修复: node_logic.py 两函数开头加
  ```python
  label = ctx.get("label", "")
  if label == "▶运行":
      log = ctx.get("log")
      if log:
          log("🎥 操作视频: 运行模式跳过弹窗 — 双击节点打开")  # 波形同理
      return True
  ```
  双击 (无 label) / ⏭单步 照常弹窗。LLM 节点 (node_ss_llm/reason/skill) 只 import planner.py
  跑本地规划 + log, 不弹窗, 无需处理。

## 🩺 GUI 运行时排查手段 (用户"你查一下"时按序用)
1. `tail -60 /tmp/simulink_log.txt` — GUI 底部日志**实时落盘**, 第一手证据:
   加载了哪个 flow、点运行后实际执行了哪些节点、有无目标函数日志。
   (其他: /tmp/studio_launch.log, /tmp/zmax_simulink_init.log, /tmp/closeEvent.log)
2. `/proc/<pid>/environ` — 调试 env 是否真进进程 (launch.json 有 ≠ 进程有)。
3. `/proc/<pid>/status` State=S + 主线程 wchan=poll_schedule_timeout = Qt 事件循环空闲
   (没停在断点); 停在 debugpy 断点时主线程阻塞在调试等待 (futex 类)。
4. `ps aux | grep studio.py`: F5 调试 = launcher + `debugpy --connect 127.0.0.1:<port>` +
   pydevd 子进程 多进程正常, 真正的 GUI 是 debugpy --connect 那条 (pid 最大)。
5. `__pycache__/*.pyc` mtime vs 源码 mtime — 进程加载新代码 = 进程启动时间晚于 patch 时间。

## 验证坑
- 测"断点过滤不误停"别用 match 不到 key 的节点名 (🧠 左脑 MLP → None, 注册词是 LeftBrainMLP):
  execute_node_logic 在断点逻辑**之前** `if key is None: return None`, 断言假通过。
  用「📊 43D obs 输入」(→obs43) 这类真匹配节点。
- debugpy 只在 gui-venv311, 系统 python3 无 → 验证脚本用 `./gui-venv311/bin/python` 跑。
