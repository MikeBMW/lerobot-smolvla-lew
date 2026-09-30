# 🔭 可视化层节点 + GUI 自动取证 + 插入验收波形 (2026-09-05)

承接 ff-probe-visualization-2026-09-04 (探针/两节点/t-SNE)。本文件 = 可视化层收拢、
双击开窗机制、GUI 自动取证(真人测试工程师)、Scope 验收波形、引擎 0.5mm 精度改造。

## 可视化层布局与节点机制
- 状态空间画布节点**唯一数据源 = flows/state_space_obs.json**(左栏 LIBRARY 状态空间组由
  `_load_state_space_library_group` 读同一 json)。老倪"画布没有新节点" → 先查 json 是否
  append + node_logic `_reg` 注册 + **重启 studio.py** 三件事。
- 🔭 可视化层 = 画布底部 row_bg 一行 (回路外观察器), 收拢 5 类: 🧠直方图/🎯归因
  (源=⚡前馈加速器探针, 左组) + 📊仿真波形/🧭3D/🎥操作视频 (源=🌍物理世界, 右组);
  主链各行不再混挂观察器。连线按"语义观察对象"画, 观察器读引擎总迹/共享状态,
  连线是语义展示不是数据通道。
- **双击路由 = on_node_activated (simulink_module) 按 params 标志分派, 不是
  execute_node_logic!** 新可视化节点若只带 `source` 字段 → 被 :9175 "数据源切换"分支
  抢先 → 双击变切换、无窗口 (与 ssfeat/sstest verif_layer 同坑)。修: params 加
  `viz_kind` (hist/attrib/scope/3d/video) + on_node_activated 顶部统一分派
  `_open_viz_node(kind)` (必须放 source 分支前)。
