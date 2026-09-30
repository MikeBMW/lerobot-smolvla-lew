# 真机首次适配 · 全系统安全检查单 (2026-09-19, v5.9.0)

> 老倪: 「我要和你一起进行标定适配过程 … 由 L4 负责安全, L3 负责流程, L2 负责操作; 再次检查全系统逻辑,
> 冗余检查后, 我们开始人机在环操作 … 注意, 这次是你第一次进行真实环境适配, 要保证全系统所有功能的
> 可用性, 可操作性, 可标定性, 保证安全的人机操作。」
> 纪律: 本文所有数字均为**只读实测**; 取不到的字段写明"取不到", 不猜。

## 一、层责任 (系统级约定 + 代码出处 + 在役状态)

| 层 | 职责 (谁负责什么) | 代码出处 | 状态 |
|---|---|---|---|
| **L4 安全** | **否决权 + 限幅 + 恢复预算**; 最后一道闸门, 上层不可绕过 | `state_space_sim_real.py`(安全边界/否决) · `state_space/safety.py` · `cognition.py`(认知层否决) | 在役 (限幅 + 否决计数) |
| **L3 流程** | 阶段序列 / 技能序列编排 + 长程规划 (下一步做什么) | `state_space/skills/atomic_skills.py`(SK01-08) · `planner.py`(TaskPlanner 242 技能) | 在役 (13 阶段状态机) |
| **L2 操作** | 单步原子动作 / 解析控制 + 前馈加速 (这一步怎么做) | `state_space/parallel.py` · `execution.py` | 在役 (解析控制 + 前馈 MLP 快通道) |
| 唯一出口 | 上层只给意图, 执行只由 L2 收口 | `sched.decide` (矩阵 F12: 出口计数=1 ✅) | 已验收 |
| 人机在环 | **任何机械臂动作须操作员确认; `operation_state=drag` 时一律不下发** | 本清单 §三 | 生效中 |

## 二、真机只读体检 (2026-09-19 09:5x, 零指令)

| 项 | 实测值 | 判定 |
|---|---|---|
| 链路 | 本机→Orin `192.168.23.66` 0.21ms | ✅ |
| **power_state** | `on` | ✅ (解锁闸门 ③ 满足) |
| **operation_state** | **`drag`** (拖动示教) | ⛔ **禁止下发** — 需操作员关拖动→切自动(idle) |
| has_error | `false` | ✅ |
| **六轴速度** | 全 `0` (静止) | ✅ |
| TCP | `[0.42118, 0.01042, 0.15360] m` (frame=base_link) | 与旁路同刻配对 |
| 相机 | 640×480, 帧龄 0.4~1.7s, YOLO `peg` conf 0.69, 框中心 (279, 87.5) | ✅ 真机帧链活 |
| 产线 `/motion` | 节点在线; 日志显示最近完成一个循环("抓取失败开爪"→"循环结束移动到过渡点"→灯塔 complete); `/motion/active_states` **当前无活动状态** | ⚠️ 会抢控制 → 只在停线窗口动 |
| **`collision_detection_enabled`** | **`False`** (撞了不停) | ⛔ **真风险**, 见 §四 |
| `tool_load` | 全 `0` (工具负载/质心未设) | ⚠️ 力矩模型有偏差 |
| `rt_speed_ratio` | `0.05` (rt 路径 5%) | ✅ 低速 |
| `final_joint_move_speed` / `move_timeout` | `0.1` / `30.0` | ✅ |
| `speed` / `line_speed` | `50` / `40` | ⚠️ 非 rt 路径参数, 本次不用 |

> 注: `/robot_status` 的 JSON 字符串**被发布者截断** (只能拿到前 ~110 字符) → `estop_detected` / `collision_detected`
> 字段**取不到**; 需在示教器/控制器侧确认, 或让集成商补全该话题。**我不据此假设"无急停"。**

## 三、现场作业闸门 (逐条, 缺一不动)

