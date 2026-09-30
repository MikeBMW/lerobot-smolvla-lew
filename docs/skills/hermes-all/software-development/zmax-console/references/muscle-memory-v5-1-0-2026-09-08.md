# 原子技能肌肉记忆 v5.1.0 + 画布高级/基础分层 v5.2 (2026-09-08 老倪设计)

## 肌肉记忆 (仿小脑) — RealStateSpaceSim 集成

老倪命题: "运行几次同动作 → 取最好作标杆模板 → 以后直接快速运行不每步决策层给出; 越练越顺; 可数据增强"。

### 架构语义 (定稿)
- **大脑(决策层)**: MLP 前馈 + 卡尔曼 + 调制器, 每步精算 → 慢而准
- **小脑(肌肉记忆)**: 观察重复动作 → 固化标杆 → 快通道重放 → 越练越顺
- 分层: encoder VLM → 潜空间 → decoder = **高级功能**; yolo → 前馈加速器 → 原子技能 = **基础功能**

### 实现 (v5.1.0, commit 3be980d1)
- `tools/gui/muscle_memory.py`: 模块级单例 `get_memory()`; 每 (seed, stage) 分桶;
  记录 **u_exec 序列** (实际下发速度, 含闭环修正), x 仅存证据。
  固化: 同技能连续成功 ≥3 次 (MIN_OK_RUNS) → 标杆 = 最近成功轮 u_exec 整段;
  后续成功轮指数融合 α=0.3 (数据增强 = 多轮平均去噪, 越练越精)。
  持久化 `data/muscle_memory.json`; 开关 `SS_MUSCLE=0` 关。
- `state_space_sim_real.py` 集成: run() 开头 begin_episode(seed) → 主循环每帧
  feed(stage, x, u_exec) → 结束 end_episode(ok); 失败轮不固化 (只清缓冲)。
- **快通道只接管前 5 段** (接近/对位/下降/抓取/抬起): 阶段切换 get_champ 预取,
  每帧 u_ff = champ_u[i] 推进 (跳过 MLP 精算 = "练熟动作小脑直接给力");
  **转移/插入/完成 段实时决策** (毫米级对准+插拔, 标杆会级联偏 z)。

### 血泪坑 (全踩过, v1→v2 两轮)
1. **快通道不能改 target (目标层)**: v1 把标杆 x 轨迹混进 `_stage_target()` →
   ep4+ 全失败 (转移结束 z 偏 4mm → 插入段伺服级联偏, 400 步卡死)。
   **必须只接管 u_ff (前馈层)**, 决策终点/反馈/饱和限幅闭环保留 — 小脑辅助大脑非替换。
2. **标杆记录 u_exec 而非 x**: x 轨迹重放 = 开环位置引导, 环境微差即错位
   (σ<1mm 也不行, 插入段 z 判据 1.2mm 会卡死)。
3. **插入/完成段禁快通道**: peg 无倒角刚体, 孔间隙 1-2mm, 标杆 u 微差顶孔沿磨死。
4. **阶段切换重置段步计数** (_mm_seg/_mm_i), 否则标杆索引错位。
5. **测试隔离**: 引擎 import muscle_memory 时 get_memory() 建正式库实例 →
   测试先 `muscle_memory._INSTANCE = MuscleMemory(path=临时)` 再 import 引擎。
6. **同 seed 决策确定性极高 (σ<1mm) 是固化可行的前提** — 按 seed 分桶, 各场景自练
   (真机同构: 每工位/来料位置各自的肌肉记忆)。

### 验证模式 (R0 seed104 6 轮)
ep1-3 学习 (σ0.00087) → ep3 全 7 段固化 → ep4-6 快通道命中 180/182/183 帧全成功
(跳过决策精算依然完成), σ→0.00086。判定: 后 3 轮 ok=True 且 _meta.mm_hits>0。
`tr["_meta"]["mm_hits"]` 每轮写回; 结束日志打 "🧠 肌肉记忆: SK01接近固化(练3次)..."
+ "🧠 肌肉记忆库: 场景104: 接近(练N次)..."。

## 画布高级/基础分层 (v5.2, flows/state_space_obs.json)

### 老倪定稿语义
- **高级层 (顶部, 紫 #4b2d8e/#5b2d8e)**: 🧠 VLM 通用视觉编码器 (SmolVLA 式:
  图像/视频帧/触觉/YOLO 检测框 → token → 潜空间 z) → 潜空间流形
  (接触流形 e∥/e⊥ + 性能流形 V_p/η = 导航地图) → 🔄 潜空间 Decoder (z→u_mani)
- **基础层 (原位青)**: YOLO 检测 → 📡 传感器融合 → ⚡ 前馈加速器 (MLP) ←
  decoder u_mani 融合 → 🧭 调制器 → 🧩 原子技能 SK01-08 → 执行器
- **保持光模块插入能力零改动** — 只增不改现有节点/连线/流程

### Flow JSON 手术配方 (54 节点 66 连线)
1. **先备份**: `shutil.copy2(PATH, PATH+".bak_v520")`
2. 节点字段: id/type/name/x/y/w/h/icon/color/params — row_bg 定义行带
   (name/y/w/h/icon/color+params.bg); 节点放行内用绝对 y。
3. 新行插入顶部: 把大模型行整体下移让位 (set_row + 节点 y 同步), 别在密集区挤。
4. 连线 {id,f,t,f_port,t_port,label} — **新增必须查重** (any l.id==lid 防重复加载),
   改后验证: 所有 links 的 f/t 都在 node ids 里 (失效连线 = 加载崩)。
5. `d["version"]="5.2.0"` + name 更新; json.dump indent=1。
6. 重启 GUI 后 ss_canvas 命令等画布加载 (simulink_log.txt 出现 "已加载工作流"),
   **open_state_space 打印的架构说明文本是硬编码的, 不随 flow 变** — 看节点数判断。

### VLM 节点真实化方向 (参考 src/lerobot/policies/smolvla_lew/)
SmolVLM 500M (SigLIP 视觉骨干) → DiT-B flow-matching action head (Sys-11) +
LeWorldModel next-frame predictor (Sys-12); config 坑: `freeze_smolvlm:true` 时
`enable_lew_world_model` 被 __post_init__ 强制 False — 真 LEW 必须 freeze:false
+ enable:true。节点 params 先挂 desc/source, 数据流逐个接真实模型再验证。
