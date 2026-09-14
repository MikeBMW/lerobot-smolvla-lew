# 记忆层集成阶梯 (L2→L3→L4→总装) — 第一版 30 格实测 + 数据一致性修复 (2026-09-14, v5.5.46/47)

> 本文是 SKILL.md「🧲 记忆层集成阶梯」小节的展开。老倪口径: "集成 L2肌肉/L3流程/L4工作/总装记忆 …
> 稳步推进, 从 L2 到 L3 再到 L4 … 我要看到最终成功抗干扰的插拔, 且高效稳定 … 数据一致性最重要"。

## 1. 阶梯台 (tools/mem_ladder_integration.py)

| 维度 | 内容 |
|---|---|
| 臂 | `off` / `L2` / `L23` / `L234` / `assy` (总装仲裁) — 只改 `data/memory_layers.json` 开关 |
| 干扰档 | `none` = 引擎 `cap=l3` (无注入) · `disturb` = 引擎 `cap=l4` (**真注入**来料移位/转向 + 恢复预算×2) |
| manifest | 权重 sha256+epoch · 反归一化 stats sha256+action_space · 逐层开关快照 · 引擎/桥/势场/工具源码 sha256 + git rev · **记忆状态文件 + models/*.pt sha256** |
| 续跑 | 每格跑完 append `reports/mem_ladder/runs.jsonl`; 同 (manifest_hash, arm, disturb, seed) 自动跳过 |
| 历史 | `reports/mem_ladder/ladder_history.csv` (append-only) → 换 ckpt/换配方后同一格直接对比 |
| 闸 | N1 L2 准确性 / N2 L23≥L2 / N3 L4 抗干扰 / N4 总装≥任一臂 / N5 零搜索+调用/步≤1.05 / N6 跨 seed 深度 std≤25mm |
| 哨兵 | `~/.hermes/scripts/mem_ladder_watch.py` (no_agent cron **every 20m**; 崩溃格上报 / 进程死且格未跑完**自动重启** / 新结论推飞书) |

⚠️ cron 建任务: schedule 必须写 `every 20m` — 只写 `20m` 会建成**一次性**任务 (实测 regex 陷阱)。

## 2. 第一版 30 格结论 (manifest 6fc5fe9f60fa, v4-ep2 权重)

```
臂     干扰     n  模型成功  插入距离(mm)         调用/步 介入步  w̄     解析链对照
off    none     3  0/3     588.5 (std 55.0)     1.00    0     0.0    7/9 成功 (65mm)
L2     none     3  0/3     609.4 (std 14.9)     1.00  3000    0.1
L23    none     3  0/3     605.9 (std 21.7)     1.00  3000    0.1
L234   none     3  0/3     605.9 (std 21.9)     1.00  3000    0.1   ← 与 L23 逐位相同
assy   none     3  0/3     610.0 (std 22.6)     1.00  3000    0.1
off    disturb  3  0/3     605.2 (std 44.0)     1.00    0     0.0    4/7 成功 (65mm)
L2     disturb  3  0/3     585.4 (std 64.2)     1.00  3000    0.1
L23    disturb  3  0/3     610.8 (std 60.2)     1.00  3000    0.1
L234   disturb  3  0/3     610.8 (std 60.2)     1.00  3000    0.1   ← 与 L23 逐位相同
assy   disturb  3  0/3     610.8 (std 60.2)     1.00  3000    0.1
```
- **结论: 没有提升。** 模型直驱 0/30 · 记忆层每步介入 (3000/3000) 但 w̄ 恒 0.1 ·
  L234/assy 与 L23 **逐位相同** = 后加层零可测贡献 · 解析链能插入 (65mm) ⇒ 几何可达, 差的是"谁出力"。
- 闸: N1 ❌ (609.4 vs 588.5mm) · N5 ✅ · N6 ❌ (std 60mm) · **N2/N3/N4 是"全 0 空过"** (0≥0 天然成立)。

## 3. 两个根因 (代码级)

1. **场权写死太低** (`src/lerobot/memory/potential_field.py::blend_action`):
   旧式 `w = w_max·max(conf, w_floor)`; 桥用 `w_max=0.5, w_floor=0.2`, 现场 `conf ≡ 0` (离最近轨迹管 207mm)
   ⇒ w̄ 恒 **0.1** = 介入全部步数但只出力 10%, 扳不动 600mm 误差。
   已修 (v5.5.47, **增益调度**): `far = clip((d_perp−d_near)/(d_far−d_near),0,1)`,
   `w = max(w_max·max(conf,w_floor), w_far·far)`, 默认 `w_far=0.85 / d_near=30mm / d_far=150mm`
   — 管内维持原公式 (**不回退**), 出管才让记忆场主导; `far / w_far_gain` 写进逐步诊断。
2. **模型动作塌缩** (天花板): `IntentActionActor` 输入 = 潜槽 `[z_t, m_t, z_t·m_t]` + 上一动作嵌入,
   **无本体/几何输入**; 数据集 `optical_insert_v4.h5` 里有 39D `observation` 但
   `grep observation train.py jepa.py module.py` **零命中** = 通道从未被消费 ⇒ 224²/patch14 潜空间补不出
   亚毫米几何 ⇒ 动作头输出条件均值 ⇒ 幅度仅教师 7~22% (v3/v4/v5 同病) ⇒ 判闸输常数基线。

## 4. 数据一致性真 bug (本工程最贵的一条, 已修)

**症状**: 同 seed / 同 cap / 同权重 / 同代码, 解析链从 `65.26mm(done)` 漂到 `58.02mm(not done)`;
而**纯模型路径逐位复现** (649.33 / 667.13 两次完全一致) ⇒ 差异只出现在"读记忆"的路径上。
**根因**: `data/muscle_memory.json`(标杆/冠军轨迹) · `assembly_memory.json`(台账) · `shared_memory.json`
被引擎**逐局写入** (成功即固化) —— 不在 manifest 里、也不在格间复位 ⇒ 同口径被悄悄破坏。
**修法**: ① 可变状态文件 + `models/*.pt` 全 sha256 纳入 manifest; ② 每 manifest 建快照目录,
**每格开跑前复位到快照**; ③ 跑完把该格状态另存 `reports/mem_ladder/state_after/<tag>__<file>` 当证据;
④ **续跑用快照 sha 算 manifest hash** (先算不含状态的 core hash → 做快照目录名 → 把快照 sha 并进去重算),
否则 live 漂移会让 manifest 每次变 → 断点续跑失效。
**通用判据**: 任何**运行过程会写**的文件都是实验条件; 没进 manifest + 没逐格复位 = 这批对照不成立。

## 5. 迭代纪律 (下一步怎么走)

- **判闸是快闸, 阶梯是慢闸**: `tools/intact_replay_check_v3.py` (数据集真帧 120 帧, ~1 分钟) 用来迭代配方;
  阶梯一格 ~6 分钟 (1000 步) ⇒ **先过判闸再上阶梯**。闸值: `model_xyz_mae < const_xyz_mae`
  且预测幅度 ≥ 教师 50% (<30% 判为塌缩)。
  v5 已判 4 个 epoch: MAE 0.0435 → 0.0424 → **0.0560**, 幅度 22.4% → 14.5% → 19.1%, **全未过闸且越训越差**
  (接力守护 `l4_ab/train_intact_optical_chain.sh` 起的是 v5r2, 同配方续训 — 配方问题, 不是训练量)。
- 下一版 (同 manifest 比对, 历史 CSV 直接看提升): ① 场权增益调度后先跑 1 seed × 3 臂 × 2 干扰档探针
  (看插入距离能否掉到 65mm 附近); ② 有效再跑全量 30 格; ③ L4 障碍/孔轴几何吸引项
  (L234 与 L23 完全相同 ⇒ 该层当前无贡献); ④ v6 给 actor 加 39D 状态通道 (opt-in `state_dim` 默认关 → 老配置逐位不变);
  ⑤ 抗干扰扰动增广数据。
- **诚实上报模板**: 先说"有没有提升" → 给同口径表 (臂 × 干扰档 × seed) → 标"空过"的闸 → 说清剩余反向/失败原因;
  回退不当成功报。
