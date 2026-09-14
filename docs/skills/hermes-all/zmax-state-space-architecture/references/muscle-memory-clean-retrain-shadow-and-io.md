# L2 标杆库: 清库重练 + 影子模式 + io 契约 + 测量纪律 (2026-09-10 实测)

本文是引擎侧肌肉记忆/标杆库的操作事实 (原 zmax-muscle-memory 技能的补充;
该技能为 user-owned, 无法自动更新 — 需要时 `hermes curator adopt zmax-muscle-memory`)。
真源代码: `tools/gui/muscle_memory.py`, `tools/gui/state_space_sim_real.py`,
`src/lerobot/memory/memory_graph.py`, `tools/gen_skill_dict.py`。

## 1. 测量纪律 (先看这条, 否则所有结论都不可信)

- **同 seed 不同进程/不同实例存在物理微扰** → 单次 A/B 对比会骗人。
  比较"开/关某机制"必须**同进程交替 A/B**:
  ```python
  for i in range(3):
      for tag in ('off', 'transformer'):
          os.environ['SS_LEW'] = '' if tag == 'off' else 'transformer'
          sim = RealStateSpaceSim(seed=1, vision=False, mode='insert', log=lambda *a: None)
          tr = sim.run(max_steps=900)
  ```
  (SS_* 开关在 `__init__` 读 env → 改 env 后新建实例即生效)
  实测教训: 单跑 off 成功 / on 失败 → 差点误判"新功能有害"; 交替 3+3 得到 off 3/3、on 1/3
  = **真回退**; 修复后 on 3/3。单次对比只是噪声。
- 基线必须 **SS_MUSCLE=0 隔离固化库**再比 (343 步基线 vs 400+ 步的假回归)。
- 报指标用**均值+中位+波动区间**; 逐 batch loss 值 (0.01~1.4 波动) 不能当趋势或"突破"。

## 2. 清库重练协议 (标杆库被污染时)

症状: 快通道命中但全链失败 / 影子 gate 全 ❌ (dx 偏差 12.6~188mm)。
判据: `data/muscle_memory.json` 桶数远超实际场景数 (实测 138 桶 = 20 个 seed 的跨代码版本累积)。

```
① cp data/muscle_memory.json data/muscle_memory.json.bak_before_clean_<ts>
② 写 {} 清空
③ 重置单例: MM._INSTANCE = MM.MuscleMemory(path=P)   # 否则引擎拿到内存旧库
④ 跑 6 轮同 seed (R0 无视觉, ~1s/轮): ep1-3 冷启动固化 → ep4-6 快通道命中验证
   判定 = ep4-6 全 done=True 且 sim._mm_hits > 0
```
清库后实测 (seed104 insert): 7 桶干净标杆; ep4-12 命中 180~185 帧/轮, 12 轮 100% 成功;
继续练 ep7-12 各段 dx_mean **逐轮下降** → "越练越顺"可实测复现 (α=0.3 融合):
```
接近 1.14→1.04 · 对位 1.65→1.57 · 下降 2.27→2.10 · 抓取 2.59→2.46
抬起 4.55→4.50 · 转移 3.11→2.70 · 插入 1.80→1.09   (mm)
```

## 3. 影子模式 (S3: 接新功能前先拿数据, 不盲训)

- 开关与快通道**解耦**: `SS_SHADOW`(默认开) / `SS_OBSERVE`(io 采集) / `SS_MUSCLE`(快通道)。
- 全段(含插入/完成)同帧对比"L2 标杆 vs 实际决策":
  `tr["shadow"][stage] = {n, du_mean, du_max, dx_mean, dx_max, gate_ok}`, gate_ok = dx_max < 2mm;
  同时写 `data/shared_memory.json` 的 `l3.shadow`。
- 读法: **du = L2 先验与实际下发的动作差** — du≈0 表示快通道精确重放(标杆就是实际动作);
  **dx = 同帧位置差 = 累积物理偏差**(前段起点微差), 不等于动作错。
  实测: 前 5 段 du=0.0; 转移/插入 du 0.93/0.35 → **插入段不可重放**(与"插入禁快通道"一致);
  影子数据自证"哪些段能用标杆"。
- 用途: 决定 S3 正式启用哪些段 + "是否需要为接 L2 先验做一次轻量微调" — 先有数据再训。

## 4. io 契约 + 技能词典 (S2: 让 L3/L4 能调用 L2 技能)

- `MuscleMemory.feed()` 同时记 `seg_io[stage] = {entry, entry_u, exit, exit_u}`,
  `end_episode` 成功轮写 `e["io"]` 并持久化 (键 `"<seed>|<stage>"`) → 上层才知道每个原子技能
  "从什么状态进 / 出什么状态", 才能编排与接力 (设计: docs/design/zmax_intent_bundle_3layer.md)。
- 技能词典: `tools/gen_skill_dict.py` → `models/skill_dict.json` {skill → Δz 动作基};
  检索侧 `src/lerobot/memory/memory_graph.py`: skill_dict() / intent_direct() / recall()。

## 5. 补救机制必须计入尝试次数 (LEW 回退实锤)

`SS_LEW=transformer|mamba_interleave` (自 `tools/gui/ss_lew_plugin.py`, 权重 `models/lew_{tag}.pt`)
= 插入遇阻第 1-2 次先让世界模型预测 peg 偏移 → 反向补偿微调 8 帧, 第 3 次才回退。

🐛 原实现: 修正窗口内不计 stall 且 `_stall_events` 不增长 → "遇阻→修正→再遇阻→再修正"
无限循环、**永不触发第 3 次回退** → seed1 实测 3/3 → 1/3, 900 步耗尽。
✅ 修复: 窗口结束校验 `self._insert_depth()` 是否推进; 无改善 → `_stall_events += 1`
(最多 2 次修正, 之后走回退, 与 SS_LEW 关闭路径一致) → 修复后 3/3, 平均步数还少 9%。

**通用规则**: 任何"再给一次机会"的补救机制(重试/微调/自适应)都必须占用一次尝试额度,
否则它会吃掉兜底回退, 表现为"接了新功能反而更慢/失败" — 也就是用户红线里的"性能回退"。
