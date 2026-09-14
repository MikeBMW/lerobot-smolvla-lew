---
name: zmax-state-space-architecture
description: "Use when 状态空间画布 debug — 字段来源(预定义vs预测), 教学解析层vs真实权重, 节点源码映射."
---

# Z-MAX 状态空间画布架构与源码溯源

状态空间(状态空间仿真画布)是 left_right 双脑策略的仿真蒸馏版。用户(老倪)反复 debug
此区域, 高频问题: "某字段是预先定义还是模型预测的?" / "为什么两个模块源码一样?" /
"这是不是写死的?"。本技能是溯源方法和架构事实。

## 分层模型 (谁产生什么)
- **感知层** (state_space/perception.py, tools/gui/state_space_sim.py): 构造 obs。
  仿真里 target/孔位 = **HOLE_POS 预定义常量** (metaworld goal) + `_stage_target()` 阶段子目标,
  由感知层写进 obs[36:39]; 真机同构 (gen_insert_video.py) = `aligner.detect_3d`(YOLO 检测+3D
  反投影解算) 写 obs[36:39]。
- **并行层** (state_space/parallel.py): FeedforwardAccelerator (obs→u_ff) + AdaptiveStateEstimator
  (递归潜状态+卡尔曼)。**只读 obs, 不产 target**。
- **认知层** (state_space/cognition.py): 调度器 u = w_ff·u_ff + (1−w_ff)·u_fb + 状态机。
- **世界模型 (右脑 RightBrainWM)**: 只预测 next_obs + contact 概率, **不产出 target**。
  target 是任务目标(先验), 世界模型是动力学 — 语义两码事, 别混淆。

## 教学解析层 vs 真实权重 (识别"模拟伪装")
- `state_space/parallel.py` 的两个类 = **画布教学解析式, 全仓库零引用** (仅画布/验证脚本用):
  前馈加速器 = 手写 Kp·(target−pos) 限幅公式 (注释自称"等价于训练后学的" = 示意, 非真);
  状态估计器 = 线性卡尔曼 A=0.95/K=0.5 (非训练 GRU)。
- **真实训练权重前馈**: `tools/gui/state_space_sim.py::ff_forward` — 从 npz 加载 W0-3/b0-3 +
  归一化参数 (sm/ss/am/astd) 做真 MLP 前向; `tools/ss_verify_trained.py` 加载 LeftBrainMLP
  权重替换 FeedforwardAccelerator 做闭环验证。
- 通用判别: 手写解析公式 + 注释声称"等价于训练后学的" = 教学/画布层; 真权重必有 npz/pt
  加载处 (outputs/rl_peg/full_pipeline.pt 或 state_space_sim npz)。

## 画布节点源码展示机制 (tools/gui/node_logic.py + node_logic_dialog.py)
- **执行层可共用分派函数**: 多个节点 _reg 注册同一 node 函数, 靠 `"关键词" in name` 分派
  (ss_ff/ss_est 共用 node_ss_s2, "估计"→AdaptiveStateEstimator, 否则 FeedforwardAccelerator)。
  这是设计, 不是 bug — 但会让"看源码"看起来重复。
- **编辑器源码展示优先级**: `node_logic_dialog._load_source` 先 `get_external_source(key)`
  (_EXTERNAL_LOC 按符号截取真实类源码, 只读), 无映射才回退 `get_node_source(key)`
  (返回注册的 node 函数整段)。**每个节点 key 都应挂独立 _EXTERNAL_LOC** — 两个节点
  显示同一段 = 缺映射或映射指向同符号。验证: `get_external_source(key)` 首行应为各自类名,
  不是 `def node_ss_s2`。
- 改 node_logic.py / _EXTERNAL_LOC 后必须重启 studio.py (旧进程跑旧代码)。

## 调试铁律
1. **"预定义还是预测"类问题 → 追字段的写入者**: 谁构造 obs / 谁写 [36:39] (感知层?
   仿真真值? YOLO?), 不是读它的 forward。forward 被动读 obs, 回答不了来源。
2. **"两个模块源码一样" → 先跑 `get_external_source(key)` 对比首行**, 再判断是缺映射还是
   共用分派函数, 别猜。
