# 「断点不进 / 真身不执行」第三类根因: 装配期把函数换掉了 (2026-09-16 实测)

老倪原话: 「选择 L4 功能后, 这个代码 `def forward(self, obs)` … **怎么没有进入呢**?」
判据先摆清: 域判定/守卫类拦截会让**守卫计数涨** (n_guard++), 而"函数被换掉"是
**所有内部计数恒 0** + 调用侧计数满格。两者症状完全不同, 一眼可分。

## 结论 (实测, 非推断)

真因不在被问的那段代码里, 在**引擎构造时的一行赋值**:

`tools/gui/state_space_sim_real.py:369-372`

```python
if os.environ.get("SS_USE_MLP") == "1":
    print("🧠 SS_USE_MLP=1: 分层伺服 (前段蒸馏 MLP 主执行 + 插入段解析)")
else:
    self.accel.forward = self.accel.analytic_forward      # ← 实例属性覆盖类方法
```

全仓只有这一处读 `SS_USE_MLP`, **GUI 任何档位 (含 L4) 都不设它** ⇒ 构造完成后
`accel.__dict__["forward"]` 指向 `analytic_forward` 的 bound method ⇒
`parallel.py:143 def forward` 的 body **一行都不执行** (断点自然永不进),
`n_mlp / n_guard` 恒 0, 域判定 (D_GUARD / DOMAIN_SIGMA) 根本没被走到。

## 两臂实测数字 (seed 0 / 32 步 / mode=insert / vision=False)

| 观测 | 臂A: GUI 默认 (SS_USE_MLP 不设) | 臂B: SS_USE_MLP=1 |
|---|---|---|
| `accel.loaded` / `_ff is None` | True / False (权重在, 不是加载失败) | True / False |
| 实例 `__dict__` 覆盖 forward | **True** (`acc.forward` → `analytic_forward`) | False (`acc.forward` → `forward` L143) |
| 引擎每帧 `acc.forward(...)` 调用 | 32 | 32 |
| **真身 body 进入次数** | **0** | **32** |
| `n_mlp / n_guard` | 0 / 0 | 32 / 0 |
| 域判定真值 | 未评估 | d_guard 0.131/0.163/0.178 (min/mean/max, 门 0.25, 超门 0/32); 归一化 max\|xn\| 1.583 (门 4.0, 超门 0/32) |

⇒ 这批帧**不是被守卫挡的**: 放它进就 32/32 全走 MLP。挡它的是装配期那行赋值。

## 取证脚本 (可直接复用的打法, 放在仓库 `tools/diag_ff_entry.py`)

不改任何源码, 三步:

1. **构建 sim 之后先答"它现在是谁"**——不要一上来就插断点:
   ```python
   acc, cls = sim.accel, type(sim.accel)
   print("forward" in acc.__dict__,                       # 实例是否覆盖 (True 即真身已死)
         getattr(acc.forward, "__name__", acc.forward),   # 实际落到哪个函数
         cls.forward.__name__, cls.forward.__code__.co_firstlineno)
   ```
2. **两处包装两层计数, 别只包一层**:
   - 包**类**方法 `cls.forward` → 计"真身进入次数"; 实例已覆盖时它恒 0, **这个 0 本身就是证据**。
   - 若实例已覆盖, 再包**实例**属性 `acc.forward = counter(acc.forward)` → 计"引擎每帧调用次数",
     用来证明"调用侧是通的, 断的是函数身份"。
   - 包 `cls.analytic_forward` **对已捕获的 bound method 无效** (赋值时捕获的是原函数对象)
     ⇒ 只包类/实例 forward, 别指望在 analytic 侧计数。
3. **顺手把守卫判据的真值打出来** (d_guard = ‖obs[0:3]−obs[36:39]‖, 归一化 max\|xn\|),
   这样才能一句话回答"是 (a) 距离 还是 (b) 4σ 挡的" —— 本会话证明两个门都没挡。

## 同类"函数身份被换掉"的排查清单 (审计 L1→L2 之间加一步)

先查有没有人**在构造期/装配期重新绑定**你要断点的那个名字, 再谈调用链:

```bash
# 实例属性覆盖 (类方法被 shadow) —— 最常见, 静态 grep 就能抓到
grep -rn '\.\(forward\|step\|decide\|act\) *= *self\.' --include=*.py .
# 别名/替换成"另一个实现"
grep -rn 'self\.[A-Za-z_]*\.\(forward\|step\) *= *self\.' --include=*.py .
# 开关决定是否替换 (本会话: SS_USE_MLP) —— 顺手确认这个开关谁设了
grep -rn 'SS_USE_MLP' .
```
判定规则: **一个环境变量只在被问的那个文件里被读、GUI 侧 grep 不到任何人设置它
⇒ 那个分支在生产口径下恒走 else**。这类"孤儿开关"是假接入的高发形态。

## 三条连带事实 (问"这段代码进没进"时必须一起给, 否则答案会误导)

1. **插入段恒解析**: 同一文件 `2245` 行 `u_ff = (analytic_forward(obs) if st_now == "插入"
   else self.accel.forward(obs))` ⇒ 即使 `SS_USE_MLP=1`, 插入段也不进 MLP (分层伺服设计本意)。
2. **L4 档的执行者根本不是它**: L4 走 `install_direct_act` 包 `sched.decide`, 解析指令被丢弃;
   `u_ff` 只用于取阶段标签 / gripper / `build_skill_ctx`。执行参考是**引擎本帧的 `u`**
   (`act = clip(u[:3]/K_ACT)`), 模型动作与 `u` 比 cos 后融合或否决
   ⇒ 这条链上"前馈 MLP 进不进"都不决定动作, 别把"进了"说成"接管了"。
3. **诊断前向不等于主路径**: `2587` 行每步直接 `acc._ff(obs[:39])` 只为灌"前馈探针"直方图,
   绕过 guard、也不走 `forward` ⇒ 症状是"探针有激活但 `n_mlp` 还是 0", 两者不矛盾,
   不要拿探针非空当"主路径在跑"的证据。

## 汇报模板 (老倪认这种)

> 结论: 不是域判定挡的 (否则 n_guard 会涨), 是**装配期把函数换掉了**。
> 证据 (两臂, 32 步): 臂A 引擎调 32 次 / 真身 0 次 / n_mlp=n_guard=0 / 实例 `__dict__` 覆盖 = True;
> 臂B (SS_USE_MLP=1) 真身 32 次 / n_mlp=32 / 域判定 32/32 全过 (d_guard ≤0.18 < 0.25, max\|xn\| 1.58 < 4.0)。
> 连带: ①插入段恒解析 ②L4 直驱下执行参考是引擎的 u, MLP 进不进不决定动作 ③2587 行诊断前向绕过 guard。
> 要让它真进: 起 GUI 前 `export SS_USE_MLP=1` (或加勾选)。
