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

## 🏢 工程实现包 (2026-09-28 起): src/lerobot/engineering/ —— 逻辑在这里, GUI 只显示

节点逻辑与画布 JSON 已从 `tools/gui/` 搬进包 (lerobot 哲学: 注册表 + 实现归属 + 调用方解耦):

```
src/lerobot/engineering/
  paths.py      路径真源 (REPO_ROOT / LOGIC_FILE / FLOWS_DIR / GUI_DIR)
  registry.py   register(key,[关键字],doc,fn) · match_node(name) · home_file(key) · logic_globals()
  runtime.py    execute_node_logic(module,node,...) · _trace_exec · _demo_node_output
  sourceview.py get_node_source / get_node_location / explain_node / save/restore/reload
  flows.py      load_canvas / save_canvas(原子+备份) / validate_* / orphans / stats
  levels.py     L2/L3/L4/L5 档位契约 (must 列表) + band_map() + check()
  nodes/library.py    141 条节点逻辑 · 148 个注册 key (唯一真源)
  nodes/by_level.py   档位索引 (节点↔key↔函数, 自动生成)
  flows/state_space_obs.json   画布真源 (87 节点 / 173 连线)
```

`tools/gui/node_logic.py` = 33 行兼容壳 (转发包命名空间) · 仓库根 `flows/state_space_obs.json` = 软链。
**新增/改节点逻辑请写包里那份, 不要再写回 GUI 目录。**

溯源链 (从画布节点名 → 真代码): `registry.match_node(节点名)` → key →
`sourceview.get_node_location(key)` / `registry.home_file(key)` (用 `fn.__code__.co_filename`, 所以搬完自动指对地方)。

四层契约 (`levels.py`, 实测节点数): L2 基础功能 25 · L3 连续功能 5 · L4 自主安全 17 · L5 场景理解+自动标注 11 ·
元层 12; 判据 = `levels.check()` 里每层 `no_logic_key` 为空。

同类搬运的验收口径 (以后照用): ①key 集合与顺序 ②画布全量节点名→key 映射 ③每条关键字/doc 逐字
④函数源码逐字哈希; 基线 = 渲染 87/172 · 档位审计 R1 15·R2 34·R3 13·R4 7·R5 3·真缺口 0。

### ⚠️ 注册 key 重名会静默覆盖 (实测事故)
同一个 key 注册两次 ⇒ 后一条把 fn+关键字一起换掉 ⇒ 画布上那个节点**永远 match 不到逻辑**。
实例: `ss_pred` 被「先验动力学」(dynamics.py) 与「流形专家」(manifold) 重复注册,
导致「📈 先验动力学预测器」长期不可执行 (落在档位审计 R5-待建); 已拆为 `ss_dyn` + `ss_pred`。
新加节点/改关键字后, 拿画布节点名跑一遍 `match_node()` 验非 None (或直接 `levels.check()`)。

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

## 🧩 VEH.5.041 统一状态空间 = SU(2) 二阶特殊酉群 (2026-09-20 老倪升级)

**旧口径作废**: 该节点源码曾是 `perception.fuse_sensors()`(传感器融合拼接 43D) —— 老倪指出
"这是传感器融合, 不是统一状态"。统一状态空间是**群**: `SU(2) = {U∈C²ˣ²: U†U=I, det U=1}
= exp(−i·ω·σ/2)`, 全部层/全部节点数据都映进这个群, 在群里观察并理解整个场景。

- 内核: `src/lerobot/policies/left_right/state_space/su2.py`
  - `SU2Element`: 哈密顿积(群乘)/逆元/`from_rotvec`(exp)/`log`(主值分支, exp∘log 精确可逆)/
    `bloch()`(‖r‖≡1 — 群元素↔纯态, 全在 Bloch 球面 S²)/`theta()`/`visibility()`=|w|=收敛度/
    `distance_fs`/`commutator_norm`;  参数化 `U = w·I − i(x σx + y σy + z σz)`, (w,x,y,z) 单位四元数
  - **有界映射律** `ω = π·tanh(g·‖v‖)·v̂`: 任意实向量 → su(2); θ<π 永不绕圈(否则 θ 3.14 与 0 混在
    一起 = 假收敛), 方向保留, ‖v‖→0 ⇔ U→I(场景收敛)。别用 ω=g·v(会绕圈)。增益 L2=2.0/L3=3.0/L4=1.0
  - 层: L2=43D 几何误差(光模块头−孔位) / L3=流形规划(progress,dperp,rem) / L4=安全动作(u_sat,
    contact_p,1−η) / L5=大模型意图(**未接入 → 单位元, 不编造**);  `U_scene = U_L2⊗U_L3⊗U_L4⊗U_L5`
    (群不可交换 = 层序敏感), `peel_layers` 逐层左乘逆元读贡献, 全剥离残余应≈0(分解自洽)
  - 节点级全面映射 `NODE_SPECS`(17 节点): 每个节点的 io_trace 真实 out 按语义规则取向量
    (vec/slice/diff/chans/obserr; 字符串里的数值用正则提); 本帧无数值输出者 → 单位元 + 标注
