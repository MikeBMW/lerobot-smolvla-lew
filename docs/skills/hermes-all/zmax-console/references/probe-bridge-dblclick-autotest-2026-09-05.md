# ▶运行实时探针桥 + 真实双击链路 + 一键测试 GUI 演示 (2026-09-05 尾段)

承接 viz-layer-nodes-gui-autotest-2026-09-05.md (可视化层/取证/0.5mm 验收已覆盖)。
本文件 = 该会话最后三轮的增量: 老倪"点运行后直方图没内容 / 其它窗口打不开 /
双击无法打开新窗口 / 一键自动测试要自动操作窗口显示波形真实跑一遍"。

## ▶运行 后窗口实时数据 = probe 桥 (直方图"没内容"根因)
- 直方图数据源 = 引擎 sim 的 `accel.probe`。▶运行 两条路径 (`_start_state_space_sim`
  快演 / `_start_real_sim` 真实化) 都**不存 sim 引用** — 只有单步/取证走的
  `_ss_ensure_trace` 存 `self._ss_last_sim` → 运行完双击 hist = 空窗。
  修: 两条路径创建 sim 后都 `self._ss_last_sim = sim` (真实化 = RealStateSpaceSim,
  自建 parallel.FeedforwardAccelerator 带 probe)。
- ⚠️ `_start_state_space_sim` 里还残留一份 `load_trained_left_brain` 覆盖
  sim.accel.forward (旧闭包无探针无守卫) — 与 `_ss_ensure_trace` 曾有的同款, 一并删。
  原则: 任何把 forward 换成旧闭包的点都会停探针 + 去守卫。
- probe 帧序号: `mlp_ff_forward` 每次 forward `probe["_seq"] = probe.get("_seq",0)+1`。
- **桥**: module `_ensure_ff_bridge()` = QTimer 300ms `_ff_bridge_tick`: 从
  `_ss_last_sim.accel.probe` 读, seq 与上次不同才 push 给已开的 `_ff_hist_win` /
  `_ff_attr_win` (去重)。开 hist/attrib 窗时启动一次 (幂等)。效果: 真实化运行中
  (每步 ~1s) 直方图逐帧动; 快演 (引擎先全跑完, probe 停末帧) 桥推一次末帧 → 有内容。
- 真实化 run 在 daemon 线程, 主线程桥读 probe dict — GIL 下单字段读安全
  (worker 线程禁 QObject 是写 UI, 读共享数据 OK)。

## 真实双击链路验证 (别只调 _open_viz_node 假验证)
- 画布节点真实双击 = `SimNodeItem.mouseDoubleClickEvent` →
  `item.scene_ref.on_node_activated(node)` (scene_ref 即 module)。验证开窗必须走这条
  路径 (等价鼠标双击) — 直接调 `_open_viz_node` 绕过了 on_node_activated 的分派顺序,
  viz_kind 是否被前面分支抢先只有走真实路径才暴露。
- ⚠️ 画布节点 **id 加载时被重生成** ("节点 id 加载时被重生成, name 稳定") —
  验证/定位节点用 name (含子串匹配), 别用 json 里的 ssff_hist 等 id。
- 顶层窗口按类名找: FFHistView/FFAttribView/StateSpaceScopeDialog/DreamView3D/
  MLPRolloutDialog。老倪"都打不开"最常见 = **旧进程** (改 node_logic/simulink_module/
  json 后没重启 studio.py) — 先确认进程再谈代码; 本会话实测代码修复后 5 窗全开 +
  引擎跑完直方图自动有内容 (桥 seq=330)。

## 一键自动测试 = GUI 演示段先行 (真开窗、真跑、看得见波形)
- Test 节点右键「⚡ 一键自动测试」→ `_run_auto_test` 先跑 `_auto_test_demo`
  (on_done 里才起后台报告子进程, 原 worker 逻辑不变)。
- demo = 主线程 `_oneshot` QTimer 链: ① `_ss_ensure_trace(force=True)` 引擎真实跑 →
  ② show_state_space_scope 开窗 → ③ hist 开窗 + parquet 150 帧喂 (MLP 真前向) →
  ④ attrib 开窗 + `_project("pca")` → ⑤ open_ss_3d → ⑥ play_mlp_rollout; 每窗停留
  1.2–1.5s (用户看得见) + grab 存 reports/viz_evidence 证据 → 完成日志 → on_done()
  起 worker 跑全量用例 + 报告 PDF/Excel + scp 上传。
- 铁律: GUI 演示/取证必须在**主线程** (QTimer/信号链) — worker 线程禁 QObject
  (崩溃铁律); 子进程 (gen_verif_auto_report) 里的窗口一闪而过用户看不见,
  不满足"真实的跑一遍"。
- 主线程 QTimer 回调里 time.sleep(≤1.5s) + processEvents 可接受 (单窗停留)。