1. **只读三查**: `power_state=on` · `operation_state=idle` · `has_error=false` (+ 示教器确认无急停/无报警)
2. **操作员关拖动 → 切自动模式(idle)** (SDK 无切模式 service, 必须示教器侧操作)
3. **确认产线 `/motion` 已停且不会自启** (它在跑抓取循环时会抢控制)
4. **现场安全确认** (操作员口头): 臂活动范围内无人/无遮挡 · 急停在手边 · 保持低倍率
5. **我逐条请示, 操作员明确"可以"后才发** (一次只发一个单步)
6. **首条动作取最小可见步**: J6 相对 **+1° (0.017453 rad)** → TCP 弧长 ~0.42mm; 前后各取 `/real_joint_states` + `/robot/tcp_pose`
7. **绝不触碰**: `/execute_external_task`(real_mode=true) · `/hmi/command` · `/state_machine/*`
8. 判完成看**真值 + `operation_state=idle`**, **不凭 `success=False` 重发** (会把 1° 叠成 2°)

## 四、风险清单 + 缓解 (全系统稳定性/成熟度视角)

| # | 风险 | 证据 | 缓解 |
|---|---|---|---|
| R1 | **碰撞检测关闭** (撞了不停) | `collision_detection_enabled=False` | ⛔ 只做 ≤1° 小步 + 5% 速度 + 人盯死 + **建议集成商开启** (本条不解除不做任何插拔类动作) |
| R2 | 工具负载未设 → 拖动力学/力矩模型偏差 | `tool_load` 全 0 | 不用力控原语 (`/lissajous_force_search` 等); 只用位置模式小步 |
| R3 | 产线 `/motion` 抢控制 | `/motion` 节点在线 + 历史执行日志 | 只在操作员确认的停线窗口; 动作前重查 `/motion/active_states` 为空 |
| R4 | 拖动示教态 (`drag`) | `operation_state=drag` | 一律不下发, 等操作员切 idle |
| R5 | **标定缺失** → 真机 3D 只能 `fk_only` | `T_base_cam=None`, `box3d_state.json` 不存在 | 先走零运动采集 (S1/S2); 未标定前**不拿 fk_only 做插拔** (拒算不编造) |
| R6 | 深度话题不可用 (全帧 2~3m) | 之前实测 | 不用深度; 走 K + 自监督手眼 (合成 4mm / 彩排 5.2mm) |
| R7 | 大模型判读慢 (冷启 60~134s) | 实测 | 判读异步 + prompt 缓存 + 本地 Qwen2.5-VL-3B (下载中) |
| R8 | `/robot_status` 字段被截断 | 实测 ~110 字符 | 不据它判急停; 需集成商补全 |
| R9 | 引擎 L4 路径**双实现** | `state_space_sim_real.py::_l4_intact_u_ff` vs `policies/intact/service.py::run_once` | 运行真源=引擎路径; service 只服务双击/E2E; 报告里标注路径来源 (冗余, 见 §五) |

## 五、冗余 / 一致性检查结果

| 项 | 结果 | 影响 | 处置 |
|---|---|---|---|
| 同名函数重复定义 (node_logic) | 已修 (`node_ss_skill` 二次定义 → 原子技能更名 `node_ss_atomic`) | 曾致按名调用走错实现 | ✅ 已修 |
| L4 运行路径双实现 | `_l4_intact_u_ff` (引擎) / `run_once` (policy 服务) | 面板与证据可能不一致; 断点只在一条路径命中 | 标注路径来源; 下轮收敛为单一入口 |
| 画布重复连线 (同源同目标) | 4 对 (总装→L2/L3/L4 · 前馈→直方图) | 画布加载时按唯一口径去重, 无功能影响 | 保留 (删除会动零回退基线) |
| 孤立节点 | 0 (仅 2 个真源节点无入线) | — | ✅ |
| 矩阵 | 见 §六 (修复 F09 硬写节点数后 20/20) | — | ✅ |

## 六、全系统功能清单 ↔ 测试用例 (20 项 1:1, 同一把尺)

