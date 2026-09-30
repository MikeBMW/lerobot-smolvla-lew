---
name: robot-memory-layers
description: "Use when 优化机器人分层记忆 (肌肉/流程/工作/宏观层)."
version: 1.0.0
author: Hermes Agent
license: MIT
tags: [memory, layered-memory, potential-field, muscle-memory, macro-memory, zero-regression, robot-policy]
metadata:
  hermes:
    tags: [memory, layered-memory, potential-field, muscle-memory, macro-memory, zero-regression, robot-policy]
    related_skills: [layered-capability-stack, integration-level-audit, zmax-policy-training-eval]
trigger: "Use when the user asks to 优化/设计 多层级记忆系统, 或提到 L4 工作记忆 / L3 流程记忆 / L2 肌肉记忆 / 总装记忆 / Qwen 顶层宏观记忆, or when a memory layer is wired in but appears to have no effect on task success."
---

# 机器人分层记忆系统 (L2 肌肉 → L3 流程 → L4 工作 → 总装 → LLM 顶层宏观)

## 五层语义与落点 (老倪定义, 2026-09-19)

> "L4 是工作记忆, L3 是流程记忆, L2 是肌肉记忆, **总装记忆对应大模型的 Qwen 顶层宏观记忆**,
> 与状态空间工程的记忆保持同步。"

| 层 | 语义 | 典型实现 | 典型数据文件 |
|---|---|---|---|
| **顶层宏观** | 跨任务画像 / 失败归因 / 分阶段建议 | `memory/macro_memory.py` (LLM 接口 + 规则兜底) | `data/macro_memory.json` |
| **总装** | 跨层仲裁 (接触段下层优先 / 自由段上层优先) + 台账 | `MemoryLayerBridge` | `data/assembly_memory.json` |
| **L4 工作** | 现场几何 + 抗干扰 (世界模型预测项常未接=恒 0) | `GlobalPotentialField` | `shared_memory.json#l4` |
| **L3 流程** | 阶段时序调度 `Σw_k(t)≡1` (raised-cosine 交接) | `ProcessPotentialField` | `shared_memory.json#l3` |
| **L2 肌肉** | 冠军轨迹固化, 命中即整段重放前馈 | `SkillPotentialField` | `data/muscle_memory.json` |

**统一接口 = 标量势场 `Φ(x)`, `−∇Φ` = 意图** (只传"往哪走", 不传技能标签)。
执行钩子: `u = (1−w)·u_model + w·u_field`, 逐层开关 JSON (全关 = 恒等 → 可断言零回退)。

这条阶梯与 `layered-capability-stack` 同构: 记忆层只给**意图/条件**, 执行永远由最下层收口。

## 一、五条设计纪律

1. **只读下层** — 上层 `sync()` 不得改写下层数据文件。用例断言下层文件 **mtime 不变**: 同步 ≠ 污染。
2. **幂等** — 用过的事件按指纹 (`ts|task|steps|done` 的 sha256) 去重; 重复 sync 的 `fresh` 必须为 0。
3. **LLM 诚实** — 有 LLM 端点才调; 没有就用确定性规则归纳, 并**如实标 `llm=False`**。
   绝不假装"大模型分析过"。宏观层只产**建议**, 不写执行量。
4. **原子写** — tmp + `os.replace()`, 断电不留半截文件。
5. **逐层开关默认关** — 不设开关 = 逐位零变化。**零回退硬证据 = 关闭时新属性不存在**
   (`hasattr(sim, "_macro_sync") == False`), 比"输出看起来没变"强得多。

## 二、四个真坑 (记忆层"接了但等于没效果"的根因)

1. **喂错坐标系** (最隐蔽) — 势场消费的点必须与冠军轨迹**同源**。若轨迹记的是**夹爪位置**
   (`obs[0:3]`) 而喂进去的是**工具/工件端点** (`peg_head`), 同一局势下两者可差 **176mm**
   ⇒ 势场在自己坐标系之外求梯度, 意图 = 噪声。
   实锤法: 换源前后打印 `d_perp` — 好的源应让 `d_perp` 从 0.13m 掉到 **1e-4~2e-2 m**
   (状态本来就贴在轨迹管上) 且相位正常推进; 坏的源会越走越远。
2. **夹爪通道缺失** — 融合时若只混 `u[:3]`(XYZ), **夹爪维 `u[3]` 永远来自模型** ⇒ 远场/纯场救援时
   夹爪从不闭合, 工件根本没被抓起 (探针实锤: 1000 步工件位置一动不动)。
   修法: 势场存 4 维冠军序列 + 按弧长取**当拍冠军夹爪指令**, 用**同一个 w** 混进 `u[3]`
   (管内仍听模型的 = 不回退)。
