# 状态空间画布 2026-09-09 — 字体/开关节点/执行链/重启崩溃 全记录

老倪 09-09 一天连环验收暴露的 7 类坑,全部实锤+修复。GUI 画布/引擎/flow 三处协作的通用铁律。

## 1. 画布节点"没有输入输出"= 节点三件套不齐 (ssmani_exp 实锤)

**症状**: 双击/查看「🧠 流形专家预测器 (JEPA)」节点 — 画布上入0出0 孤立, 播放/单步时节点无任何数据显示。用户:"这个模块怎么没有输入输出"。

**诊断链** (别猜, 三条 grep 实锤):
- `grep ssmani_exp tools/gui/node_logic.py tools/gui/simulink_module.py` → **零匹配** = 节点 JSON 在 flow 里, GUI 代码里没注册/没映射/没连线
- flow links 遍历: 该 id 入度=0 出度=0
- 引擎 `_io_snapshot()` 返回的 channel dict (键=画布节点名): 无该节点名 → DataWorld/demo 播放永远无数据

**修复三件套** (每个画布节点必须齐):
1. **flow json**: 接线 (参照同排同层节点拓扑: ssmani_exp 参照 ssmani_c/p 的入线源 ss2d3d+ssvlm; 出线连真值流形节点做"预测对照") + 位置摆对该层行首 (用户指定"预测器在接触/性能流形前面")
2. **引擎 io_trace channel**: `_io_snapshot()` 加 `"🧠 流形专家预测器": {"in": [...], "out": [...]}` — 引擎每帧真算的旁路结果 (predict_manifold → tr['mani_pred']) 不发布 = 播放时节点永远没输出。发布值从 `self._mani_out["pred"]` 取 (dict 含 manifold tensor), 转 np round 再展示
3. **执行/映射**: node_logic `_reg` 注册词命中 (节点名含注册词即可, match_node 最长匹配) + `_EXTERNAL_LOC[key]` 右键跳真实源码 — 本例执行逻辑早已挂在 key `ss_pred` (注册词"流形专家"), 画布 id 却是 `ssmani_exp`, 靠关键词匹配天然命中, 缺的只是连线和发布

**教训**: 09-08 加引擎侧 predictor 注入时只加了节点 JSON + 引擎调用, 没加 io channel → "写了引擎每帧真调但画布看不见"。**引擎每帧真调的数据, 若不进 _io_snapshot, 画布节点就等于没有输出。**

## 2. 配置/开关类节点: 要可视化开关, 不进自动执行链

用户两次纠正能力档位节点:
- "位置摆错了,应该在数据源那一层" (节点 JSON y 与 node_logic 注释自称"数据源层"不符, 摆到中间行)
- "没有开关可以选择啊" — 原来只是普通 model 节点 + 双击循环切档 (module._cap_level), **无视觉状态无点选控件** → 用户以为没开关

**实现范式** (照 gate 家族 train_gate/yolo_gate/mode_switch):
- params 标记 `cap_switch: true` + `cap_level: "L2"` 持久档位 (flow json 存, 重启不丢)
- paint 分支 (drawRoundedRect 后、通用标题前): 三档 radio (圆点+标签+当前档金色高亮+底部当前档说明), `return` 提前跳出通用绘制
- 交互: 单击圆钮直选 (SimCanvas.mousePressEvent 左键节点分支, 按 paint 同款坐标公式算 radio 圆心 hit-test, 半径 ~14px) + 双击循环 (on_node_activated 分支 → module._toggle_cap)
- **档位落两处**: node.params.cap_level (画布重绘/持久) + module._cap_level (▶运行消费); `_toggle_cap(node, level=None)` 统一入口, level=None=循环
- ▶运行前从画布节点 params.cap_level 读档位优先 (重启 GUI 不丢档位), 兜底 module 内存值
- node_logic 右键执行也走 module._toggle_cap (找同名 node) — 三入口同一路径, 杜绝"切了内存档位画布不更新"

**⚠️ 副作用开关节点必须排除出自动执行链** — 实锤: ⏭单步/▶播放遍历所有非 row_bg 节点逐个 execute_node_logic, 能力档位注册了 node_ss_cap (语义=切档) → **单步路过它就 L4→L2 自己切换** (用户:"我没有切换档位啊")。gate 家族 (train_gate/yolo_gate/mode_switch) 无 _reg 所以路过无害, 唯独 cap 有注册+副作用。修: 三处执行链构建 (`_ss_step_order`/`_ss_order` ×2) 统一排除 `params.cap_switch`。

## 3. 能力档位大小写 bug: GUI "L4" vs 引擎 "l4"

GUI `_toggle_cap`/node_ss_cap 档位值大写 "L2/L3/L4", 引擎 `run(cap=)` 判 `cap == "l4"` 小写 → **L4 的"恢复预算×2"从未生效** (静默)。修: 引擎 run 入口 `cap = str(cap).lower() if cap else None` 归一化。**跨层参数传值必须查大小写/枚举一致**, 尤其 GUI↔引擎这种两个文件。