- 画布: `flows/state_space_obs.json` 节点 ssobs 改名「🧩 SU(2) 统一状态空间 (二阶特殊酉群)」,
  params 带 `su2_unified_state/group/map_law/blocks/observables/viz_tools`; 43D 拼接语义归 📡传感器融合
- node_logic: `_EXTERNAL_LOC["ss_obs"]` → su2.py `class SU2UnifiedState`(右键显示群代码);
  执行函数 `node_ss_su2`(真跑 su2.py, 读 `module._ss_tr` 当前帧, 写 `_SS_STATE["su2_*"]`)
- 观测面板: `tools/gui/su2_dialog.py` — 双击节点打开(simulink `_open_su2_panel`, 分发分支
  `params.su2_unified_state` **必须在 source 分支前**, 否则被"数据源切换"抢先); 5 视图 = Bloch 球
  (QPainter 拖动旋转/滚轮缩放) · 层贡献+反演 · 层间不可交换与 FS 距离热力矩阵 · 节点映射 · 阶段轨迹;
  按钮含"可视化工具统一入口"(波形/3D/直方图/归因/视频/输入图像 → `_open_viz_node`)
- 验证/图: `tools/ss_su2_verify.py`(群公理 + 真实引擎 369 步 → `reports/su2_state_report.json`),
  `tools/plot_su2_state.py` → `reports/su2_bloch|converge|layers|node_map.png`
- 实测(引擎 接近→完成): θ_total 2.86→0.98, |w| 0.14→0.88(向恒等元收敛); 剥离残余 ≤3e-8;
  层间不可交换 L2|L4=0.587(最强); 群公理 封闭/酉/det/结合/单位/逆/exp-log/Bloch 全 ≤1e-15

**踩过的坑**
1. **数组进布尔上下文**: `float(frame.get(k) or 0.0)` 遇 ndarray → "truth value of an array is
   ambiguous" → 用 `_scalar()` 兜底(ndarray/0-d/None 全安全); `obs43_geometry` 兼容 (1,43)/列表。
2. **FakeMod 必须显式 `_trace_nodes = False`** — `__getattr__` 返回 lambda(truthy) 会让
   `execute_node_logic` 走 `_trace_exec` 逐行执行 → 节点"失败且无日志"的假象(排查浪费最久)。
3. **画布加载会重映射 node id**(id_map): 断言/查找一律按**节点名**, 不能按 json id。
4. **同一关键词只能注册一次**: `_reg("ss_su2",…)` 与 `_reg("ss_obs",…)` 关键词相同 → match_node
   歧义(返回 ss_su2 而 _EXTERNAL_LOC/画布 id 是 ss_obs) → 只保留 ss_obs 一条。
5. `data/` 与 `reports/*.png` 被 .gitignore → 映射表 `data/su2_mapping.json` 是**本地生成**
   (`load_mapping` 缺文件回退内置 DEFAULT_MAPPING, 不阻塞), 图不入库。
6. 扩展新层/新节点映射: 改 `NODE_SPECS`/`encode_layer` 即可(数据驱动), 不用碰画布 JSON。

## 🔌 引擎 L4 注入开关盘点 (2026-09-24 血教训: A/B 前先核对链上开关默认值)

`tools/gui/state_space_sim_real.py` 的 L4 注入链上有**一串默认关**的开关; 不核对就会把"上游没开"
误判成"模型无效" (2026-09-24 实例: 因为 `SS_L4_ALIGN` 默认关, 把"注入被闸死"写成了"新 LoRA inert"):