- **可视化窗口数据前提 (老倪"打不开"主因)**: scope 需 `self._ss_tr` (仿真轨迹)、
  video 需 reports/*MLP*.mp4、3d 需 episode、hist/attrib 需 ff_probe (引擎末帧探针,
  在 `self._ss_last_sim.accel.probe`)。无数据双击 = 静默无窗 → **show_state_space_scope
  无数据时自动 `_ss_ensure_trace(force=True)` (引擎 ~3s) 再开窗** (双击必出波形)。
- 引擎 `_ss_ensure_trace` 曾用 `load_trained_left_brain` 覆盖 sim.accel.forward (旧闭包
  无探针无守卫) → 已废弃 (parallel.FeedforwardAccelerator 内置); 同时留存
  `self._ss_last_sim = sim` 供可视化层取末帧探针。
- **窗口单例挂 module 侧** (`_ff_hist_win`/`_ff_attr_win` 属性): 双击 (module._open_viz_node)
  与 ⏭单步执行 (node_logic fn, ctx["module"]) 必须同窗 — node fn 优先取
  `getattr(ctx.get("module"), "_ff_hist_win", None)`, 无 module 才落 node_logic 全局。
- ▶运行播放 = demo 模式 (execute_node_logic demo=True 不跑真实 fn) → 播放中探针不采集;
  ⏭单步/右键/双击 = 真实执行逐帧 push (窗口 FIFO 150 帧累积)。引擎先全跑完 → probe
  只留末帧 (单帧直方图 512 值仍可看, 已够取证)。
- **自绘 QPainter 高分屏字体重合**: QFont("Sans", N) 的 N 是 **pt**, 192 DPI 渲染 2x →
  布局逻辑坐标没放大但字形大 → 行内文字叠。修: 字号小档 (标题 8pt/正文 7pt) + 行距加宽;
  空态给引导文案 (双击没数据时窗口提示"先点 ▶运行 或 ⏭单步")。

## GUI 自动取证 (真人测试工程师模式, tools/gen_viz_evidence.py)
- 驱动序列: `SimulinkModule()` 无参直构 (不需 studio) → `open_state_space()` (42 节点)
  → `_ss_ensure_trace(force=True)` (StateSpaceSim ~3s/330 步) → 真实 obs parquet 回放
  150 帧喂 hist/attr (acc.forward → probe → win.push, MLP 真前向) → `_open_viz_node`
  每类开窗 → `grab().save(png)` + **非背景像素比断言** (PIL 灰度 >40 占比, 各窗口阈值
  0.002~0.01) → viz_results.json。8/8 PASS ~4s。
- 找顶层窗口按类名: 3D=`DreamView3D`, 操作视频=`MLPRolloutDialog` (play_mlp_rollout 存
  self._mlp_dlg), scope=`StateSpaceScopeDialog(tr)` 直构传 tr。
- **⚠️ cv2 Qt 平台插件污染 (真坑)**: verification_layer (import cv2) 先于 Qt 被 import →
  Qt 从 `cv2/qt/plugins` 加载 xcb → "Could not load the Qt platform plugin xcb... even
  though it was found" (cv2 自带插件缺系统依赖)。修: QApplication 创建前 (import Qt 前)
  设 `os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"]` = `<site-packages>/PyQt5/Qt5/plugins`
  (遍历 sys.path 找 platforms 子目录)。X 模式 (DISPLAY=:0) 3D GL 可 grab; 无 X 回退
  offscreen (3D 会失败, 诚实记录不造假)。
- 报告集成 (gen_verif_auto_report.py): main 里 `import gen_viz_evidence;
  viz = gen_viz_evidence.run_viz()` (内部 QApplication.instance() or new) → make_pdf
  第 8 章 🔭可视化证据 (reportlab platypus Image 嵌截图, wqy 字体) + Excel Sheet8
  (export_verif_excel(tree, results, viz=None) 加"可视化验证" sheet)。

## Scope 2x4 验收波形 (StateSpaceScopeDialog)
- 引擎 tr 需**全程序列** (io_trace 是抽稀的不够画全程): run() 每步 append
  `tr["mani_rem"]` (=−d_axial, 插深剩余 m) 与 `tr["mani_dperp"]` (=d_perp_norm 横向错位 m),
  init dict 同步加键 (有流形层 None 分支也 append 0)。
- 窗口 2x3→2x4: 原 6 通道 + "插深剩余 (mm) · 阈 0.5" + "横向错位 (mm) · 阈 0.5" 两格
  (mm 显示, y 从 0, 只画插入段窗口 = 剩余首次 <20mm 起, 0.5mm 红虚线+标注, 插入段
  时长文本); 底部大字验收摘要: "✅ 插入成功 · 插入段 0.44s (<0.5s) · 末横向错位
  0.04mm (<0.5mm) · 插深剩余 0.09mm"。自绘 drawText/fillRect 坐标必须 int。
- 性能流形几何 (manifold_layer): AXIS_HOLE≈(−1,0,0) (水平孔轴) → δ⊥ = 垂直孔轴的
  **yz 分量** (不是纯 y); 插深剩余 = −d_axial。诊断横向错位不收敛先分清 y/z 分量。

## 引擎插入精度改造 (0.5s/0.5mm 验收, 2026-09-05)
- 原状态: 插入段 0.38s (<0.5s ✓) 但完成时 δ⊥ 2.77mm / 插深剩余 1.46mm (完成阈
  insert_depth=4mm 太松, 孔壁只有 v[1]*=0.3 阻尼无主动对中)。
- 三步改 (state_space_sim.py run() 内):
  ① 入孔后 (grasped and peg_head.x < HOLE_MOUTH.x+0.001) **孔壁 yz 双轴对中**:
     x[1]/x[2] 指数收敛到 hole 对应值 (min(1, dt*25)), v 阻尼 0.3。
  ② **改 x 后必须 `self.peg = self.x + self.peg_off` 同步** — 否则 tr 里 peg−x 虚漂
     6.6mm 破坏夹持锁存断言 (t_F_A06 drift<1e-9), 且 3D/流形数据错。
  ③ 孔底物理止动: head_x ≤ HOLE_POS.x → x[0] 钳位到孔底 + v[0]=0。
- **完成阈 < 单帧步长陷阱**: insert_depth 0.004→0.0005 后单帧步长 (0.085m/s×0.02s
  ≈1.4mm) > 阈值 → depth<阈 永不连续成立 → 永不 done → 越孔底冲出 (插深剩余
  −188mm)。必须配物理止动。
- cognition.py: insert_depth 默认 0.004→0.0005, STAGE_V_CAP 插入 0.07→0.085。
- 结果: 12 扰动集 (±5cm/±1.5cm) done 12/12, 插入段 0.42–0.48s, δ⊥ ≤0.06mm,
  插深剩余 ≤0.4mm。验收用例 `VerificationLayer.t_accept_insert` (12 集统计断言) 注册
  FNaccept01 (ssworld funcs)。
- **t_cal_zerodiff = 提交纪律检查, 不是参数一致性**: 它 `git diff` 三个引擎文件
  (parallel/cognition/state_space_sim), 工作区有未提交改动即 FAIL — 改引擎文件后必须
  commit 才 PASS (不是 bug, 别去改测试)。

## 蒸馏 MLP 断言规格 (测试重写, 老倪"只看最终插入")
- **手造稀疏 obs (np.zeros(43)+只填 pos/target) 对 MLP 是分布外**: 归一化后全零段 =
  极端输入 → 输出饱和 (三轴全 clip 0.6 → |u|=1.039) → 旧解析律断言假失败 (t_ff_zero/
  t_ff_kp/t_F_B02 等 6 个 FAIL 全因此)。**断言一律用训练域真实帧** (parquet 随机采样,
  verification_layer `_ff_frame(rng)` helper, 函数内 import numpy — np 只在 t_* 注入)。
- 实证规格 (26942 帧): 指向目标 100% · 速度段 ≤0.6 100% · 夹爪按 **d_xy<0.03** 规则
  (3D 距离大但 xy 已对中时闭爪=垂直接近准备态, 属正常, 别用 3D d 断言"远距误闭") ·
  完成态 pos=target |u|≤0.3 (p95 0.124; 蒸馏不保证精确 0, 精停由完成判据接管) ·
  误差大→动作大 ≥95% (实测 97.4%, 统计阈值别写 100%) · 限幅断言容差 1e-3 (float32
  clip 边界 0.60000002)。
- 术语: 功能清单/用例文字 peg→光模块 (用户可见文本全换; metaworld 任务名
  peg-insert-side-v3 与 39D 键名 hand/peg/hole 段保留=环境/代码绑定)。
