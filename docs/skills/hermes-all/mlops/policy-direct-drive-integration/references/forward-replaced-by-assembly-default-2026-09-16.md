# ⚠️ 默认口径下前馈 `forward` 主路径不会被执行 (2026-09-16 实测)

> 请下次维护时把本文件的两行结论补进 SKILL.md §1 (落地写法) 与 §6 (Pitfalls):
> ①「装配期实例覆盖类方法」这类替换会让真身 body 与守卫计数**双双恒 0**, 不是域判定挡的;
> ② L4 直驱档的执行参考是引擎本帧的 `u`, `u_ff` 系前馈**不决定动作**。
> (SKILL.md 的写入本轮被 read-before-write 守卫拒绝, 故先登记在此。)

## 镜像的另一半: 引擎自己把 `forward` 换掉了

`references/taking-over-a-controller-guard.md` §1 记的是"**我们**把引擎控制器整个换掉 → 我们放进去的
模型没有兜底"。这里记相反的一半 —— 引擎**默认就在替换自己**:

```python
# tools/gui/state_space_sim_real.py (构造 RealStateSpaceSim 时)
if os.environ.get("SS_USE_MLP") == "1":
    print("🧠 SS_USE_MLP=1: 分层伺服 (前段蒸馏 MLP 主执行 + 插入段解析)")
else:
    self.accel.forward = self.accel.analytic_forward      # ← 实例属性覆盖类方法
```

- 全仓只有这一处读 `SS_USE_MLP`, **GUI 任何档位 (含 L4) 都不设它** ⇒ 生产口径恒走 else
  ⇒ `parallel.py` 里 `def forward` 的 body (域判定 + 蒸馏 MLP 前向)**一行都不执行**;
  插断点自然永不进, `n_mlp` / `n_guard` 双计数**恒 0**。
- 判据: 症状若是"断点不进 + 内部计数恒 0 + 调用侧每帧都在调" ⇒ **函数身份被换掉**,
  与"域判定/守卫拦截"(守卫计数涨) 症状恰好相反, 别把后者当解释。

## 两臂实测 (seed 0 / 32 步 / mode=insert / vision=False)

| 观测 | 臂A: GUI 默认 (不设 `SS_USE_MLP`) | 臂B: `SS_USE_MLP=1` |
|---|---|---|
| `accel.loaded` / `_ff is None` | True / False (权重在, 不是加载失败) | True / False |
| 实例 `__dict__` 覆盖 `forward` | **True** (→ `analytic_forward`) | False (→ `forward`) |
| 引擎每帧调用 `acc.forward` | 32 | 32 |
| **真身 body 进入次数** | **0** | **32** |
| `n_mlp` / `n_guard` | 0 / 0 | 32 / 0 |
| 域判定真值 | 未评估 | d_guard 0.131/0.163/0.178 (门 0.25, 超门 0/32); 归一化 max\|xn\| 1.583 (门 4.0, 超门 0/32) |

⇒ 放它进就 **32/32 全走 MLP**, 这批帧不是被守卫挡的。要真进: 起 GUI 前 `export SS_USE_MLP=1`。

## 计数要用对层次 (否则取证无效)

- 包**类**方法 `cls.forward` = 真身进入次数 (实例已覆盖时它恒 0 —— 这个 0 就是结论);
- 实例已覆盖时再包**实例属性** = 调用侧次数 (证明调用侧通、断的是函数身份);
- **不要**在被换过去的 `analytic_forward` 上计数: 赋值时捕获的是原 bound method,
  事后包类方法不生效 (实测无效)。

## 另外两条同档位的坑

1. **插入段恒解析**: `state_space_sim_real.py` 同一函数里 `u_ff = (analytic_forward(obs)
   if st_now == "插入" else self.accel.forward(obs))` ⇒ 即使 `SS_USE_MLP=1`, 插入段也不进 MLP
   (分层伺服本意), 报告里要写明参与阶段, 别拿"整轮成功率"覆盖它。
2. **"进了"≠"接管了"**: L4 走 `install_direct_act` 包 `sched.decide`, 解析指令被丢弃;
   `u_ff` 只用于阶段标签 / 夹爪 / `build_skill_ctx`, **执行参考是引擎本帧的 `u`**
   (`act = clip(u[:3]/K_ACT)`), 模型动作与 `u` 比 cos 后融合或否决 ⇒ 前馈 MLP 进不进
   **不决定动作**。汇报必须分开写"每帧被调用 (次数)"与"输出参与执行 (权重/融合/否决)"。
3. **诊断前向≠主路径**: 同文件另有每步 `acc._ff(obs[:39])` 只为灌"前馈探针"直方图,
   绕过守卫也不走 `forward` ⇒ "探针有激活但 `n_mlp`=0" 两者不矛盾, 别相互印证。

> 完整三步归因 + 汇报模板: `integration-level-audit` →
> `references/breakpoint-not-hit-assembly-monkeypatch-2026-09-16.md`
> (同技能 `references/00-INDEX-breakpoint-not-hit-series.md` 有症状→根因速查表)。
