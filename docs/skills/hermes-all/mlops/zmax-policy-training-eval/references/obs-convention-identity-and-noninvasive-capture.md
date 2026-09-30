# obs 口径辨明 + 非侵入采集法（2026-09-23 收尾）

> **修正 `references/joint-training-holdout-eval-corrections.md` §一 铁律③。**
> 那篇写"要造同源数据必须**先给引擎加记录**（或从 sim.env 直取）" —— 实际上
> **有现成的非侵入做法, 不用改引擎文件**。本文给出实测裁定的口径 + 可用代码。

---

## 一、正确口径 = `sim.env._get_obs()[:39]`（实测裁定, 不靠注释推断）

```
候选                             平均逐维均值差 (与 v6 对比)
tr["obs"]       (引擎 fused 39)  = 0.1793     ✗
env._get_obs()[:39]  (env 原生)   = **0.0273**   ✓  ← 正确
```

铁证维度指纹（这是判别关键，别只看总差值）：
```
idx 7/8 : v6 = 0.000±0.000   ←→   env 0.000±0.000 ✓   |  tr 0.011 / 0.485 ✗
idx 10  : v6 = +0.999        ←→   env +1.000      ✓   |  tr -0.243      ✗
```

引擎里两个同名 39 维并存，容易被注释绕晕：
- `_obs39()`（注释写"训练同源观测 (env._get_obs() 前 39 维)"）**就是** env 原生 ✓
- `tr["obs"]` 是 `fuse_sensors(concat([cur18, prev18, target3]), force, tactile4)[:39]`
  的 **fused** 向量 ✗

**辨明工具（已落盘）: `tools/identify_obs_convention.py`** — 跑一次输出上面这张表。
判据：`平均逐维均值差 < 0.06` 视为同源。**换数据源前后各跑一次。**

---

## 二、★ 非侵入采集法：挂 `fuse_sensors` 钩子（每步恰好 1 次 → 1:1 对齐）

```python
# 在 sim.run() 之前挂上; 不需要改 state_space_sim_real.py（它可能被别的会话维护）
_env_obs = []
_orig_fuse = sim.perception.fuse_sensors


def _fuse_hook(visual39, force, tactile4, _o=_orig_fuse, _s=sim, _b=_env_obs):
    try:
        _b.append(np.asarray(_s.env._get_obs(), dtype=np.float64).ravel()[:39].copy())
    except Exception:
        pass
    return _o(visual39, force, tactile4)


sim.perception.fuse_sensors = _fuse_hook
tr = sim.run(max_steps=a.steps)        # 钩子在每步 obs 融合处触发一次

# ⚠️ 采用前必须校验长度, 不符就回落并打印 —— 不许静默用错源
_tr_obs = tr.get("obs", [])
if _env_obs and abs(len(_env_obs) - len(_tr_obs)) <= 1:
    obs_l = _env_obs
else:
    obs_l = _tr_obs
    print(f"⚠️ env obs 长度不符 ({len(_env_obs)} vs {len(_tr_obs)}), 回落 tr['obs']")
```

**为什么挂 `fuse_sensors` 而不是 `env._get_obs`**：后者**每步被调 2 次**
（实测 340 步 → 683 条记录）→ 与轨迹步对不齐；`fuse_sensors` 每步恰好 1 次。

---

## 三、验证（改完必须跑，别只看代码）

```
修复后 L5 造数据的 obs 前 12 维均值:
   v6: [0.049 0.544 0.147 0.434 0.055 0.546 0.112  0.    -0.    0.031 0.999  0.  ]
   L5: [0.065 0.610 0.119 1.000 0.088 0.617 0.025 -0.     0.   -0.    1.000  0.  ]
   平均逐维均值差 **0.1793 → 0.0496**  ⇒ ✅ 同源通过
   (idx3 是工件高度维; L5 变体高度不同属正常差异, 不是不同源)
```

全量重跑产物：`datasets/l5_gen_v3.h5`。
**`l5_gen_v1.h5` / `l5_gen_v2.h5` 的 obs 源错了 —— 废弃勿用**（v1 还外加 pixels 全零）。

---

## 四、附带修好的另一处：`--vision` 必须开

```
引擎 `_key_frames` **只在 vision=True 时采集**
  （在 perception refresh 内, 且需同阶段连续 ≥6 帧才开始记）
→ vision=False 造出的 pixels **全是 0**（本次 75k 帧报废）
验证真渲染: 非零率 > 0.99 且均值 ~130（全零/均值 0 → 废数据, 重造）
诚实标注: pixels = "该阶段关键帧按阶段复用", 不是每步独立渲染
```

---

## 五、教训归档（两条通用）

```
① 同名同形状 ≠ 同源 —— 判据只能是**逐维数值分布**, 并用指纹维度交叉验证;
   靠源码注释推断口径会翻车（注释写"同源"的那个方法确实对, 但别处同名向量是错的）
② 修数据源缺陷时优先找**非侵入挂载点**（monkey-patch 既有调用点 + 长度校验 +
   不符即回落打印），而不是改共享文件 —— 引擎可能正被别的会话维护
```