| 开关 | 默认 | 作用 | 不设的后果 |
|---|---|---|---|
| `SS_L4_INTACT=1` | 关 | L4 直驱接入 (decoder 量纲逆运算 act×K_ACT) | 完全没有 L4 注入 |
| `SS_L4_ALIGN=1` | **关** | 施加对齐层 `models/l4_align_map.json` (锥角 cos≥`SS_L4_ALIGN_COS_MIN`(0.9) + 幅度封顶 ≤`SS_L4_ALIGN_RATIO_MAX`(1.2)×L2) | 原始提案 cos 中位 **−0.605** / 幅度比中位 **5.8×** → 被 L2 收口闸逐帧否决 (实测 0/90 通过) |
| `SS_L4_INTACT_GATE=1` | 开 | L2 收口闸 (cos<0 或幅度>1.5× 否决) | 上层越界提案直接进执行 |
| `SS_L4_INTENT_LINE=1` + `_W` | 关 | 直连线注入 (另一条注入通路) | 只有直驱一条通路 |
| `SS_INTACT=1` | 关 | 标定映射接入 (需 `models/intact_action_map.json`, R² 负 → 全拒) | 用 SS_L4_INTACT 那条 |

**实测 (2026-09-24, 在役 `intact_l4_current`, 90 步 direct 臂)**:
`SS_L4_ALIGN=1` ⇒ 闸门 **90/90 全过** · cos 中位 −0.605→**0.963** · 幅度比 0.86 (0 帧超标) · blend **90/90** (原 0)。
闭环 A/B 同口径 3 seed × 4 臂: **消除回退** (seed1 direct 13.6mm→27.7mm, 与解析链 30.9 同级) 但
**未证明提升** (成功数与解析链同 1/3) ⇒ 不切在役指针/不进默认档。报告 `docs/design/lora_align_ab_20260924.md`;
复现 `tools/diag_lora_du.py`(带闸门内部量输出) + `tools/ab_intent_line_closedloop.py`。

**判据纪律**: 任何"注入无效/零影响"的结论, 先用 `tools/diag_lora_du.py` 打**逐级计数**
(本帧提案 → 闸门 pass/方向否决/幅值否决 → blend → u_ff 逐位比对) 再下结论。

## 🧬 模型进引擎的**只读旁路**挂点 + 口径 (2026-09-24 实测, 换靶子前必读)

工具 `tools/moe_engine_bypass.py --model {moe,dense}` (同一套框架跑两模型, 同口径可比)。

- **挂点**: 引擎 `run()` 里唯一每步一调的物理推进点是 `env.step(act)` (行 ~2637) →
  直接 `sim.env.step = hooked` 包一层。计数必须 `== 步数` (实测 52,212 帧 / 0 失败),
  这是"每帧真调"最硬的证据; 别用 `_io_snapshot`/每 5 步的 `ss_publish_metrics` (那是节流点)。
- **口径逐项 (对不上就是白测)**:
  | 输入 | 引擎侧取法 | 训练侧同源 |
  |---|---|---|
  | obs 39D | `sim._obs39()` == `env._get_obs()[:39]` | h5 `observation` (8715,39) **同源同义** |
  | px | `sim._render_frame()` → 224×224 INTER_AREA | 采集像素即 224×224 uint8 |
  | px 归一化 MOE | `float/255` → CHW, **无** mean/std | `stage_moe_backbone` 训练侧 |
  | px 归一化 dense | `to_img()` = `/255` + `(x-0.5)/0.5` | `joint_unified_backbone` 训练侧 |
  | mem 13D | `zeros(13)` | 训练侧就是 `torch.zeros(B,13)` |
  ⚠ `tr["obs"]` 是 **43D** (`perception.fuse_sensors`) 不是 39D —— 想比 39D 必须 `[:, :39]`。
- **零回退实证法**: 同 seed 跑两次 (挂钩 / 不挂钩) → `dist` 序列 `np.array_equal` 逐位相同才算只读
  (实测 10/10 seed, 最大差 0.0mm)。冷记忆隔离 `SS_MUSCLE_PATH=/tmp/...` 否则热记忆让同 seed 漂移。

### 🎯 结论: 认知头"预测下一帧观测"= 靶子定错 (2026-09-24, 两模型同证)

