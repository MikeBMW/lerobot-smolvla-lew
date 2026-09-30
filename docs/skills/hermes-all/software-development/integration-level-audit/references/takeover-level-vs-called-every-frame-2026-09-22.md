# 「每帧被调用」≠「真接管输出」 — INTACT L4 接管级审计 (2026-09-22)

老倪问「**L4层INTACT集成进来了么？**"。本文是那次审计的完整取证与结论口径。
核心收获: 集成审计在 L2 (档位链) 之后**还有一道闸**, 且它最容易被自己判错 ——
**组件每帧真被调用了, 但每次都被拒, 输出仍来自解析链。**

---

## 1. 三级判据 (逐级实测, 缺一不可)

| 级 | 判据 | 本例实测 |
|---|---|---|
| 代码在位 | 引擎接线 + 集成包可导入 | ✅ 引擎 4 处接线 (`_intact_ready` @150 / 挂载 @430 / L4 通道 @441 / stats) + `policies/intact/` 全套 |
| **每帧被调用** | 运行统计的 `refused*` 计数 ≈ 总帧数 | ✅ 跑 120 步 → `refused_map=120` |
| **真接管输出** | `src`/`source` 字段是否变更 | ❌ `u_ff_src='analytic(未标定)'` ⇒ **没接管** |

**关键读法**: `refused*` 计数的是**拒绝**次数, 不是"调用次数"。把 `refused_map=120` 说成
"调用了 120 次"是错的口径 —— 正确说法是 "**每帧都进了调用点, 但 100% 被拒**"。

## 2. 同模型两条路径: 前置条件不同, 结果相反

| 开关 | 路径 | 前置条件 | 实测 |
|---|---|---|---|
| `SS_INTACT=1` | 标定映射 → u_ff | 标定文件**过闸** | ❌ refused_map=**120/120**, src=`analytic(未标定)` |
| `SS_L4_INTACT=1` | decoder **量纲逆运算** (`act×K_ACT`) | **无需标定** | ✅ refused=**0** · calls=15 · reuse=105 · src=`intact(chunk×K_ACT=0.5)` · w=0.3 |

`calls + reuse = 15 + 105 = 120 = 总帧数` ⇒ 全覆盖, 且 `src` 从 `analytic` 变为 `intact(...)`
= **真接管的硬证据**。

## 3. 为什么标定必然失败 (数学必然, 不是工程没做通)

已有标定报告 (`reports/intact_calib_action_20260912_151221.json`, n=1661, 9 folds):

```
INTACT 动作 (10维 chunk) → 引擎 dx/dy/dz 映射   R² = -0.1471   (负!)
INTACT 潜空间 z(192→PCA16) → 同上                R² = -0.3269   (负!)
```

**负 R² = 比常数基线还差 = 无可学对应关系**。根因是在役权重跨域:
**OGBench cube 数据**训的权重 → 却要驱动 **Z-MAX 光模块插拔**引擎 ⇒ 两套动作空间无对应。

⇒ **根治只有两条**: ① 用**自家数据重训** (zmax 数据 + 训练链已拉通) ② 走**无需标定**的路径。

## 4. 诚实拒绝是正确行为 (审计时要分开说)

引擎的判定 (`state_space_sim_real.py` ~1352):

```python
ad_ok = self._intact_adapter is not None and getattr(self._intact_adapter, "enabled", False)
if not ad_ok and not self._intact_shadow:
    st["refused_map"] += 1
    st["u_ff_src"] = "analytic(未标定)"
```

标定不过闸 → **宁可拒绝也不硬映射噪声**。这正是老倪要的"零容忍假接入", **不是 bug**。
审计报告必须把 "**诚实拒绝**" 与 "**接不进去**" 分开表述, 否则会把好设计报成故障。

## 5. 审计工具自己会造假阴性 (先怀疑探针)

`attach_intact(node, adapter)` 的调用方:

```
tools/gui/simulink_module.py:12027   ← GUI 画布路径 (设 SS_INTACT=1 + attach_intact)
tools/probe_*/diag_*/ab_*            ← 诊断/对照工具
(引擎自身 **不调** 它)
```

⇒ **headless / 裸引擎构造 `RealStateSpaceSim()` 不会自动挂载**, 必须自己调 `attach_intact()`。
我第一次只设了 `SS_INTACT=1` 就下结论 → `_intact_node=None` → 统计全 0 → **差点误报"未集成"**。

**纪律**: 审计前先 `grep -rn 'attach_\|register\|mount'` 找集成点的调用方;
若调用方只在 GUI/外部工具里, headless 审计脚本必须自己补挂载, 并把这个差异写进结论。
(顺带值得报给用户的工程建议: 引擎在开关打开时**自挂载**, 消掉一类"忘了挂"的坑。)

## 6. 回答模板 (老倪认这种结构)

> 「代码在位 ✅ (引擎 4 处接线 + 集成包可导入) · **每帧真调用** ✅ (refused=120 为证)
> · **但动作没生效** ✗ (100% 被拒, u_ff 仍是 analytic)。
> 走 `SS_L4_INTACT` (无需标定的量纲逆运算) 则真接管: refused=0 · src=`intact(chunk×K_ACT=0.5)` · w=0.3。
> 标定路径不通是**数学必然** (跨域权重, 标定 R²=-0.147), 根治 = 自家数据重训。」

**禁止** 一句"集成了"或"没集成" —— 三级分开说才既诚实又可执行。

## 7. 可复用的探针形状

```python
# 1) 设开关 + (headless 必须) 显式挂载
os.environ["SS_L4_INTACT"] = "1"; os.environ.pop("SS_L4_INTACT_SHADOW", None)
sim = RealStateSpaceSim(seed=104, vision=False, log=lambda *a: None)
sim.attach_intact(IntactNode(horizon=8), None)          # ★ GUI 会做, headless 得自己做
# 2) 跑有界步数, 只读统计
tr = sim.run(max_steps=120)
print({k: sim._l4_stats[k] for k in ("calls","reuse","refused","blend","src","w")})
# 3) 判据: refused==0 且 src 不含 'analytic' ⇒ 真接管
```

同类探针 (既有): `tools/probe_l4_callchain.py` · `tools/probe_l4_direct_count.py` ·
`tools/ab_intact_uff.py` · `tools/diag_intact_stage_align.py`。
