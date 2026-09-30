# 状态空间画布可视化层 + 节点双击/执行机制 (2026-09-05)

> 2026-09-04 老倪:「重新布局, 增加可视化层…画布简洁连线简单」+「可视化层节点双击要打开
> 显示窗口」+「工具栏按钮精简」。前台会话可把本文件要点合并进 SKILL.md。

## 画布 = flows/state_space_obs.json 唯一数据源 (新节点必须写 json!)
- 状态空间画布节点/连线/行背景全来自 flows/state_space_obs.json (nodes/links/row_bg)。
  只在 node_logic._reg 注册 **不会** 出现在画布/左栏模块库 — 左栏「🧮 状态空间模型 (N节点)」
  组也由 _load_state_space_library_group (simulink_module.py ~L947) 读同一 json 生成。
- 加节点三步: ① node_logic._reg(key, matches, doc, fn) ② json nodes[] 加条目
  (id/name/x/y/w/icon/params.state_space=true) ③ 需要连线就 links[] 加 {f,t,f_port,t_port,label}。
- 行背景 row_bg: 主链行 w=3000 全宽, 回路外行可 w=1150 只盖节点区; y 行距 ~200-240,
  节点 y = bg y + 40。布局前先跑碰撞检测 (遍历 nodes 排除 row_bg)。

## 双击 = on_node_activated 按 params 标志分派 (不是 execute_node_logic!)
- simulink_module.SimCanvas 节点双击 → scene_ref.on_node_activated(node) →
  按 node["params"] 的标志串行 if/return: verif_layer (最前) → viz_kind → 物理世界 →
  state_space_scope → state_space_rollout → video → subsystem → run_env → source(数据源切换)
  → switch/mode/train_gate/yolo_gate/coord_overlay/skill/scene/insert_video/infer_rollout/
  eval_state_space/… → 默认参数框。
- 🐛 大坑: **params 带 source 字段的节点会被"数据源切换"分支抢先拦截** (双击变切换,
  表现=「双击没反应/不开窗」)。任何新交互节点必须: json params 加专属标志 (如 viz_kind)
  + on_node_activated 分支插在 source 分支 (L9175) 之前 — verif_layer 分支就是为此放最顶。
- ▶运行播放 tick 调 execute_node_logic(demo=True) → _demo_node_output 只读 DataWorld 帧
  (不跑真实 fn, 防 YOLO/LLM 冷加载卡播放); ⏭单步/右键运行 = demo=False 真实执行
  (断点可进); execute_node_logic(module, node, label, demo) 首参 module=SimulinkModule,
  ctx["module"] 可调其方法 (如 open_ss_3d/on_infer_video) — 画布节点打开 GUI 窗口的正路。

## 🔭 可视化层 (2026-09-04 布局, 5 观察器收一行)
- 新增底部 row_bg「🔭 可视化层 · 观察器 (回路外, 不参与控制)」y=1520 + 5 节点 y=1560:
  🧠前馈激活直方图(1150)/🎯归因·分工(1410) ← ⚡FF(源 1140) / 📊仿真波形(1880)/🧭3D视图
  (2170)/🎥操作视频(2480) ← 🌍物理世界(2420)。源与观察同列/近列 → 连线垂直不交叉。
- 可视化节点连线 = 语义 (节点执行读 _SS_STATE/引擎, 不真走连线数据); 仿真波形上游原 3 条
  流形线并入「世界→波形 引擎总迹」1 条 (流形/潜空间数据在 io_trace 总迹里), 连线大减。
- 执行 fn (双击分支/单步): node_ss_ff_hist / node_ss_ff_attrib / node_ss_3d_view / ss_scope
  (node_ss_scope) / ss_video (node_ss_video); 3D/视频 fn 里 label=="▶运行" 跳过弹窗
  (防断点冻结时窗口关不掉, 双击才弹)。

## 直方图/归因窗口 (ff_hist_view.py / ff_attrib_view.py)
- 数据源: node_ss_s2 (⚡FF 执行) 每 tick 把 accel.probe 存 _SS_STATE["ff_probe"]; 引擎侧
  sim.accel.probe 每引擎步更新 (FeedforwardAccelerator 内置, probe=None 时零开销)。
- probe 结构: obs(手/目标/d) / layers[3](active/act_l2/top3) / out_contrib[3](W3·x3 归因
  top 单元) / u_ff / act_raw (3×512 全量激活, 画直方图/散点用)。
- 窗口单例必须统一到 module 侧 (module._ff_hist_win / _ff_attr_win): node fn 与双击
  _open_viz_node 都先 getattr(ctx.module/"self") 复用, 否则单步开的窗和双击开的窗是两个
  (数据各累积各的)。
- 双击开窗但没数据 → 空态提示「运行 ⚡前馈加速器后自动累积」, 不造假; _ss_last_sim
  (引擎 sim 留存) 有末帧 probe 则填入。引擎 _ss_ensure_trace 曾用 load_trained_left_brain
  覆盖 sim.accel.forward → 探针停更 + 守卫失效, 已删 (parallel 内置 npz+守卫+探针)。
- 窗口绘制模式: QPainter 自绘深色面板 (#0d1117 系), QDialog + 节流 QTimer(100ms) 重绘;
  直方图 64 bins + x=0 ReLU 截断虚线 + 最近帧朱红叠加; 归因堆叠 4 输出维通道色
  (朱红 dx + 灰阶 dy/dz/gripper — 分析图允许多通道色, 监控面板才守单色纪律)。
- 单元功能散点: 每单元=150 帧激活 profile (512×N, 每帧中心化) → PCA(SVD, 即时) 或
  t-SNE; gui-venv311 无 sklearn → 纯 numpy exact t-SNE (perplexity 30, ~400 iter,
  512 点 ~2s; 梯度向量化 4·(Y·ΣA − A·Y), A=(P−Q)/(1+Dq); 传矩阵方向 = 单元×特征 勿转置)。
  颜色 = argmax|W3[:,j]| 静态分工 (它听哪个输出维), 点大小 = 平均活跃度。

## 工具栏按钮删改模式
- 只删 mk_btn 创建行 + tl.addWidget 行; **底层方法保留** — on_z_analysis 还被自动测试
  流程调用, open_ss_3d 被画布 3D 节点执行调, open_topsys 被 flow 双击块展开用。
- 删前 grep 全引用 (self.btn_xxx 残留 → AttributeError); 删除留注释 (日期+原因+方法去向)。
- 老倪可反悔: 3D 视图按钮删了又要求恢复 → 双入口 (工具栏 + 画布节点) 同开一个方法, 安全。