| 口径 | 持久基线 | MOE | dense |
|---|---|---|---|
| 同源留出 (v6 2000 样本) | **0.002972** | 0.009894 (3.33×差) | 0.015417 (5.19×差) |
| 引擎流 (52,212 帧) | **0.00042** | 0.01214 (29×差) | 0.01665 (40×差) |

机理: 引擎每步 `|Δobs|` 均值 **0.000298** vs 采集集 **0.002966** (≈10×) → 两边"预测下一帧"难度不同源,
持久基线在引擎上天然近乎完美。⇒ **不接管**; 改法是换靶子 (多步 K=5/10 或事件级: 接触/阶段切换/残余插深),
且**一律带持久基线+平凡基线同表**。与 09-06 右脑 world model "一步预测打不过纯积分先验"同一条教训。

## 🧮 流形引擎 (Manifold Engine) — L4 核心内核 (2026-09-24 老倪架构升级)

**定义**: 高维状态空间 → 低维流形, 在流形上做 表征/投影/度量/测地线导航/梯度流/有界反馈。

- 源码 `src/lerobot/manifold/manifold_engine.py::ManifoldEngine`; 画布节点 `ss_mani_eng`
  (x=7500 y=1546, L4 专家自主功能行 **前向输入前沿 4690 与输出前沿 10016 之间**);
  三件套 = `_reg("ss_mani_eng")` + `node_ss_mani_eng`(读 `module._ss_tr` 当前帧真跑) + `_EXTERNAL_LOC`
  + 能力清单 `capability_levels.py::L4-C15`。
- 复用既有真件 (别重写!): `su2.py`(群) · `manifold/lie_intent.py`(SO3/SE3 四元数) ·
  `manifold/manifold_layer.py`(接触/性能势能 Φ) · `manifold/fiber_bundle.py`(丛提升)。
- 流形注册表 **9 种 = 7 ready + 2 planned**: ready(euclidean/sphere/torus/so3/se3/su2/latent_flat);
  planned(calabi_yau 缺 Ricci-flat 度量 / hyperbolic 缺图卡) → `project()` 对 planned **拒答**,
  只返回 status/confidence=0, **不造数** (这是本仓库的红线, 新流形没实现就别标 ready)。
- 实测 (真跑引擎 160 步, `tools/manifold_engine_bench.py`): 端到端 **0.056ms/帧** · 投影 0.019ms ·
  测地线T=16 0.24ms · 上限 ~3500Hz · **约束违例 1.1e-16** · Φ 0.96→0 (向收敛态)。
- 踩过的 5 个真 bug (都写进自检): ①潜维不足 SO(3) 静默退化成单位阵 (改补齐+标注 `latent_padded`)
  ②SE(3) 12 维点 (R9+t3) 被当 9 维 reshape → 必须 `[:9]` ③"残差"要拆成 **约束违例**(验投影器, ≈0)
  与 **投影改动量**(‖p−z‖, 做置信/异常) ④反馈残差维数 ≠ 切空间维数时必须显式对齐(截断/补零+标注)
  ⑤无界岭回归解码器**外推发散**(预测幅值 3.05 vs 真值 1.0, 全段 R² +0.561→−3.55) → 必须用训练数据的
  动作界做**硬限幅**, 并**分段报 R²**(训练段/未见段) + 逐维相关, 别只报一个聚合 R²。
- 画布接入脚本 `tools/canvas_add_manifold_engine.py`: 6 条硬断言 (居中/最大空档/零重叠/全前向/幂等/行带内),
  新增"核心内核类"节点照这个模板改 X/Y 即可。

### 🧮 主标定参数 M —— 流形引擎向标定层暴露的**唯一**结构参数 (v5.16.4)
- 口径(老倪定调): 流形引擎 = 整个工程的核心结构 ⇒ 它向标定层暴露一个主标定参数 **M**(类比发动机标定的质量), **M 是系统最主要的参数**。
  物理: 等效惯量 `a=F/M ⇒ Δx=F·dt²/M`; 信息论: 交叉熵 H(p,q) 的"单位换算/曲率尺度"(Fisher/Hessian 尺度的单标量代理)。
  **M 由流形结构导出, 不是拟合出来的自由参数** — 结构决定可能性, 质量是果不是因。
  过阻尼含义: `M→0` = 现在的一阶 GD(速度∝力, 感觉不到惯性); `M>0` ⇒ 状态带**动量** ⇒ 过渡更平滑、抑制突变。