## 4. 🔄重启崩溃 = mujoco 双 env 并发 segfault (09-09 实锤)

**症状**: ▶运行 (真实化, L4) 中点 🔄重启 → GUI 崩。崩溃日志: `Fatal Python error: Segmentation fault` 在 `metaworld sawyer_xyz_env._reset_hand → mujoco do_simulation`。

**根因**: 真实化引擎跑在 daemon 线程 (`threading.Thread(target=_work, daemon=True).start()`), **stop_sim 从不终止它** (原注释"跑完即弃", 只停 _real_poll_timer 轮询)。🔄重启 = 旧引擎 (mujoco env) 还在物理循环里 → 立即 new 新 RealStateSpaceSim → 双 metaworld env 同进程并发 step/reset → mujoco C 层 segfault。

**修复三件套** (GUI 长任务线程通用):
1. 引擎 run() 循环首行查 `getattr(self, "_abort", False)` → break (__init__ 置 False; CLI 验证: 预置 True → 0 步即退)
2. GUI 保存线程句柄 `self._real_thread = _th` (原来裸 start 不存, 无法 join)
3. stop_sim() 先置 `sim._abort = True` → 轮询 `_rt.is_alive()` ≤10s (processEvents 不冻结 UI, 同训练 worker 停止模式) → 才允许开新引擎

**教训**: daemon 线程"跑完即弃"对 GUI 停止/重启语义 = 崩溃源。任何 GUI 启动的长跑线程 (引擎/采集/推理) 必须有 abort flag + 句柄 join, 否则重启类操作会叠两个重资源实例。

## 5. 🔄重启行为: 用户两次纠正 = 只复位不自动跑

09-04 老倪定制"重启 = 停止→立即重新仿真"(tooltip 都写着), 09-09 连续两次否掉:
- "为什么点击重启,就跳到运行,又崩溃了" → 修崩溃
- "一点重启,还是跳到运行" → **运行中点重启不该又跑一轮** (真实化一轮 10-30 分钟)
最终形态: 重启 = stop_sim → 清缓存 (_ss_step_tr/_ss_step_order/_ss_last_sim/_ss_trace/_sim_tr/_ss_timer 置 None) → **不调 start_sim**, 日志"已复位待命 (点 ▶ 运行 开始新仿真)", tooltip 同步改。
**教训**: 用户对同一按钮语义连续两次纠正时, 以最新意图为准彻底改, 别做"运行中/停止态分情况"的中间态 (第一轮修复就是分情况, 被第二次纠正打回)。

## 6. 档位过滤执行链 + 切档必须重置执行序

需求: L2 档单步/播放不该高亮 L3/L4 行功能 (用户:"选了 L2, 怎么 L4 的功能也高亮了")。

**节点层级判定**: 节点 y 落在哪个 row_bg 色带内 → 行名含 "L4"/"L3"/"L2" → 4/3/2; 基础·回路外行 (数据源/大模型层/验证层/可视化层) → 0 恒包含。过滤条件 `_ss_node_cap_level(n) <= _ss_cap_num()` (cap 未设默认 2)。

**⚠️ 切档后必须重置已构建的执行序** (实锤): `_ss_step_order` 只在首次点单步时按当时档位构建 (35 节点 L2 序), 切 L3 后不重建 → 单步永远走旧 L2 序, 进不了 VLM/Flow-Matching (用户:"L3 为什么不进入 VLM 和 Flow Matching")。修: `_toggle_cap` 里置 `_ss_step_order/_step_order/_ss_order = None` (播放中 _ss_timer active 时不动 _ss_order, 防 tick 崩, 下轮重建)。

## 7. 小坑: 节点函数漏 import numpy

单步日志 "⚠️ 前馈激活直方图失败: name 'np' is not defined" — node_ss_ff_hist 用 np.round 但函数内无 `import numpy as np` (node_logic 节点函数风格=函数内 import)。单步逐个真实执行节点函数会暴露这类静态检查漏网之鱼 — **执行序里每个节点函数都会被真实跑, 是隐性回归测试**。

## 8. 画布流程改动验证清单 (本次全跑过)
- flow json 改动 → `python3 tools/ci/validate_flow.py flows/xxx.json` 必须 ALL PASS (既有重复连线 ssworld→ssvideo ×2 会 FAIL, 删旧留新; 未连接 row_bg/开关类节点是豁免)
- 引擎改动 → `gui-venv311/bin/python -m py_compile` + 真跑探针 (~/lerobot-venv/bin/python, R0 vision=False 80 步 0.9s 快验)
- GUI 代码改动 → 重启 (ZMAX_DEBUG=1 保 5678) → 证据三连 (pid/时间/5678)
