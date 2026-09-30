# 肌肉记忆机制 (2026-09-08, 老倪: 仿人类小脑, 越练越顺)

代码: `tools/gui/muscle_memory.py` (MuscleMemory 单例) + `state_space_sim_real.py` 集成。
开关: `SS_MUSCLE=0` 关闭; 默认开 (引擎级自动积累, GUI 无感)。
持久化: `data/muscle_memory.json` (每 seed+stage 一桶)。GUI 测试注独立库: 构造
`MuscleMemory(path=...)` 后赋给 `muscle_memory._INSTANCE` (模块级单例), 再 import 引擎。

## 需求语义 (老倪原话)
多次运行同一动作 → 把最优轨迹固化为"标杆模板" → 以后直接快速执行, 不再每步由决策层
精算 = 肌肉记忆, 越练越顺, 可数据增强。验收 = 功能 + 测试 + 视频。

## 机制 (阶段级, 按 seed 场景分桶)
1. **观察**: 每轮 `begin_episode(seed)`; 每帧 `feed(stage, x, u_exec)` 记录该段
   (stage → u_exec 4D + x 3D 序列)。u_exec = **实际下发执行指令** (execr 输出),
   不是 u_ff/decide 中间量。
2. **固化**: `end_episode(success)` — **失败轮不固化** (只清缓冲)。同 (seed, stage)
   连续成功 ≥3 次 (MIN_OK_RUNS) → 固化标杆 = 最近成功轮 u_exec 序列 (真实化多轮物理
   微差, 用最近轮; 不是平均 — 平均需对齐, 见下)。
3. **精进**: 已有标杆后每成功轮 `_merge` 指数融合 `(1-α)·champ + α·new` (α=E_MERGE=0.3),
   逐点对齐、末端保持 → 越练越顺 (数据增强 = 多轮融合去噪)。
4. **快通道 (重放)**: run() 每步查当前段标杆; 命中 → **替换 u_ff** (前馈建议),
   decide/反馈/饱和限幅闭环保留 → 安全链不破。

## ⚠️ v1→v2 血泪教训 (ep4+ 全失败实锤, 别重走)
- **v1 错误**: 标杆记 x 轨迹, 快通道把标杆 x 混进 `target` (`target = 标杆×α + 实时×(1-α)`)。
  → 开环重放目标与实时状态脱节, 前段微偏经夹持/转移级联 → 插入段初始 z 偏 4mm
  (判据 1.2mm) → 400 步内插不完 → ep4+ 全失败。改 α 0.35→0.9 没用 (量变非质变)。
- **v2 正确**: ①标杆记 **u_exec 序列** (非 x); ②快通道 = **替换 u_ff**, 不是改 target;
  ③**只有接近类前段 (接近/对位/下降/抓取/抬起) 走快通道**, 转移/插入/完成 = 毫米级
  对准/插拔, 必须实时决策 (快通道会级联偏 z → 插入伺服启动条件不满足卡死)。
  ④同 seed 布局确定性高 (ep1-3 σ<1mm) → 重放 u_exec ≈ MLP 实时输出, 价值 = 跳过
  MLP/卡尔曼/decide 精算 (真机实时性), 轨迹几乎不变 → 不失败。
- **插拔/毫米级阶段永远实时**: 插入段已有解析伺服精插 (analytic_forward), 禁止任何
  开环重放 (孔间隙 1-2mm, 无倒角刚体, 开环必顶孔沿)。

## 引擎集成点 (state_space_sim_real.py)
- `__init__`: `if os.environ.get("SS_MUSCLE") != "0": from muscle_memory import get_memory`
  + 成员 `_mm_stage/_mm_step/_mm_hits/_mm_seg/_mm_u/_mm_i`。
- run() 开头: `muscle.muscle.begin_episode(self.seed)` (after _reset)。
- 每步 target 计算后: 阶段切换检测 → `feed(stage, x, u_exec_prev)` (u_exec 待算,
  用上帧 `self._u_vec`)。
- u_ff 计算处: 阶段切换 → `get_champ(seed, stage)` 预取; `_mm_i < len(_mm_u)` →
  `u_ff = _mm_u[_mm_i]` + log "🧠 肌肉记忆快通道: {段} 标杆 u_exec 重放"。插入段
  `_mm_u=None` (实时)。
- run() 返回前: `end_episode(done)` → log "🧠 肌肉记忆: SK01接近固化/精进…" + 记忆库
  汇总 (`muscle.status()`)。

## 测试 (R0 seed104 连续 6 轮, 真实物理 0.2s/轮)
ep1-3 观察 (命中0, σ=0.00087) → ep3 固化 (7 段全固化, 练3次) → **ep4-6 快通道命中
180/182/183 帧 + 全成功** (342-343 步, σ→0.00086)。判定: 后3轮 ok 且 hits>0。
测试脚本模式: `/tmp/mm_train_test.py` — 独立记忆库注入 _INSTANCE, 6 轮循环跑
`RealStateSpaceSim(seed=104, vision=False)` (R0 无 YOLO 快), 每轮打印 ok/steps/hits/σ。

## 视频证据生成 (3D 回放, cv2 Qt 坑见 zmax-console)
- 事后 env.render() 不可行 (metaworld env reset 后是初始态) — 视频用 **DreamView3D 喂
  轨迹 set_frame 逐帧 `w.grab().toImage().save(png)`**, 帧存 PNG → ffmpeg 合成 mp4。
- 流程: 练 3 轮固化 → 跑 ep1 (初学) + ep4 (肌肉记忆) 各存轨迹 → 每轨建 DreamView3D
  resize 900x560 show → set_trajectory → 每 ~3 步 set_frame + grab PNG → ffmpeg
  `-framerate 30 -i f%04d.png -pix_fmt yuv420p`。GL item 绘制 warning 无害, 帧有内容
  (亮度 31/彩色 7-12%) 即有效。
