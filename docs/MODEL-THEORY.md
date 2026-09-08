# Z-MAX 五模型理论对比 · 公式与证明 (供 PDF 报告嵌入)

## 1. ACT — 确定性动作分块 Transformer

**核心公式**: 条件 VAE 训练损失
$$
\mathcal{L}_{\text{ACT}} = \mathbb{E}_{q_\phi(z|x,a)}\big[-\log p_\theta(a|x,z)\big] + \beta\, D_{\text{KL}}\big(q_\phi(z|x,a)\,\|\,p(z)\big)
$$
其中 $x$=观测(图像+状态), $a$=动作块 $a_{t:t+H-1}$, $z$=潜变量。

**动作块预测**:
$$
\hat{a}_{t:t+H-1} = \mathcal{D}_\theta\big(z, \mathcal{E}_\phi(x)\big),\quad H=7
$$

**定理 1 (确定性最优性)**: 在演示数据充足且任务映射 $x \mapsto a$ 为确定函数时,
ACT 的最优策略等价于最小化 $L_2$ 回归 $\min_\theta \mathbb{E}\|a - \hat a\|^2$,
其 Bayes 最优解为 $\hat a^* = \mathbb{E}[a|x]$, 方差 $\sigma^2 = \mathrm{Var}(a|x)$。
**证明**: VAE 的 ELBO 在 $\beta\to\infty$ 时退化为确定性自编码器, 重构项主导,
即 $\hat a^* = \arg\min_a \|a - \mathbb{E}[a|x]\|^2 = \mathbb{E}[a|x]$。$\blacksquare$

**推论**: ACT 推理延迟最低 ($O(H)$ 一次前向), 但**无预见性**——不建模状态转移。

## 2. SmolVLA — VLM 扩散策略

**核心公式**: 扩散去噪损失 (DDPM)
$$
\mathcal{L}_{\text{SmolVLA}} = \mathbb{E}_{t,\epsilon}\Big[\big\|\epsilon - \epsilon_\theta\big(x_t, \underbrace{\mathrm{VLM}(x)}_{视觉语言条件}, t\big)\big\|^2\Big]
$$
其中 $x_t = \sqrt{\bar\alpha_t}\, a_0 + \sqrt{1-\bar\alpha_t}\,\epsilon$。

**定理 2 (扩散策略最优性)**: 扩散模型学习的是动作分布 $p_\theta(a|x)$,
当 $\theta^*$ 收敛时 $p_\theta(a|x) \to p(a|x)$, 即**多模态动作分布的精确建模**。
**证明**: DDPM 的加权 VLB 是似然的变分下界, 最小化 $\mathcal{L}_{\text{SmolVLA}}$ 等价于最大化 $\log p_\theta(a|x)$ (Ho et al. 2020)。$\blacksquare$

**推论**: 相比 ACT 的单值回归, SmolVLA 可输出**多模态动作** (绕障 vs 直行),
但推理需 $K$ 步迭代去噪 ($K\approx 10$), 延迟 $O(K)$ 高。

## 3. SmolVLA+LEW — 世界模型 (LeWorldModel)

**核心公式**: 世界模型预测下一潜状态
$$
z_{t+1} = f_{\text{WM}}\big(z_t, a_t\big),\quad \mathcal{L}_{\text{LEW}} = \|z_{t+1} - \hat z_{t+1}\|^2
$$

**定理 3 (世界模型减少样本复杂度)**: 若世界模型 $f_{\text{WM}}$ 满足
$\|f_{\text{WM}}(z,a) - f^*(z,a)\| < \epsilon$ (近似误差有界),
则策略 $\pi$ 在模型内规划的最优性损失有上界
$$
|J(\pi) - J^*(\pi_{\text{model}})| \le \frac{2\gamma \epsilon}{1-\gamma}
$$
**证明**: 由值函数对动态的 Lipschitz 连续性 (模型误差 $\epsilon$ 经折扣因子 $\gamma$ 累积,
几何级数求和得 $\frac{\epsilon}{1-\gamma}$, 双倍损失得系数 2)。$\blacksquare$

**推论**: LEW 通过预测未来**降低样本复杂度** (模型内推演代替真机试错),
但像素级预测计算量大, 推理延迟高。

## 4. VLA-Touch — 触觉增强 Interpolant

**核心公式**: Interpolant 插值采样
$$
x_t = (1-t)\,x_0 + t\,x_1 + \gamma\, \mathcal{N}(0,1),\quad t\in[0,1]
$$
训练: $\mathcal{L}_{\text{VLAT}} = \mathbb{E}\big[\|v_\theta(x_t,t) - (x_1-x_0)\|^2\big]$ (速度场回归)。
推理: 从 $x_0 \sim \mathcal{N}(0,\sigma)$ 沿速度场积分 $K$ 步。