- 落点: 引擎 `src/lerobot/manifold/manifold_engine.py`(MANIFOLD_M_DEFAULT/RANGE/UNIT + `set_M()` + 有惯性二阶分支)
  · 真源 `config/calib/zmax_manifold.json` → `tools/zmax_params.py --check | --m <v> [--inertia on|off]`
  · 标定层新域 `calibration_layer.MANIFOLD_CALIB`
  · 画布新节点 `n_calib_mani`「🧮 流形引擎标定 · 主参数 M」+ 5 条前向连线(sscalib/sslat → 本节点 → ss_mani_eng/ssmani_c/ssmani_exp)。
- **零回归红线**: 默认 `M=1.0 · inertia=false` 必须与旧一阶过阻尼**逐位相同**; 判据 = 引擎内建 selftest(M=0/关 ⇒ 与旧轨迹相等)
  + `tools/manifold_M_experiment.py`(同场同起点: 关与 M=0 逐位相同; M=1 时反转 −F 后**仍沿原方向前进** ⇒ 动量可观测)。
- 画布节点改动后**须重启控制台才可见**; 若重启前有人在画布上点了「保存」, 内存旧版可能覆盖磁盘 ⇒ 重跑 `tools/canvas_add_manifold_calib.py --apply`(幂等+六断言+自动备份)。

## 🎛 GUI 安全启停 (2026-09-24 血案)

- **别用 `pkill -f studio.py` / `ps|grep studio.py`**: 你的命令行里含 "studio.py" 字样 → **匹配到自己 → 自杀**
  (实测 SIGTERM -15 中断整条命令)。用 `bash tools/studio_ctl.sh {status|stop|start|restart}` (按 /proc cmdline
  精确匹配, 判断逻辑在脚本文件里所以不会自杀)。
- **venv 在仓库根**: `/home/ubuntu/lerobot-smolvla-lew/gui-venv311/bin/python` (launch_studio.sh 硬编码),
  **不在** `tools/gui/` 下 → 按 tools/gui 路径匹配会永远报 "stopped" (假阴性, 实测踩到)。
- 启动脚本用 `nice` 包一层, 所以 **argv[1] ≠ 解释器**; 匹配要"任一段是解释器 且 任一段是 studio.py"。
- 改 `node_logic.py` / 画布 JSON 后: 先 `studio_ctl.sh stop` → 改 → `studio_ctl.sh start`;
  GUI 存活核验 `xdotool getwindowgeometry $(xdotool search --onlyvisible --name "XSpace Studio"|head -1)`。

## 🐞 「断点打不进」的真相 = 分层生效, 不是 bug (2026-09-29 老倪现场: 跑L5时 move_pose 进不了断点)
- **画布 L5 档不下发真机动作**: `node_l5_loop`(src/lerobot/engineering/nodes/library.py:4643) 只读状态+触发 VLM 标注→训练; 节点 `n_moveit`(同文件 2990-2999) 只 `precheck()` + `MoveItPlan.plan(...)`, **一行 move_pose 都没有** ⇒ 断在 `arm_control.ArmController.move_pose`(src/lerobot/arm/arm_control.py:165) 永远不命中。上层只给意图/条件、执行由 L2 收口 —— 看到这现象先想"分层对", 别去改画布节点代码。
- **真机下发是另一个常驻进程**: GUI/CLI → `~/zmax_data/l2_cmd.fifo` → `tools/l2_daemon.py`(独立 pid) → `ros2 service call /move_pose|/move_line|/gripper_driver`(l2_daemon.py 325/518/916)。断点要 **attach 到 daemon 的 pid**(VSCode: Attach using Process ID), 不是另起的调试会话; 断在真实执行器里会暂停下发, 现场臂动着时别停太久。
- **别为了看下发去改 daemon**: `l2_daemon.py:79 maybe_reload(reg)` 会热加载 ⇒ 现场改码可能 reload。用只读镜像 `tools/l2_dispatch_watch.py`(tail l2_daemon.log → reports/l2_dispatch.jsonl, 分清 DRY-RUN/真发) 代替断点。
- **契约式退出码 ≠ 崩溃**: `raise SystemExit(main())` 得 1/2 = 工具按判据拒绝(VSCode 报成 "Exception has occurred: SystemExit")。真原因打在 traceback **上面**; 判断他跑了哪个模式看产物 mtime, 不要猜。
- **L5 槽位工具 0 框退出码**: `tools/l5_slot_tool.py --build-dataset` 默认只收 `status=已记录`; VLM 复核不一致 / 无 TCP 真值 / 深度未上线 → 一律停 `待确认` ⇒ 0 框 ⇒ exit 1(不是崩)。跑通管线用 `--include-pending`(仅供冒烟, 报告标注); 要真标签必须现场 `--record --slot N`(判据: 投影 ok + TCP≤3s + VLM 一致)。
- 现场拖动时的实时叠加三件套见 `sim-real-scene-overlay`: 50Hz 录制真关节+TCP(`tools/live_motion_recorder.py`) · 停顿点自动打点+实测轨迹层(`live_pause_marker.py`, origin=`trace` 黄) · 同源规划段(`live_plan_segment.py`, 两端真机真值, 按执行器守卫 ≤50mm/下降≤20mm/≤10°分段)。

