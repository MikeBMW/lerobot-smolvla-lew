# VSCode 断点"进不去"第四根因 — 引擎内部断点堵死主线程 (2026-09-02)

老倪: "点击运行后进不了 node_metaworld_data 断点; 右键打开 VSCode 还能看到 783 行断点(实心已绑定), 不合理"

## 症状
- 点 ▶运行, VSCode 不停在目标节点逻辑 (node_logic.py:783), GUI 冻结
- 右键节点打开 VSCode: 783 断点红点实心 (已绑定) — 断点本身没问题
- 日志: 20:01:23 点运行后停在 "🧠 任务规划器 (慢决策·回路外)" 之后, 无 "⏩ 数据源节点优先"

## 执行顺序 (关键)
状态空间画布 ▶运行 (start_sim → _start_state_space_sim):
1. sim.run(io_every=25) — **同步**跑引擎 500 步纯 numpy (~0.1s), 内部调用真实源码:
   _build_obs (state_space_sim.py:203) → fuse_sensors (perception.py:33)
2. run() 返回 → _ss_order 构建 (数据源节点排第 1 帧, commit 922d048b)
3. _ss_tick 80ms/帧, 每帧 execute_node_logic 一个节点 (数据源第 1 帧)
4. execute_node_logic 内 ZMAX_DEBUG_BREAK=metaworld 强制 debugpy.breakpoint()

断点若设在引擎内部 (perception.py:33 fuse_sensors assert 行等 src/.../state_space/*.py),
run() 第 1 步命中 → 主线程 do_wait_suspend → run() 不返回 → 步骤 2/3/4 永不执行
→ 节点逻辑断点进不去; 每次 F5 继续又停 (500 步 = 500 次暂停)

## 证据 (py-spy dump 铁证, 2026-09-02 实测)
```
Thread 7948 (MainThread):
    do_wait_suspend (pydevd.py:2199)      ← debugpy 断点暂停中
    fuse_sensors (perception.py:33)       ← 命中的真实位置
    _build_obs (state_space_sim.py:203)
    run (state_space_sim.py:260)
    _start_state_space_sim (simulink_module.py:10260)
    start_sim (simulink_module.py:5816)
```

## 对照 (证明机制本身正常)
19:59:22 旧进程 (无引擎断点) 点运行日志:
```
⏩ 数据源节点优先: 「📦 metaworld 数据源」第 1 帧执行 (断点调试命中快)
▶ 仿真开始 · 物理世界: ...
🔴 调试断点: 暂停「📦 metaworld 数据源」  ← ZMAX_DEBUG_BREAK 强制停, 正常
```
有引擎断点后 20:01:23 点运行: 只到 "🧮 状态空间真实仿真" + "🧠 任务规划器" 就停,
无 "⏩ 数据源节点优先" → 引擎未跑完。

## 判定流程
1. `tail /tmp/simulink_log.txt` (GUI _log 落盘, simulink_module.py _log, append+flush 不丢日志):
   - 有 "⏩ 数据源节点优先" = 引擎已跑完进播放阶段 → 节点逻辑断点问题 (老三坑)
   - 停在引擎内部 (🧮 状态空间真实仿真/🧠 任务规划器后无后续) = 卡在 run() → 引擎内部断点
2. py-spy dump 主线程帧:
   - do_wait_suspend ← 某引擎源码 = 断点命中 (读帧里文件名:行号)
   - 事件循环 idle = 空闲/运行已完成
3. `/proc/<pid>/environ | grep ZMAX` — 确认 F5 调试 env 传入 (ZMAX_DEBUG_BREAK=metaworld)

## 解法
- 删掉/禁用引擎内部源码断点 (src/lerobot/policies/left_right/state_space/*.py),
  只留目标节点断点 (node_logic.py:783) → F5 继续 → 引擎 0.1s 跑完 → 数据源节点命中
- 引擎内部断点每次 F5 停一次 (500 步 = 500 次暂停) — 调引擎内部才留
- 加固方向: 数据源节点 execute_node_logic 提前到 sim.run() 之前 (数据流源头语义,
  与 922d048b "数据源节点优先" 同思路, 从播放阶段提前到引擎阶段)

## 工具备忘 (GUI 进程现场诊断)
- py-spy 安装: `uv pip install --python gui-venv311/bin/python py-spy` (Rust 二进制,
  在 gui-venv311/bin/py-spy, 非 python 模块 — `python -m py_spy` 会报 No module named)
- 运行: `sudo env "PATH=$PATH" gui-venv311/bin/py-spy dump --pid N` (本机 sudo 免密;
  yama ptrace_scope 限制下普通用户 Permission Denied)
- GUI 日志: /tmp/simulink_log.txt (simulink_module.py _log 6749 行, 每次 _log 同步写+flush)
- 进程甄别: ps 里 debugpy launcher/adapter/pydevd 三进程 + studio.py 主进程;
  `ss -tpn` 的 CLOSE-WAIT 连接常是 relay/ws 客户端残留, 不是卡点
