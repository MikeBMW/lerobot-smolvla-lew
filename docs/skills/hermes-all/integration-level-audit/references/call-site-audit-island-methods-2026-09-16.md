# 断点/接线审计的**调用侧**三查 (2026-09-16 实录)

老倪贴了 `PerformanceManifold.predict_manifold` (`src/lerobot/manifold/manifold_layer.py:173`) 问
「这个断点怎么没有进入呢?」。这次答案不是分支/档位/跨进程 (那三类见
`breakpoint-not-hit-new-causes-2026-09-15.md`), 而是**调用侧**的问题:

## 第 6 类根因: 孤岛方法 —— 这个方法没有任何调用者

```bash
# ① 数调用者 (定义处不算): 只有定义 + 没有调用 = 孤岛
grep -rn "predict_manifold" --include=*.py src/ tools/ | grep -v __pycache__
#  → manifold_layer.py:87 (ContactManifold) / :173 (PerformanceManifold)  两个定义
#  → 唯一调用点 state_space_sim_real.py:3193, 调的是 self._mani_**cm** ← 接触流形
# ② 孪生对象核对 (同一模块里同类不同实例, 名字只差一个字母)
grep -n "_mani_pm" tools/gui/state_space_sim_real.py
#  → 只有 构造(3129) / 二态意图(3139) / evaluate(3149) 三处; 没有 predict_manifold
```

判据与话术:
- **`grep 调用者 = 0` 是最强信号**。"写在类里" "面板引用过" "双击能跑" 都不算接上 —— 只有被
  **每帧执行链**调用才算。
- **孪生对象坑**: 接触/性能流形、双脑、左右臂这类"同类多实例"名字极像, 调用点 grep 到的常是**另一个实例**
  ⇒ 你断点所在的那个永远是孤儿。核对时把**实例名**一起 grep, 不要只 grep 方法名。
- 汇报必须分级: "节点级: 单步可跑 (贴证据) / 档位级: **0 调用者 = 孤岛** (贴 grep 原文 + 行号)"。
  这类结论也和 `L2 审计命令` 的"孤岛 (links=0)"同族: 一个是图上没线, 一个是代码里没人调。

## 第 7 类: 调用点在, 但被"周期 / 导入 / 注入"三道门夹住

即便有调用者, 也可能几百帧才进一次, 或被静默跳过。逐条查包裹条件:

| 门 | 实例 | 判据 / 症状 |
|---|---|---|
| 周期门 | `if step % 25 == 0:` (流形/trace 块) | 只有 25 的倍数帧进; 跑 ≥25 帧 (300 步 ≈ 进 12 次) |
| 模块门 | `if _MANI_MOD is not None:` (importlib 加载流形模块) | 导入失败 → 整块不进, **不报错**, 计数恒 0 |
| 注入门 | `if self._mani_cm.predictor is not None:` | predictor 通常**已经**注入 (构造时传了 `_pred`), 别误判成"没给预测器" |

## 诊断顺序 (省时间的那个)

**数调用者 → 核孪生对象 → 查包裹门 → 才查分支 / 档位 / 跨进程 / 绑错文件**

本轮就是跳过前两步白绕了半天: predictor 明明注入了 (`PerformanceManifold(..., predictor=_pred)`),
真因只是"没有任何地方调这个函数"。下次遇到「断点不进」先花 10 秒跑这两条 grep。

## 附带口径澄清 (避免把共用通道当成两条)

引擎里"预测流形"只有一条: `_mani_cm.predict_manifold` 算出 6 维 `_mpred`, 发布到 `_mani_out["pred"]`
供**接触 + 性能两个节点一起显示**; 性能流形自己的执行/显示值来自解析 `_mani_pm.evaluate()`
(3149, η/δ⊥)。所以审计表里"流形专家→性能流形 = 有数据"指的是这条**共用通道**,
**不是** `pm.predict_manifold` —— 报口径时要说清, 否则就是拿别人的数据给孤岛背书。
