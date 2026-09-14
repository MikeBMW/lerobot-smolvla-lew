---
name: zmax-muscle-memory
description: Use when 原子技能需要"越练越顺"机制 — 重复动作固化标杆模板后快速直通, 或状态空间引擎集成肌肉记忆.
---

# Z-MAX 原子技能肌肉记忆 (2026-09-07 v5.1.0 老倪设计)

仿人类小脑: 大脑(决策层)每步精算 → 多次重复同动作 → 小脑固化为标杆 → 快通道整段重放, 越练越顺。

## 架构 (三层)

```
大脑(决策层): MLP前馈+卡尔曼+调制器 每步精算 → 慢而准 (原始)
    ↓ 观察: 每轮记录 8 技能段 (stage, x, u_exec) — 决策层实际输出
小脑(肌肉记忆): 同场景同技能 连续成功≥MIN_OK_RUNS(3)次 → 固化为标杆
    ↓ 命中: 该段前馈 u_ff = 标杆 u_exec 序列同帧值 (跳过 MLP 精算)
    = "练熟的动作小脑直接给力"; decide/反馈/饱和限幅链全保留 (安全不破)
    ↓ 持续练习: 每轮成功轨迹与标杆指数融合 (α=0.3) → 越练越顺 (数据增强)
```

## 关键文件

- `tools/gui/muscle_memory.py` — 核心: MuscleMemory 类 (模块级单例 get_memory())
  - begin_episode(seed) / feed(stage, x, u_exec) / end_episode(success)
  - 固化: n_ok≥3 → champ_u=最近成功轮 u_exec (整段); 后续成功轮指数融合
  - 持久化: data/muscle_memory.json; 测试可注入 _INSTANCE 隔离
- `tools/gui/state_space_sim_real.py` — 引擎集成:
  - __init__: SS_MUSCLE=0 可关; 成员 _mm_stage/_mm_step/_mm_hits/_mm_seg/_mm_u/_mm_i
  - run() 开头 begin_episode → 主循环每帧 feed + 快通道 → 结束 end_episode(ok)
  - **快通道只接管前5段** (接近/对位/下降/抓取/抬起): 阶段切换时 get_champ 预取,
    每帧 u_ff = champ_u[_mm_i] 推进; **转移/插入/完成 段实时决策** (毫米级对准+插拔)
- SK 节点画布高亮: simulink_module.py `_highlight_sk_for_stage(stage)` 共用方法
  (stage→sssk1-8: 当前阶段 running 其余 success); _on_real_poll 400ms 轮询
  sim._vis["stage"] 驱动运行中高亮; _ss_tick 播放也调

## 血泪坑 (全踩过)

1. **快通道不能改 target (目标层)**: v1 把标杆 x 轨迹混进 _stage_target →
   ep4+ 全部失败 (转移结束 z 偏 4mm → 插入段伺服级联偏)。**必须只接管 u_ff (前馈层)**,
   决策终点/反馈/限幅闭环保留 — 小脑辅助大脑, 不是替换大脑。
2. **标杆记录 u_exec 而非 x**: u_exec 是实际下发速度 (含闭环修正), 重放它才安全;
   x 轨迹重放=开环位置引导, 环境微差即错位 (σ<1mm 也不行, 插入段 1.2mm z 判据会卡死)。
3. **插入/完成段禁快通道**: 毫米级接触 (peg 头无倒角刚体, 孔间隙 1-2mm) —
   标杆 u 与实时物理微差 → 顶孔沿磨死。前段 (接近→抬起) 是"接近动作"才安全。
4. **失败轮不固化**: end_episode(ok=False) 只清缓冲 — 固化=成功经验, 失败练不进去。
5. **阶段切换要重置段步计数** (_mm_stage/_mm_i), 否则标杆索引错位。
6. **测试隔离**: 引擎 import muscle_memory 时 get_memory() 建正式库实例 →
   测试先 `muscle_memory._INSTANCE = MuscleMemory(path=临时)` 再 import 引擎。
7. **同 seed 决策确定性极高** (σ<1mm) 是固化可行的前提; 不同 seed 布局不同 → 按 seed 分桶,
   每场景各自练 (真机同构: 每个工位/来料位置各自的肌肉记忆)。

## 测试 (mm_train_test.py 模式)

```python
# 6 轮验证: ep1-3 学习(σ0.00087) → ep3 全 7 段固化 → ep4-6 快通道命中 180+帧 全成功
for ep in range(6):
    sim = RealStateSpaceSim(seed=104, vision=False)
    tr = sim.run(max_steps=400)
    ok = tr["done"][-1]; hits = tr["_meta"].get("mm_hits", 0)
# 判定: ep4-6 全部 ok=True 且 hits>0 = 肌肉记忆生效 (跳过决策精算依然完成)
```

## GUI 操作链路 (老倪现场验收要点)

- 命令文件触发: `echo "simulink|ss_canvas|ss_run" > /tmp/zmax_nav_cmd` (studio.py QTimer 300ms
  轮询, 无去重 — 每次写入都执行; ss_run=_run_ss_cmd→simulink.start_sim())
- ▶运行 默认=真实化 (_start_real_sim, seed104 vision); ⚡引擎快演=快演示
- 真实化 500 步×~1s=5-9 分钟; R0 无视觉 0.2s/轮 适合肌肉记忆测试
- GUI 重启杀进程: pgrep -f 'studio.py' 精确 PID (kill -9), 两实例叠窗=旧代码残留
- 窗口遮挡: Chromium(千问) 全屏盖画布 → wmctrl -i -a <winid> 置顶; 画布平移=**中键拖动**
  (mousePressEvent MiddleButton), 左键=选中节点不是平移!
- 视频证据: DreamView3D 逐帧 grab → PNG → ffmpeg 合成 (禁 cv2 import — 自带 Qt 插件污染
  平台插件路径, QApplication 起不来; QT_QPA_PLATFORM_PLUGIN_PATH 指 PyQt5 真插件)
