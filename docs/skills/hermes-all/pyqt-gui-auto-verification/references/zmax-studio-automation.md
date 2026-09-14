# Z-MAX studio 画布自动化机制 (2026-09-05)

仓库: /home/ubuntu/lerobot-smolvla-lew · GUI venv: gui-venv311 · 报告脚本用 gui-venv311 (reportlab 在)

## 状态空间画布节点机制 (改画布前必读)
- **画布节点唯一数据源 = flows/state_space_obs.json** (nodes+links+row_bg); 左栏 LIBRARY 的状态空间组由
  `_load_state_space_library_group()` 动态从该 json 生成 — 加节点只注册 node_logic._reg 不会上画布!
  必须写进 json (含 x/y/w/h/color/params)。背景行 type=row_bg, 标题层语义 (S1/S2/S3/执行/🔭可视化/验证)
- **节点执行匹配**: 播放/单步走 node_logic.execute_node_logic(module, node, label), 按节点 name 匹配 _reg 的 matches 子串
- **双击 ≠ execute_node_logic**: 双击走 SimulinkModule.on_node_activated(node), 按 **params 标志** 分派
  (state_space_scope/state_space_rollout/video/subsystem/viz_kind…), 与 execute 是两套路由!
- 🐛 大坑: 带 `source` 字段的节点会被 on_node_activated 的"数据源切换"分支抢先拦截 → 双击变成切换数据源、不开窗。
  自绘窗口类节点必须加独占 params 标志 (如 viz_kind) 并把分派放在 source 分支**之前**
- 引擎轨迹: `module._ss_ensure_trace(force=True)` 跑 StateSpaceSim (~3s/331 步) → _ss_step_tr; 留存
  `_ss_last_sim` (引擎对象, sim.accel.probe 每 forward 更新)。**废弃旧坑**: 别再用 load_trained_left_brain
  覆盖 sim.accel.forward (parallel.FeedforwardAccelerator 已内置 npz+守卫+探针)
- 🔭可视化层 5 观察器 (2026-09-05 重排, 回路外底部行 y≈1560): 🧠直方图(ssff_hist)/🎯归因(ssff_attr)←⚡FF 探针;
  📊仿真波形(ssvideo)/🧭3D(ss3d_view)/🎥操作视频(ssvideo2)←🌍物理世界 (波形上游流形 3 线并入世界总迹 1 线减乱)
- 双击开窗统一入口: `_open_viz_node(kind)` (hist/attrib/scope/3d/video); hist/attrib 窗口单例挂 module._ff_hist_win/_ff_attr_win,
  node_logic 的 node_ss_ff_hist/attrib 执行时也优先复用 module 侧单例 → 单步与双击同窗
- 3D 视图: 工具栏 btn_ss_3d 与画布 🧭3D 节点双入口同调 open_ss_3d(); 状态空间画布内 on_infer_video → play_mlp_rollout (放现成 reports/*MLP*.mp4, 窗口类 MLPRolloutDialog, 不触发生成)
- 引擎探头: parallel.py probe = {obs, layers(每层 active/dim/act_l2/top3), out_contrib(W3·x3 归因), u_ff, act_raw(3×512 全量)}
- 工具栏顺序 2026-09-05: ▶运行 | 🔄重启(restart_sim=stop_sim+清 _ss_step_tr/_ss_step_order/_ss_last_sim/_ss_timer+start_sim) | ⏭单步 | ⚡引擎快演 | 🧮状态空间 | 🧭3D | ⏹停止 …

## 自动测试/报告入口
- GUI 取证: `gui-venv311/bin/python tools/gen_viz_evidence.py` (X 模式; 无 X 自动 offscreen, 3D 会 FAIL 如实记)
  序列: SimulinkModule() → open_state_space() (42 节点) → _ss_ensure_trace(force=True) → 先 _open_viz_node("hist"/"attrib")
  再逐帧回放 data/ss_insert_lerobot parquet 真实 obs (150 帧, MLP 真实 forward push 两窗) → scope: StateSpaceScopeDialog(_ss_tr)
  → 3D: open_ss_3d() 找 DreamView3D → video: play_mlp_rollout() 找 MLPRolloutDialog → grab 截图 + 内容断言 → reports/viz_evidence/*.png + viz_results.json
- 一键报告: `gui-venv311/bin/python tools/gen_verif_auto_report.py` → CLI 550 用例 (run_tree skip_slow) + GUI 取证
  → PDF 8 章 (第 8 章 🔭可视化证据嵌图) + Excel 8 sheet (Sheet8 可视化验证)。产物 reports/状态空间自动测试报告_<ts>.pdf / state_space_features.xlsx
- cv2 污染 Qt 插件 → 见 SKILL.md 坑节 (QT_QPA_PLATFORM_PLUGIN_PATH 指向 PyQt5/Qt5/plugins)

## 蒸馏 MLP 行为断言规格 (verification_layer t_ff_*, 与 zmax-left-right-policy 同源教训)
- 测 MLP 必须用训练域真实帧 (`_ff_frame(rng)` 从 parquet 采样), 手造稀疏 zeros obs = 分布外 → 饱和假失败
- 实证规格: 指向 100% / 幅值≤0.6 (容差 1e-3) / 夹爪按 d_xy<0.03 / 完成态 |u|≤0.3 / 单调 ≥95% / 近距 |u| 中位 0.03
- node_func_tree ssff 用例文字与源码映射行号同步更新; 改 parallel.py 后复核 _EXTERNAL_LOC 与"源码映射"用例
