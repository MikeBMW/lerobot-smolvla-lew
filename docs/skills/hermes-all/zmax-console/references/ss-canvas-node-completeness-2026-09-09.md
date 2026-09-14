# 状态空间画布节点完整性 + 执行链/开关/线程终止 (2026-09-09 老倪连环验收)

## 1. 画布节点"没有输入输出" = 三件套缺件 (ssmani_exp 实锤)
`flows/state_space_obs.json` 有节点但 GUI 侧缺件 → 节点看起来是摆设:
- **① 连线缺** (入0出0 孤立) → 画布无输入输出端口。修:flow links 补真实上下游。
- **② node_logic 注册缺** → 双击/单步执行无逻辑。注意:注册 key 与节点 id 可错位 —
  执行按**节点名关键词** (match_node 最长匹配) 不按 id!`ssmani_exp` 名字含"流形专家"
  实际命中 `ss_pred` 的注册 (node_ss_pred 已实现真实前向自检)。所以"执行逻辑"可能早就通,
  缺的只是连线 + 数据发布。
- **③ 引擎 io_trace/dw channel 缺** → ▶播放 demo 模式读 DataWorld 该节点 out 永远空。
  `_io_snapshot()` 的 channel key = 画布节点名 (data_world.module() 前缀匹配短名),
  引擎每帧真算的旁路结果必须发布进去, 播放才有数显。
- **④ _EXTERNAL_LOC key 错位** → 右键 VSCode 跳源码失效。映射按节点 id/注册 key 查,
  画布 id 与注册 key 不一致时右键死。键对齐 = 右键进真实源码的前提。
- 排查法: `python3` 遍历 flow links 算入度/出度找孤立非 row_bg 节点;
  `grep -n <nid>` node_logic.py/simulink_module.py 零匹配 = GUI 代码从未注册该节点。
- 修复案例 (ssmani_exp 流形专家预测器): flow 重排 L4 行 exp(x=40)→接触流形(410)→性能流形(690),
  接 2 入 (VLM z + 2D3D 几何 z R7) 2 出 (→接触/性能流形, label 预测流形 JEPA);
  引擎 `_io_snapshot` 加 `"🧠 流形专家预测器"` channel (in: z/a 描述, out: 预测流形 6D + trained=False);
  顺手删历史重复连线 (ssworld→ssvideo 两条) — 校验器 FAIL 先对照备份确认是否历史遗留。

## 2. 开关/配置类节点禁入自动执行链 (能力档位 L4→L2 自跳实锤)
- 症状: ⏭单步/▶播放后, 能力档位从 L4 自己跳回 L2 (用户没切)。
- 根因: `_ss_order` / `_ss_step_order` 构建 = `[n for n in self.nodes if type != "row_bg"]`
  (**全部非背景节点**含开关), 单步对每个节点 `execute_node_logic(demo 默认 False = 真实 fn)` →
  能力档位注册的 node_ss_cap 语义=循环切档 → 被"路过执行"切走。
- 修: 三处构建点 (⏭单步 ~6283 / ▶真实播放 _real_finish ~11040 / ▶引擎播放 ~11173) 统一排除
  `not n.get("params", {}).get("cap_switch")`。train_gate/yolo_gate/mode_switch 无 _reg 所以
  execute 返回 None 无害, 唯独注册了逻辑的开关节点会触发副作用 — 排查先问"它有没有 _reg"。
- 教训: 有副作用的配置类节点 (切档/切源) 不要注册成可执行逻辑节点, 或必须排除出自动链。

## 3. 能力档位 radio 三档开关设计 (数据源层)
- 位置: 数据源行 (y=-1450) 与 📦metaworld 数据源/🔀训练/推理 同排 (09-09 老倪: "位置在数据源那一层")。
- 形态: 节点 params `cap_switch: True` + `cap_level: L2/L3/L4`, paint 加分支自绘三 radio 圆钮
  (当前档金色实心 + 档位说明小字), 不走通用标题路径 (drawRoundedRect 后即 return)。