3. **势场桥不得新建引擎实例** — 若构造障碍场时不把**当前引擎的几何**传进去, 实现会新建第二个
   仿真实例并 reset(), 而底层 sim 常常**进程内共享** ⇒ 正在跑的场景被改写 (实测工件瞬移毫米~十几毫米),
   所有含该层的 A/B 全部失真。
   纪律: `Bridge.from_real_data(..., use_engine_geom=True, geom=self.geom)`。
4. **先量方向, 再谈"抵消"** — 现象是"记忆层与模型动作互相抵消 / 合成≈0"时, **先量冠军轨迹方向与
   真实前进方向 Δx 的 cos**, 再看融合环节。实测 406 段冠军轨迹 **0 段反向** (中位 +0.99)
   ⇒ 轨迹没问题, 锅在喂进去的坐标系/通道 (即坑 1/2)。不量就改公式 = 白改。

## 三、阶梯台取证 (逐层叠加 + 同口径)

判"记忆层有没有用"不能只跑全开/全关, 必须**逐层叠加**看单调性:

```
--arms off,L2,L23,L234      # 逐层叠加, 看单调性
--disturbs none,disturb     # disturb = 真注入来料移位/转向 (测抗干扰)
--seeds / --steps / --ckpt  # 同 seed 同口径; 权限允许时每臂独立进程
```

- **manifest 冻结**: 权重 sha256 + 反归一化 stats + 记忆开关快照 + 源码 sha256 + git rev。
  换任一项 = 另一批历史行, 不会混着比。
- **append-only 历史** (`ladder_history.csv`): 每格跑完即写 → 断点续跑, 不重复烧机时。
- 跑前备份开关文件, 跑完**自动恢复** (别留副作用)。
- **判据看单调性, 不只看首尾**: `off > L2 > L23 > L234` 单调改善 = 逐层真在起作用;
  中间某层突然变差 = 该层有问题。

### 闸门设计参考 (6 道不后退闸)

`N1` 下层准确性不回退 · `N2` 上层叠加 ≥ 下层 · `N3` 抗干扰档 ≥ 自身无干扰档 (且 ≥ 基线干扰档) ·
`N4` 仲裁层 ≥ 任一单层 · `N5` 高效零搜索 (候选搜索 = 0 且调用/步 ≤1.05) · `N6` 跨 seed 稳定 (std 阈值)。

⚠️ **缺数据的闸要标"缺数据", 不能当回退报**。只跑了无干扰档时 N3/N4 是 `None%` 而非 0% —
汇报必须写清"本次未跑干扰档, 该项缺数据"。

## 四、解读结果: 区分"记忆层贡献"与"基线贡献"

一次典型复核 (同 seed, 1200 步, 无干扰):

```
臂      成功   插入mm    距成功线
off     0/1    194.0     +129.0
L2      0/1    185.6     +120.6
L23     0/1    183.3     +118.3
L234    0/1    182.9     +117.9
```

正确读法:
- ✅ 单调正向 (每层 +8~11mm) ⇒ 记忆层**不再反向抵消**, 修复生效、可安全重开。
- ⚠️ 但总贡献 **11mm** vs 缺口 **118mm** ⇒ **瓶颈在基线本身**, 记忆层是锦上添花而非雪中送炭。
- 换权重带来的变化 (基线 649→194mm, **−455mm**) 远大于记忆层贡献 ⇒ 主因是模型权重。

**别把"记忆层小幅正向"汇报成"记忆层有效提效"**; 要给"贡献 vs 缺口"的比值。

## 五、汇报口径

分三段, 不合并不夸大:
1. **接线段** — 逐层计数/hash/是否真介入 (可复现命令)。
2. **质量段** — 阶梯台逐臂数字 + 单调性 + 各闸状态 (缺数据的老实标缺数据)。
3. **归因段** — 记忆层贡献 vs 基线缺口, 明确指出瓶颈在哪一层/哪个组件, 以及下一步。

## 参考

- `references/multilayer-memory-ladder-2026-09-19.md` — 一次完整的五层记忆系统落地实录:
  宏观层 API 与引擎挂点、四个坑的实锤数字、阶梯探针结果表与解读。
- 相邻技能: `layered-capability-stack` (分层契约/零回退取证/功能↔用例矩阵)、
  `integration-level-audit` (判定"是否真接进执行链")。