| # | 功能 | 层 | 开关 | 用例 | 判据 | 结果 |
|---|---|---|---|---|---|---|
| F01 | 输出单步控制量 | L3 | SS_L3 | verify_l3_action.py | 控制量非零且在界内 | ✅ |
| F02 | 按意图零搜索产出动作块 | L4 | SS_L4_INTACT | verify_l4_intact_zeroseach.py | 候选搜索数=0 且动作块非零 | ✅ |
| F03 | 坐标系间无损变换 | L4 | - | flight:selftest | 往返误差<1e-9 | ✅ |
| F04 | 潜空间→几何基映射 | L4 | SS_L4_INTENT_LINE | bundle:lift | 留一 R²≥0.30 | ✅ |
| F05 | 接触条件注入(可关) | L4 | SS_L4_FIBER | verify_fiber_zero_regression.py | 关闭时逐位相同 | ✅ |
| F06 | 上层参考被收口夹紧 | L2 | - | bundle:project | 越界 100% 被夹紧 | ✅ |
| F07 | 任务进展势函数不增 | L2 | - | bundle:potential | 逐帧单调不增 | ✅ |
| F08 | 仿真/真机数据源隔离 | L0 | ZMAX_ANNOT_ROOT* | verify_annot_sim.py | 两源互不污染 | ✅ |
| **F09** | **数据源可随时切换** | L0 | ZMAX_ANNOT_ROOT | verify_src_switch.py | 切换后状态正确 | ✅ (本轮修硬写节点数) |
| F10 | 画面来源如实标注 | L0 | - | verify_real_frame_provenance.py | 标注=真实来源 | ✅ |
| F11 | 各层开关独立(可叠加) | ALL | SS_L4_* | self:no_mutex | 无档位互斥 | ✅ |
| F12 | 唯一执行出口 | ALL | - | self:single_exit | 出口计数=1 | ✅ |
| F13 | 仿真↔真机随时切换 | ALL | MODE_ORDER | self:mode_switch | 三模式入口在 | ✅ |
| F14 | 自适应增益随风险收紧 | L2 | SS_ADAPT_GAIN | verify_adaptive_gain.py | 增益有界且越危险不增 | ✅ |
| F15 | 共享意图编码(两态同算子) | L2 | - | verify_intent_pair.py | 两态同算子且都产动作 | ✅ |
| F16 | 动作似然/行为对齐 | L2 | - | verify_likelihood_head.py | 似然可算且可反传 | ✅ |
| F17 | 接触/性能流形度量 | L4 | SS_L4_FIBER | verify_manifold_layer.py | 偏离风险≥对齐 | ✅ |
| F18 | 潜空间一步预测 | L4 | SS_L4_INTENT_LINE | verify_predictor_layer.py | 前向形状正确且非零 | ✅ |
| F19 | 能力栈逐层收缩 | ALL | - | verify_capability_stack.py | 越界 100% 夹紧 | ✅ |
| F20 | 顶层宏观记忆 | MEM | SS_MACRO_LLM_URL | verify_macro_memory.py | 只读下层+幂等+建议有据 | ✅ |

## 七、可标定性 (本次适配的核心目标)

| 标定量 | 现状 | 取法 (零运动可完成?) |
|---|---|---|
| 相机内参 K | ✅ 已落盘 (`real_cam_calib.json`, fx=394.06 fy=393.47 cx=318.44 cy=238.66 @640×480) | 已完成 (ROS camera_info 出厂标定) |
| **手眼 T_base_cam + 夹持偏移 off + 歪斜 R_rel** | ❌ 未标定 | ✅ 零运动可采 (人工拖 10+ 位姿, 我只读), 自监督拟合 + 前提自证 IoU≥0.45 才落盘 |
| 台面高度 plane_z | ❌ 未知 | 需一次量测或从位姿估计 |
| 模块尺寸 | 标称 [40,16,12]mm | 可联合解 (K 已知时) 或量一次 |
| 夹持重复性 | 未知 | 小步动作 (需批准) 或拖动采样 |

## 八、结论与下一步

- **现在可以做的 (零运动, 零风险)**: 人工拖 3~5 位姿 → 验证"框随位姿变化"数学 → 攒 ≥10 位姿 → 自监督手眼标定落盘 → 真机 3D 从 `fk_only` 升到 5mm 级。
- **要动机械臂 (需逐条批准)**: 先 J6 +1°; 且 **R1 未解除前不做插拔类动作**。
- **必须由现场/集成商完成的**: 关拖动→切自动 · 确认停线 · **开启碰撞检测** · 补 `tool_load` · 补全 `/robot_status` 字段。