- 交互: SimCanvas.mousePressEvent 左键节点分支先做 radio 圆钮 hit-test (scene 坐标 vs
  局部圆心 12+i*((w-24)/3)+8, y+37, 半径 14) → `module._toggle_cap(node, level)` 直选;
  双击走 on_node_activated 新分支 (params.cap_switch → _toggle_cap(node) 循环下一档)。
- 状态落点三同步: node.params.cap_level (画布重绘+flow 保存持久) + module._cap_level (▶运行消费)
  + ▶运行前从画布节点 params 读 (重启 GUI 不丢档位)。node_ss_cap (node_logic) 改成壳:
  遍历 mod.nodes 按 name 找节点调 mod._toggle_cap — 右键执行与单击/双击同路径, 防"开关显示与实际档位不一致"。

## 4. GUI 大写档位 vs 引擎小写判据 (L4 预算×2 从未生效)
- GUI `_cap_level = "L4"` (大写), 引擎 `run(cap): if cap == "l4"` (小写) → 大写直传永不匹配,
  L4 恢复预算×2 静默失效。修: 引擎 run 开头 `cap = str(cap).lower() if cap else None` 归一化。
- 教训: 跨层参数契约 (GUI 常量 ↔ 引擎字面量) 写死前先对齐大小写/枚举; 生效性用日志关键字验证
  ("🏆 L4 自主恢复档" 是否打印)。

## 5. 真实化引擎线程终止 (mujoco 双 env 并发 segfault)
- 症状: 真实化运行中点 🔄重启 → 崩溃 (Fatal Python error: Segmentation fault,
  栈在 metaworld reset_model → gymnasium mujoco do_simulation)。
- 根因: 真实化引擎跑 daemon 线程, stop_sim/重启只停日志轮询 "跑完即弃", 从不终止线程;
  🔄重启立即 new 第二个 RealStateSpaceSim (第二个 metaworld env) → 双 env 并发 step/reset →
  mujoco C 层 segfault。
- 修三件套: ①引擎 `__init__` 置 `_abort=False`, run 主循环首行查 `_abort` → log + break
  (GUI 置位后至多当前步结束退出); ②`_start_real_sim` 保存线程句柄 `self._real_thread`
  (原裸 Thread().start() 无引用无法 join — 改句柄后小心别保留旧裸启动行 = 双线程启动!);
  ③stop_sim 开头: 置 `_rs._abort=True` → 轮询 `_rt.is_alive()` + processEvents (≤10s, UI 不冻结,
  同 worker 停止模式) → 清 `_real_thread`。
- 验证: 预置 `sim._abort=True` 再 run → 实跑 0 步即退 (循环首行检查生效);
  注意 R0 每步 ~1.5ms 太快, "运行中置位"类探针会因自然完成而测不到 abort — 用预置法。

## 6. 🔄 重启按钮语义 (09-04 定 → 09-09 两次纠正反转)
- 09-04 定制: "停止 → 清缓存 → **立即重新仿真**"。09-09 老倪两次抱怨 "点重启就跳到运行":
  真实化一轮 10-30 分钟, 误触/想停时自动重跑体验差。
- 终态 (09-09): 🔄重启 = 停止 → 清状态空间缓存 → **复位待命, 永不自动运行**;
  要跑点 ▶ (▶ 停止态即从头, 重启增量 = 清缓存强制引擎重跑)。按钮 tooltip 同步。
- 教训: 用户对按钮语义的要求会随使用场景反转 (演示快 vs 真实化慢), 重活默认不自动续跑。

## 7. 画布节点字体再次降档 (09-09, 第三次)
- 真机 Qt logicalDotsPerInch=192 (X 上报 96, 用 gui-venv311 python 查, 勿信 xdpyinfo)。
  10pt=27px/9pt=24px/8pt=21px/7pt=19px。
- 08-28 已 12→10 起, 09-09 老倪仍嫌大/挤 → 标题 10/9/8→9/8/7, row_bg 大字 10→9 起 (下限 8→7),
  徽章/ID 10→9, row_bg 小标 9→8。改处全在 SimNodeItem.paint (标题循环 ~2726 / row_bg ~2634 /
  徽章 ~2926 / ID ~2870 / 小标 ~2660), 全局画布共享一次降一档, 注释记录日期防重复改。