3. **画布节点"真实执行"必须完整闭环**: 分派分支里只调 predict 不调 update (卡尔曼校正没
   执行) = 名不副实 — 2026-09-02 已修 node_ss_s2 估计分支 (补 obs39 z_k 校正闭环, 日志打
   predict 与 update 两步数值; 手算验证匹配)。
4. 改完 GUI 代码必重启 studio.py; 验证逻辑用 gui-venv311/bin/python (项目无 .venv)。

## 🧮 流形层逐帧发布闭环 (2026-09-03 老倪: "为什么流形/潜空间没有输出连线")
- 回路外元层此前只读日志、无输出 → 半吊子。闭环: 引擎 run() 每步实算流形量
  (decompose/evaluate 纯 numpy, ~0.1ms) → tr["mani_risk/progress/eta/V"] 全程序列
  + _io_snapshot 发布 3 个 channel ("🧮 接触流形"/"🧮 性能流形"/"🧮 潜空间",
  out=进度/偏离/V·状态 | δ⊥/插深/V_p/η | 潜坐标/速度场 prior−x̂₋)。
- data_world.MODULE_ORDER 14→17 键 (物理世界后 append 3); 数据总线/3D 自动带出。
- StateSpaceScopeDialog 2x2→2x3 六格 (+ 法向偏离 #ff7b72 / η #a371f7), 画布连线
  ssmani_c→ssvideo(in2)/ssmani_p(in3)/sslat(in4) + 节点 outputs=["out1"]。
- 引擎加载流形: _find_mani_file/_load_manifold (module 名 state_space_mani, 缺失不阻塞)。
- 铁律: 回路外分析节点输出必须"有去向" — 要么进数据世界逐帧发布, 要么明确只读标注;
  禁止无输入也无输出(孤立)与有输入无输出(断头)。连线不改执行 (状态空间跑引擎拓扑)。

## 🧩 验证层 (2026-09-03 老倪: 系统要能逐个验证)
- 真源: src/lerobot/verification/verification_layer.py — FEATURES 注册表 (45 项:
  35 自动 F-A01~F-F04 + 10 GUI 手动 F-G01~G10) + **FEATURE_META (v4.0.1, 并行 dict:
  fid → (基本功能|泛化功能, 感知模型|世界模型|决策控制|规划推理|安全机制|引擎|数据平台|标定工具|GUI工具, 模型特点))
  — 加在文件末尾 main() 前 (勿插 FEATURES 后: 会错位 _EXTERNAL_LOC 行号锚点 47/97)**。
  list_features() 返回 dict 列表含 kind/role/spec (GUI 对话框/Excel 导出复用)。
- VerificationLayer (t_F_* 断言, 引擎跑一次缓存 tr; 六层/标定/流形 importlib 直载)。断言全部按源码契约手算可核。
- 画布: 底部「🧩 验证层」row_bg + 🧩 Feature 功能清单 (ss_feature) / 🧪 Test 用例执行
  (ss_test) — **v4.0.1 起双击/右键 = VerificationDialog (tools/gui/verification_dialog.py):
  45 项分类表格 + ▶运行全部测试 (后台 skip_slow) + 导出 Excel (3 sheet, scp 上传)**;
  单跑 ZMAX_VERIF_ONLY=F-xx; CLI tools/ss_feature_tests.py --list/--only/--skip-slow。
  ⚠️ ssfeat/sstest 带 source 字段 → on_node_activated 的 verif 分支必须在最顶部 (0.0),
  否则被数据源切换分支抢先拦截。
- 域: A引擎闭环7 (八阶段/收敛3.08mm/速度伺服0.211/台面/夹持/接触) B六层11
  C感知4 (YOLO 真检出3类 conf~0.95) D规划3 (离线规则) E元层5 (三域/潜空间PCA 2D@95%/
  流形) F画布4 (38节点10层/_EXTERNAL_LOC 35条/io_trace 14键=MODULE_ORDER)。
- 坑: 引擎 tr["u_sat"] 标量; 画布 io 键 "🛡 安全限幅"≠节点名"安全执行边界";
  行号映射随源码增行会漂 (F-F03 校验 ±3 行容错); YOLO 用例需 DISPLAY。

## ▶运行/单步/右键 执行语义 (2026-09-03 老倪: "运行状态空间后 detect_3d 没进" 根因)
- **▶ 运行 = 引擎仿真 + demo 播放, 不执行任何节点真实函数**:
  ① `_start_state_space_sim` (simulink_module.py) 只真执行名含"数据源"的节点;
  ② `StateSpaceSim.run()` 纯 numpy 引擎 (简化世界, 无 metaworld/无图像);
  ③ `_ss_tick` 播放每节点 `execute_node_logic(demo=True)` → `_demo_node_output` 只读
  DataWorld 帧数值展示 (v3.4.8 为防 YOLO/LLM 冷加载 1.6s+ 卡播放)。
- **⏭ 单步 / 右键"运行节点" = 真实执行**: `execute_node_logic(demo=False)` →
  node_ss_yolo → `_yolo_ensure_aligner`(best.pt + metaworld env) → `_yolo_capture` →
  `aligner.detect_3d` — 断点可进 (ZMAX_DEBUG_BREAK=YOLO 只停该节点)。
- **引擎 io_trace 曾写死伪装 (老倪红线)**: state_space_sim._io_snapshot 的
  "🎯 YOLO 目标检测" out 写死 "conf 0.99"、坐标抄仿真 peg/hole、hand 抄 peg → 总线/播放
  显示假检测。2026-09-03 已改 conf "--"(引擎无 YOLO 模型, 诚实标注) + hand=末端 self.x、
  peg=独立物体 self.peg (原误用末端当 peg)。
- **真实 YOLO 采样一次 (2026-09-03 落地)**: simulink `_real_yolo_sense_once()` —
  ▶运行/单步/右键同源, 引擎跑完对 ss_yolo 节点 execute_node_logic(demo=False) 一次:
  detect_3d 断点可进 + 真实 conf/3D 日志; `_demo_node_output` 对 ss_yolo 节点优先展示
  缓存真实值 "(真实YOLO采样)"。
- **⚠️ 勿把真实采样注入 io_trace**: 引擎是简化世界 (HOLE_POS y=0.462), 真实 detect_3d 是
  metaworld seed0 世界 (hole y=0.671) — 坐标不同源, 混进同帧自相矛盾。真实值留
  _YOLO_CACHE + 日志/演示展示, 引擎帧保持自洽。
- **YoloStateAligner.detect_3d 不带 conf**: node_logic `_yolo_detect2d` (同帧同预处理
  rot90+BGR 二次 predict) 补真实 conf/框, 存 `_YOLO_CACHE["det2d"]` (det3d 存 3D)。

## 🧮 标定层三域 + 潜空间节点 (2026-09-03 老倪: 潜空间=流形地图, 世界模型=导航仪)
- 标定层从引力/斥力二分 → **三域**: ATTRACTION(动作)/REPULSION(状态预测)/
  LATENT_CALIB(潜空间 — 世界模型预测流形): latent_dim=4(位置3+预测力1)/state_dim=39/
  manifold_kind=flat-linear/flow_kind=const-vel/force_ch/prior_A=1.0(latent_dim 改维=
  重构卡尔曼, 只标定+校验不写引擎字面量; prior_A 从斥力域迁入潜空间域, 引擎写回锚点
  PriorDynamicsPredictor(A= 单源不变)。
- 画布: 标定层 row_bg 更名「🧮 标定层 · 引力/斥力/潜空间」+ 新增「🧮 潜空间 · 世界模型
  流形标定」节点 (ss_lat, node_ss_lat): 真执行 — 引擎轨迹 39D 观测 PCA → 有效维@95%/99%
  (实测 2D@95%/4D@99%: 任务路径低维嵌入, 孔/姿态常量维无方差) + 潜坐标/速度场
  (prior−x̂₋) 取 tr 真实 latent_vec/prior_vec; 校验标定潜维 vs 引擎实际。双击/右键走
  标定面板/表格 (含潜空间组: 维度 spin/力通道 checkbox/prior_A)。
- 🐛 tr["u_sat"] 是**标量范数** (float) 不是向量 — node_ss_calib/面板取速度勿 [:3]
  索引 0-d 数组 ("too many indices", 既有 bug 被 try 吞, 09-03 已修)。
- 🧮 流形层 已更名 **流形导航层** (测地线地图视角): 流形=潜空间地图, 节点=地图导航读数。

## 🧮 流形导航层 (2026-09-03 老倪: 光模块精密插拔 = 低维流形上的运动; 回路外几何元层)
- 拓扑: state_space_obs.json 底部 y≈1040 「🧮 流形层」row_bg + 两 model 节点
  (ssmani_c 接触流形 x240 / ssmani_p 性能流形 x640), 无连线, 不进引擎 io_trace。
- 源码: src/lerobot/manifold/manifold_layer.py (与 calibration/ 同级) —
  ContactManifold (L51) / PerformanceManifold (L124); 常量 HOLE_POS/HOLE_MOUTH/
  PEG_HEAD_OFF 与 state_space_sim.py 逐字同源 (别改单边)。
- 数据真源: node_ss_mani 从 module._ss_tr 当前帧取 tr["x"/"peg_head"/"target"/
  "v_vec"/"stage"] (node_ss_calib 同款 idx=_ss_round); 无轨迹 → 提示先 ▶ 运行。
- 接触流形数学: e=T−hand (x 通道=e=peg_head−HOLE_POS); 通道轴按阶段 —
  下降/抓取/抬起=z 垂直, 插入=工艺斜线 AXIS_INSERT (孔口上方悬高 2cm→孔底,
  ≈(−0.957,0,−0.29)), 完成=孔轴 x; progress=‖e∥‖, risk=‖e⊥‖, V=½‖e‖², V̇=−e·v;
  状态=risk vs RISK_TH (下降/抓取 0.03=engine 抓握接触容差, 插入/完成 6/4mm)。
- 性能流形数学: δ=销头−孔底 → V_p=½δᵀWδ (W=diag(0.4,1,1), 横向重权),
  η=exp(−V_p/σ²) σ=0.004 (高斯光束近似 — 是模型非光功率计实测, 真机标定 W/σ)。
- 实测语义 (引擎 305 步): η 全程≈0 到完成段 0.57→0.77 (没插好光路不通);
  插入段起始带 ~10mm 工艺偏离被如实标红后收敛 (引擎 D_CONTACT=2cm 提前切插入)。
- 坑: engine stage 名带推进后缀 ("下降 · 接触") → _stage_name 清洗主阶段;
  接近/对位/转移=空中自由运动归 CHANNEL_FREE (误当 z 通道会全程误报离流形)。

## 🧠 右脑 WorldModel 蒸馏接入 (2026-09-06, commits 2283efbb + 74405273)
- 训练右脑 = RightBrainWM (modeling_left_right.py): obs39(raw)+act4(raw) → next_obs + contact
  (enc 2×256 MLP, **非 GRU** — parallel.py 注释"A≈GRU W_hh"是教学类比)。角色对应链路
  世界模型/先验 (dynamics.py PriorDynamicsPredictor), 不是卡尔曼估计器 (est 是估计器)。
- 导出: tools/export_ss_right_brain.py (ckpt→npz, 自动测定 pred_next 量纲=归一化空间
  需反归一化 *ss+sm, numpy vs torch 对照 MAE 5e-8); models/ss_right_brain.npz 不入库
  (同 ss_left_brain)。**坑**: state_space lerobot 训练只优化 left action loss, 右脑
  近随机 (contact acc 0.721 无区分度近0.519/远0.511) — 导出前必实测质量!
- 重训: tools/train_ss_right_brain.py — 引擎域数据 (ss_insert_lerobot, next=同ep下一帧,
  contact=手obs[0:3]-peg obs[7:10]<5cm 自建标签) → next 位置误差 0.1cm + contact acc
  1.000 (近1.00/远0.00)。**训完直接导出 npz (同结构)**; best.pt 在 outputs/rl_peg/。
- 接入: dynamics.contact_of(obs,act) (逐通道域检 4σ + wm contact; 域外 None) → 引擎
  contact_p = max(经验残差公式, 右脑真权重) — 抓取时机由训练模型主执行, 教学公式兜底。
- **实测否决 pred_next 位置先验主执行**: 引擎纯积分动力学线性先验即最优 (u→位移精确),
  右脑 1cm 级实时残差反而加噪 (残差 0.108 vs 0.0485, 状态机卡对位)。wm 位置先验能力
  保留 (predict obs=), 待真实物理/非积分动力学场景启用; real sim 布局漂移域外
  use_wm=False (同 accel 强制解析)。验证: 引擎 8 阶段 done 无回退, 残差复原 0.048。

## 🚀 L3 扩展: 插拔+AOI 闭环任务链 (2026-09-08, commit 74ffbb95)
- 状态机 8→13 段: ActionModulator.STAGES 尾部追加 拔出/AOI转移/AOI检测/回程/放下/完成
  (插入后按 mode 分流: "insert"=直接完成 (回归默认) / "full"=插→拔→AOI→回放闭环)。
  sim_real 用 mode 参数或 SS_MODE env; GUI 默认 insert (演示基线), full 待 GUI 开关接线。
- **AOI 工位 = 台面固定标定设备** (AOI_FOCUS 常量, 3D ss_dreamview 同源常量勿改单边):
  光模块头悬停镜头对焦点保持 25 帧 = 采图; 检测报告 = **真实过程指标代理** (不造假):
  插入残余深度最小 / 接触力峰 / 回抓次数 → PASS 阈值 (深度<8mm & 力峰<1.0 & 无回接近);
  _meta 带 aoi_focus/mode/aoi_report (3D 画设备/演示消费)。光学判定留真机 AOI 接口。
- **拔出两段式**: ①沿孔轴反方向水平拉出 (depth>pull_out_m 脱孔) ②垂直抬离孔口
  (pull_clear_h → 平移不刮盒); 与插入段①同款"引擎切目标, advance 等证据"模式。
- **放件流程**: 放下段 z_stall 触台 (z_stall 统计须含"放下"段! 只算下降/抓取会永不触发
  — 09-08 实锤) → _drop_ready 开爪指令覆盖 → 观测爪开 → placed → 完成。
- 🐛 已踩: AOI转移 判据曾用"到对焦点距离<2cm"但目标是**悬停点** (focus+0.08) → 永远
  等不到卡死; 判据目标必须与 _stage_target 目标同点 (引擎几何到位事件驱动更稳)。
- 夹持回退范围 RETREAT_LO..HI = 4..10 (排除「放下」: 放件主动开爪非滑脱)。
- 画布: DiT(ssdec) y-610 回 L3 行 (v5.2.0 设计位); VLM→DiT 主输入 in1 (潜空间 z,
  接触流形让位 in3, 性能流形 in2); DiT 双下行通路 lkdc_ff→ssff (前馈=肌肉记忆固化点)
  + lkdc_act→ssact (执行端直通)。node_logic: VLM 识别 AOI 设备/报告 + DiT 双通路
  教学标注, 真实权重推理接入点 = smolvla_lew 容器/远程 (模型引擎三模式)。
- 实测: R0 mode=full seed101-104 全链闭环 4/4 (872-989 步), AOI PASS 深度 5.3-5.9mm;
  insert seed104 343 步零回归。R1 视觉 full 未验 (每步 YOLO ~1s, GUI 演示时跑)。

## 关键文件
- src/lerobot/policies/left_right/state_space/{parallel,perception,cognition,dynamics,execution,safety}.py
- tools/gui/state_space_sim.py (HOLE_POS 常量 + ff_forward 真权重 + _stage_target)
- tools/gui/node_logic.py (node_ss_s2 分派 + _EXTERNAL_LOC 映射, 行 2062-2075)
- tools/gui/node_logic_dialog.py (_load_source 源码展示优先级)
- tools/ss_verify_trained.py (训练权重替换验证)
- tools/gen_insert_video.py (真机同构: YOLO detect_3d 解算写 obs[36:39])
