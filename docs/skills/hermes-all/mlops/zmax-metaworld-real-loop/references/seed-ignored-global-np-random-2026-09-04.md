# metaworld reset(seed) 忽略 seed — 布局随全局随机状态漂移 (2026-09-04 静静复现实锤)

修正 SKILL.md 契约 #3: 「解冻→reset(seed)→冻结」**还不够**。

## 实锤
- metaworld `env.reset(seed=…)` 的 seed 参数被忽略 (gui-venv311/.../metaworld/sawyer_xyz_env.py
  reset docstring: "seed: The seed to use. Ignored, use `seed()` instead.")。
- `_freeze_rand_vec=False` 时 `_get_state_rand_vec()` 走 **全局 `np.random.uniform`**
  (L704-713: freeze → 用 `_last_rand_vec`; seeded_rand_vec → `self.np_random`; 否则全局)。
  项目代码从不调 `env.seed()`, seeded_rand_vec=False → 恒走全局 np.random。
- **后果**: 同 seed 的布局由进程全局随机状态决定。测试/验收套件里前序用例若创建过
  RealStateSpaceSim 并 `_reset()` (共享 `_ENV` 全局单例, state_space_sim_real._make_env),
  后续 quick_run 的"同 seed"布局已漂移 → 500 步插不进孔, 误判控制器/误判回归。
- **复现数据** (seed=100 销头初位 d.site_xpos[pegHead]):
  干净进程 [0.0283, 0.5398] vs 先 `_reset(0)` 污染后 [0.0345, 0.6169] → 0/1 未完成;
  修复后干净与污染一致, quick_run 2 集 = seed100 难例失败 + seed101 成功 = 1/2 (确定性)。
- 真实化基线 6/12 的不稳部分是此污染 artifact, 非纯控制器问题。

## 修复 (state_space_sim_real.py RealStateSpaceSim._reset)
```python
import numpy as _npg
env._freeze_rand_vec = False
_npg.random.seed(seed * 7919 + 13)   # 采样前固定全局随机源 → seed 真正决定布局
env.reset(seed=seed)                 # metaworld 忽略此 seed, 走全局 np.random (已被上一行固定)
env._freeze_rand_vec = True
```
同 seed 恒同布局 (可复现, 非造假 — 不同 seed 仍给不同布局)。副作用: 固定进程全局
np.random — 验证/仿真代码本就不依赖"未固定随机", 安全。

## 诊断法
疑测试顺序耦合: 打印 site 初位对比 (干净 vs 污染后) 是否漂移, 先别怀疑控制器。
教训: 涉及 metaworld 的测试失败, 第一查布局确定性 (site 初位), 第二查断言是否摆设
(见 zmax-console references/test-acceptance-verification-2026-09-04.md)。

## 关联
- 闭环用例断言语义: 单集"必完成"不是稳定契约 (seed100 布局 = 控制器难例) →
  quick_run 2 集 ≥1 完成 (贴近基线成功率语义)。
- t_sched_real (verification_layer.py) 从"import 成功即 True"假过改为真跑 2 集 ≥1。
- 验收通道: tools/test_acceptance_run.py 全量真跑 (auto 339 + semi 16)。
