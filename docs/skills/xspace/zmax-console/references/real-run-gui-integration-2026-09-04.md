# GUI 状态空间 ▶运行 = 真实化流程 (2026-09-04, 老倪: "YOLO 是不是假的? 改成真实流程, 每一帧都要渲染, 不能造假")

## 背景: 为什么老倪连问三次"YOLO 是不是假的"
- GUI 状态空间画布 ▶运行 原走**引擎简化世界** (state_space_sim.py): 500 步纯 numpy
  <0.1s, 每步 fuse_sensors; YOLO detect_3d 只在引擎跑完后 `_real_yolo_sense_once` 采样 **1 次**。
- **引擎轨迹 (io_trace/dw) 里「🎯 YOLO 目标检测」「📐 2D→3D 解算」节点的快照 =
  引擎几何直读** (_io_snapshot: YOLO out 的 xy 用 self.peg/HOLE_POS, conf "--";
  2D→3D out = 引擎 peg/hand/hole) — 本质是引擎真值包装成检测输出 = 老倪眼中的"假"。
- 播放轮转 ss_yolo 节点用 _YOLO_CACHE 真实值 (仅展示 1 帧), 播放/单步不进 detect_3d
  (v3.4.8 demo 轻量路径设计使然 — 防冷加载卡顿)。
- **老倪红线 (2026-09-04 二次纠正)**: "每一帧都要渲染, 不能造假" / "我要看真实的
  yolo 感知的效果" — 任何节流/冻结/复用旧值顶替检测都是造假。真实化视觉模式必须
  **每步 render() → detect_3d** (~0.5-1s/步 × 500 ≈ 5-9 分钟/轮, 接受)。

## GUI 接入 (commit d9fac620)
- `simulink_module.start_sim` 状态空间分支: **默认 `_start_real_sim()`** (真实化);
  仅当工具栏「⚡引擎快演」QCheckBox 勾选才走 `_start_state_space_sim()` (引擎 0.1s 演示,
  供快速演示/训练数据用)。工具栏 btn_run 旁 addWidget QCheckBox (tooltip 写清两模式区别)。
- `_start_real_sim()`: `threading.Thread(daemon)` 跑 `RealStateSpaceSim(seed=100, vision=True,
  vision_every=1)` → run(); 完成后写 `self._real_tr = ("ok", tr, sim, 检出率)`。
  **SimulinkModule 无类级 pyqtSignal → QTimer(400ms) 轮询 `self._real_tr` 最简可靠**。
  ⚠️ 线程内访问 `self._real_sim_ref = sim` 保引用防 GC; run() 纯 numpy/metaworld 无 QObject,
  后台线程安全; VSCode F5 断点命中在后台线程 (同进程 pydevd), GUI 主线程不冻结。
- `_real_finish(tr)`: `DataWorld(tr)` → 节点 reset → `_ss_tick` 播放 — **复用引擎播放路径**,
  前提: RealStateSpaceSim 的 io_trace 每帧含 **13 模块 io_snapshot** (模块名 key 与引擎
  _io_snapshot 同构: 📦数据源/🎯YOLO/📐2D→3D/🖐触觉/📡融合/⚡前馈/🔮估计/📈预测/🧪校正/
  🧭调度/🛡限幅/🤖执行/🌍物理世界) → 画布播放/3D/总线零改动复用。
  - YOLO/2D→3D 节点 out = **真实检测值** (每帧 detect_3d 结果或编码器 hand, 不再写引擎几何)。
- `stop_sim` 加: 停 `_real_poll_timer` (daemon 线程跑完即弃, 无 QObject 安全)。
- 改 GUI 代码后必须重启 studio.py (F5) 生效 — 老倪当场验证"还是假的"就是因为旧进程没重启。

## 可视化交付 (老倪要看真实感知效果)
- `tools/gen_real_yolo_video.py <seed> [max_steps]` → `data/real_yolo_perception_<seed>.mp4`:
  逐帧渲染图 + YOLO 2D 框 (hand/peg/hole 彩色, conf + det3d 3D 坐标标签) + 顶栏状态
  (step/阶段/夹持/grp) + 底栏控制值 (hand 编码器 / peg 视觉 / hole 视觉), ffmpeg 8fps 合成。
- 实现要点: monkey-patch `sim._vis_refresh` 收集每帧 (step, img, vis dict, sim 状态快照) —
  状态条必须用**帧快照**不是末态; `yolo_state_aligner.detect_3d` 加 `self._last_res/_last_img_rot`
  缓存 (画框免二次 predict, 无害); 框坐标在 rot90(k=2) 帧 → 转回原图 (180°: u'=W-u)。
- 任务失败的视频也是交付物 — 固定相机夹爪遮挡 → peg 检测崩 (26-48mm) 真实呈现,
  是 RealityGap 实证; 真机解法 eye-in-hand 相机, 不掩盖。

## 相关
- 真实化闭环全部契约/探针/基线: mlops/zmax-real-closed-loop 技能
- GUI 断点调试根因 ①-⑦: SKILL.md VSCode 断点节 + references/vscode-breakpoint-*.md