## 三级能力测试(L2/L3/L4)运行口径 (2026-09-29 实测)

```bash
xvfb-run -a ./gui-venv311/bin/python tools/ss_level_tests.py [--level L2|L3|L4]
```

- **必须 `xvfb-run`**: 不加会出现假失败(`无 DISPLAY 无法渲染真实帧` + `ModuleNotFoundError: No module named 'tools.gui'`); 加上即全过。
- 🔴 **现场机上不跑 L2/L4**: L2 里有**碰真机**的用例(`t_sssensor_real` / `t_sobs_realalign` 等 `t_*_real` 一族),
  在有人作业的现场跑会动真机、可能引发控制器报警(实测过一次)。现场要验回归只用离屏/离线手段,
  或先确认无人在场、臂处于安全位姿再跑; 要真机证据时单跑指定用例并提前告知现场。
- **节点逻辑迁 `src/lerobot/engineering/` 后验证层会假失败**: 审计/映射仍指旧壳 `tools/gui/node_logic.py`(已不含逻辑)。
  · `verification_layer._audit()` 用 `_MIGRATED_SRC` 同时扫【旧壳 ∪ 新真源】, 命中任一即过。
  · `_EXTERNAL_LOC` 行号随真源漂移, 须按真源实测校正: n_web_agent 1→93 · n_hil 1→157 · ss_test 111→123 · ssa/ssb/ssc 3900→3533 · ss_lat 58→55 · ss_moe 42→50 · ss_mani_eng 395→403。
- **L4 `t_sched_real` 必须放在子进程里跑**(已改, 否则套件内假失败): 它调 `tools/gui/state_space_sim_real.quick_run(n_episodes=2, vision=False)`, 判据 **2 集 ≥1 完成**。
  同进程内跑过前面一堆用例后两集都折在 1000 步(❌ 0/2); **单独子进程跑 = 1/2 ✓**(完成那集只 395 步、夹持=True)。
  静机复跑仍然 ❌ ⇒ **不是资源竞争, 是同进程状态污染的顺序敏感性**。
  定式: `subprocess.run(["xvfb-run","-a",sys.executable,"-c",<跑 quick_run 并 print N_OK=>], cwd=REPO_ROOT, timeout=900)`,
  解析 `N_OK=` 判 ≥1 ⇒ 既保留"真跑/真渲染/env.step"的强度, 又消掉顺序敏感性(改后 L4 178/178 全过)。
  同类启示: 任何**带真环境/真渲染的合成断言**都优先子进程隔离, 别在同一个长套件里前后串着跑。

## 关键文件
- src/lerobot/policies/left_right/state_space/{parallel,perception,cognition,dynamics,execution,safety}.py
- tools/gui/state_space_sim.py (HOLE_POS 常量 + ff_forward 真权重 + _stage_target)
- tools/gui/node_logic.py (node_ss_s2 分派 + _EXTERNAL_LOC 映射, 行 2062-2075)
- tools/gui/node_logic_dialog.py (_load_source 源码展示优先级)
- tools/ss_verify_trained.py (训练权重替换验证)
- tools/gen_insert_video.py (真机同构: YOLO detect_3d 解算写 obs[36:39])
