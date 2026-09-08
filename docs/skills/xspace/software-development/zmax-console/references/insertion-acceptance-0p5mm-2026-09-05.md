# 插入验收 0.5s/0.5mm — 引擎物理精度改造 + MLP 用例口径 (2026-09-05)

老倪 (2026-09-05): "测试用例, 我只关注最终能不能插入, 插入时间<0.5s, 偏差<0.5mm,
我要在仿真波形里明确看到这些数值的波形" → 引擎精度改造 + Scope 2x4 验收波形 +
FNaccept01 用例 (12 扰动集)。承接 test-acceptance-full-auto-2026-09-04 / playback-sync ref。

## 指标定义 (与 Scope/用例同口径)
- 插深剩余 = 性能流形 `−d_axial` (孔轴 AXIS_HOLE≈(−1,0,0), 剩余 = hole_x − peg_head_x);
  横向错位 δ⊥ = `d_perp_norm` (yz 面, 垂直孔轴)。
- 插入段起点 = 插深剩余首次 <20mm 的帧; 插入时间 = 末帧 t − 起点 t。
- 达标实测 (12 扰动集, 初始 hand ±5cm/±1.5cm): done 12/12 · 插入 0.42–0.48s · δ⊥≤0.06mm ·
  插深剩余 ≤0.4mm。测试断言全部三项 + 全绿才算过。

## 引擎物理改造三件套 (tools/gui/state_space_sim.py run 循环)
1. **孔壁 yz 双轴对中** — 原只有 `v[1]*=0.3` 阻尼 → δ⊥ 卡 ~2.8mm 不收敛 (孔轴水平,
   横向 = yz 面, 只锁 y 不够)。头进孔后 (`grasped and peg_head()[0] < HOLE_MOUTH[0]+0.001`):
   `x[1]/x[2]` 以 `min(1, dt*25)` 速率拉向 `HOLE_POS − peg_off − PEG_HEAD_OFF`, 同时阻尼 v[1]/v[2]。
2. **孔底物理止动** — 完成阈 0.5mm < 单帧步长 (~1.4mm @ cap 0.07) → 每帧都越过阈值 →
   状态机"插入"永远无法连续确认 → 不 done 且 peg 冲出孔底 18cm。修: 头到位后
   (`peg_head()[0] <= HOLE_POS[0]`, **插深沿 −X, 条件是 <= 不是 >=**) 钳 x[0] 到
   `HOLE_POS[0]−peg_off[0]−PEG_HEAD_OFF[0]` 且 v[0]=0。
3. **peg=x+peg_off 不变量**: 约束块内改 x 后必须重算 `self.peg = self.x + self.peg_off`,
   否则 tr 记录 peg 滞后 → t_F_A06 "peg−x 漂移 6.6mm" 假 FAIL (锁存偏移被虚报漂移)。
- cognition.py: `insert_depth` 默认 0.004→**0.0005** (3D 到头距离); STAGE_V_CAP 插入
  0.07→0.085 (换时间余量; 0.48s 贴线太险)。改引擎必须同步 commit — t_cal_zerodiff
  检查三个引擎文件 **git diff 必须为空** (提交纪律, 非参数一致性; 工作区有改动即 FAIL)。

## Scope 验收波形 (StateSpaceScopeDialog 2x4)
- 第 7/8 格 = 插深剩余 (mm) / 横向错位 (mm): 只画插入段放大窗 (起点前 8 帧起), y 从 0,
  0.5mm 红虚线 + "0.5mm 验收线" 标注, 标题带 "· 阈 0.5"; 插深格右上标注 `插入段 0.44s (<0.5s ✅)`。
- 底部验收摘要大字: `✅ 插入成功 · 总用时 6.66s · 插入段 0.44s · 末横向错位 0.04mm · 插深剩余 0.09mm`;
  播放中 (`set_cursor` 未到末帧) 显示 "▶ 运行播放中 t=…" 而非 verdict。
- 数据源: 引擎 tr 每帧存 `mani_rem`/`mani_dperp` 全序列 (流形 evaluate 后 append), Scope/断言共用。

## 蒸馏 MLP 断言口径 (2026-09-05 全量重写, 假失败根因)
- **手造稀疏 obs 对 MLP 是分布外** (zeros(43) 归一化后 = 极端输入 → 输出饱和 clip ±0.6)
  → 旧解析律式断言全假失败 (指向/限幅/单调/零误差全爆)。解析律已退役为守卫, 测试测的是 MLP。
- 正解 = **训练域真实帧采样**: `_ff_frame(rng)` 从 `data/ss_insert_lerobot/data/chunk-*/file-*.parquet`
  惰性读 state 列 (helper 无 np 参数 — 内部 `import numpy as _np`, 否则 NameError)。
- 断言阈值必须实证 (26942 帧采样): 指向 100% (≥99%) · |u|≤0.6 100% (容差 1e-3, float32
  恰 0.60000002 会误杀) · 完成态 pos=target |u|≤0.3 (p95 0.124; 精停由完成判据, MLP 不保证 0) ·
  误差大→动作大 ≥95% (目标外推 1.6×) · 远/近桶中位 |u| 比 >1.5 · 夹爪规则按 **d_xy**<0.03
  (垂直接近 3D 距大可 xy 已对中 → 闭爪是正常准备态, 别用 3D 距判"误闭合")。
  每用例固定 seed + 最低帧数门槛 (n≥100/300), detail 文案带实测数字与规格说明。
- FNaccept01 (ssworld): t_accept_insert 12 扰动集 run(io_every=200), done+T<0.5s+δ⊥<0.5mm+剩余<0.5mm。