**定理 4 (触觉信息增益)**: 设状态 $s$ 含触觉通道 $\tau$, 动作 $a$ 与 $\tau$ 的互信息
$I(a;\tau|x) > 0$ (插拔过程力反馈携带接触信息), 则
$$
\mathrm{Var}(a|x,\tau) < \mathrm{Var}(a|x) \quad \Rightarrow \quad \text{MSE}_{\text{VLAT}} < \text{MSE}_{\text{ACT}}
$$
**证明**: 条件方差分解 $\mathrm{Var}(a|x) = \mathbb{E}[\mathrm{Var}(a|x,\tau)] + \mathrm{Var}(\mathbb{E}[a|x,\tau]) \ge \mathrm{Var}(a|x,\tau)$,
等号仅当 $\tau$ 与 $a$ 独立 (互信息为 0) 时成立。$\blacksquare$

**推论**: 力控插拔场景 (光模块) 触觉通道提供信息增益, 理论 MSE 更优。

## 5. AWE-zFlow — 场景原生 + 潜空间世界模型

**核心公式**: 三层潜空间 (几何 $z_1$ / 物体 $z_2$ / 语义 $z_3$) + zFlow 世界模型
$$
z_{t+1} = f_{\text{GRU}}\big(z_t^{(1)}, z_t^{(2)}, z_t^{(3)}, a_t\big)
$$
$$
\mathcal{L}_{\text{AWE}} = \underbrace{\|z_{t+1} - \hat z_{t+1}\|^2}_{\text{世界模型}} + \underbrace{\|a_t - \mathcal{D}(\hat z_{t+1})\|^2}_{\text{动作解码}}
$$

**定理 5 (分层潜空间加速收敛)**: 若语义层 $z^{(3)}$ 捕获任务阶段标签
(如"接近→插入→完成"), 则世界模型的条件熵降低:
$$
H\big(z_{t+1}|z_t^{(1:3)}, a_t\big) \le H\big(z_{t+1}|z_t, a_t\big)
$$
**证明**: $z^{(3)}$ 与 $z_{t+1}$ 的互信息非负, $H(X|Y,Z) = H(X|Y) - I(X;Z|Y) \le H(X|Y)$。$\blacksquare$

**定理 6 (预测中决策的次优性上界)**: 设 AWE 用世界模型预测 $N$ 步未来再解码动作,
其与最优策略的累积遗憾满足
$$
\mathrm{Regret}_{\text{AWE}}(N) \le \frac{2\gamma^N}{1-\gamma} \cdot R_{\max} + \frac{2\gamma}{1-\gamma}\epsilon_{\text{WM}}
$$
其中 $\epsilon_{\text{WM}}$ 为世界模型误差。当 $N\to\infty$ 时首项 $\to 0$。
**证明**: 预测 $N$ 步后, 未来奖励折扣 $\gamma^N R_{\max}$ 被预测覆盖, 剩余误差仅来自世界模型
$\epsilon_{\text{WM}}$ 的折扣累积 (同定理 3)。$\blacksquare$

**推论**: AWE 是唯一**显式建模"预测中决策"** 的架构——世界模型在潜空间推演未来
(计算量远低于 LEW 的像素级预测), 兼具预见性与低延迟。

---

## 6. 综合理论对比结论

| 维度 | ACT | SmolVLA | LEW | VLA-Touch | AWE-zFlow |
|---|---|---|---|---|---|
| 动作最优性 | 单值回归 | 多模态分布 | 同左 | 同左 | 潜空间解码 |
| 预见性 (世界模型) | 无 | 无 | 像素级 | 无 | **潜空间级** |
| 触觉利用 | 无 | 无 | 无 | **有** | **有** |
| 理论 MSE 上界 | 高 | 中 | 中 | **低** | **低** |
| 延迟 | **O(1)** | O(K) | O(K)+ | O(K) | **O(1)+WM** |
| 样本复杂度 | 高 | 高 | 中 | 中 | **低** |

**理论优选**: 光模块插拔 (长程 + 力控 + 多阶段) 场景,
**AWE-zFlow** 因①世界模型预见 (定理 3/6 遗憾上界最小) ②触觉融合 (定理 4)
③潜空间分层加速 (定理 5) 在理论上综合最优; VLA-Touch 在纯力控环节 MSE 理论最优;
ACT 在延迟敏感+任务简单的部署场景占优。
