# Z-MAX 能力栈: L2/L3/L4 分层打通 (2026-09-14, 老倪原则)

> 原则 (老倪原话): **上层只提供意图/条件, 执行永远由 L2 解析链收口; 每层只能收窄可行域、
> 不能扩大 (形式上 U_L2 ⊇ U_L3 ⊇ U_L4), 稳定性由 L2 的李雅普诺夫势兜底
> (V = 到孔口距离² + 姿态偏差²), 逐层单调下降。**
> 直连线: 意图 → 流形专家预测器 → 动作头 → 融合; L4 不再直接吐动作。

## 1. 现在的病: 档位互斥, 不是能力叠加

| 事实 (代码) | 后果 |
|---|---|
| `SS_L3=1` 走 SmolVLA-Lew 出 xyz; `SS_L4_INTACT=1` 走 INTACT 直驱; `SS_INTACT=1` 走标定映射 | 每档各管一段, 上层不开下层 |
| L4 档直驱 = `u_ff = act×K_ACT` 直接进 `u_ff` 槽位 | L4 越权直接给"动作", 不是"意图" ⇒ 一旦模型不会, 直接过冲 (实测 152~331mm) |
| L4 档没有把意图交给流形专家预测器 | 世界模型/预测器/流形读数**不在链上**, 断点不进 |
| `intact_l4_current/weights.pt` 曾指向 v6r2 ep1 (死锁轮) | 运行档挂废权重 |

⇒ L2→L3→L4 能力**不可能**"不断提升": 它们是三套并联的替代品, 不是一条能继承能力的栈。

## 2. 分层契约 (单向依赖: 上层依赖下层的准确执行)

```
L4 意图层 (IntentLayer)     输入: z_t, z_goal, δ=z_goal−z_t, stage, skill_ctx
                            输出: m_t  (意图向量; 目标位移/姿态/交权)   ← 只产"意图"
                            禁止: 写 env 动作, 写 u

L3 条件层 (ConditionLayer)  输入: 任务语言 + 观测 + m_t
                            输出: c_t  (流程条件: 相位/子目标/条件向量)  ← 只产"条件"
                            禁止: 写 env 动作

L2 执行层 (ExecutionLayer)  输入: c_t + m_t + 引擎状态/接触
                            输出: u ∈ U_L2 (解析伺服 + 原子技能 SK01-08) ← **唯一执行出口**
                            权力: 对任何上层参考有**最终否决权** (夹紧/拒绝/限幅)
```

四槽语法同构 (INTACT `feature_layout=four_slot`: `[z, m_t, z·m_t, A(a_{t−1})]`) —— `m_t` 就是
流形专家预测器要接的那一路, 两边同一个变量, 不发明新语义。

## 3. 不变量 (要能被机器检查)

| 代号 | 不变量 | 检查方式 |
|---|---|---|
| I1 单出口 | 只有 L2 能写 `env.step` 的动作 | 代码: `sched.decide()`+`safety.saturate()` 是 u 的唯一出口; 上层只写 `u_ff` |
| I2 收缩 | 上层参考必须落在下层可行域: `u = proj_{U_L2}((1−w)·u_L2 + w·u_{L4})` | 探针: 越界参考 100% 被夹紧, 记录夹紧量 |
| I3 零回退 | 新通道关闭 ⇒ 逐位等于现状 | 探针: 开关前后数组 hash 逐位相同 |
| I4 证据 | 每帧记 `m_t` / `c_t` / `u` 的来源与门控, 缺条件时**如实拒绝并标注** (不静默) | 面板/台账字段 `*_src` / `*_weight` / `ready` |
| I5 稳定性 | `V = ‖hand−hole‖² + w·θ_err²` 沿阶段单调不增; 开 L4 后的 V 不高于纯 L2 | `capability_stack.lyapunov_ok()` + 同 seed 两臂对照 |

## 4. 直连线 (本次打通的那条)

```
node.step (引擎帧) ──> INTACT 策略 ──> out.latent {z_t, z_goal, δ}
   │
   └─> IntactIntentDecoder.decode()
         ├─ u_ff   (4)   量纲逆运算 act×K_ACT        ← 现状: 直接当"动作"用 (越权)
         ├─ l3_cond (D)  需标定 (无 map → 诚实拒绝)
         ├─ l4_cond (192) δ 单位向量 → DiT 额外条件 token
         └─ m_int   (192) δ  →【新】流形专家预测器条件        ← 意图, 不是动作
                    │
                    ▼
   WorldModelPredictor(m_dim=192) :  z' = mlp([z_t, a]) + gate·proj(m_int)
                    │                     (proj 末层零初始化 → gate=0 时逐位等同旧行为)
                    ▼
   ManifoldReadout → m̂ (6): [progress, risk, V, eta, rem, d_perp]   ← 引擎真值列同名, 可监督
                    ▼
   StateSpaceActionHead(m̂) → 4 维动作块 → u_int (引擎 u 空间)
                    ▼
   融合 (同一 u_ff 槽位):  u_ff ← (1−w)·u_L2 + w·u_int      w = w_decoder × β_line × ready
                    ▼
   L2 收口:  sched.decide(u_ff, u_fb, contact_p, r) → u → safety.saturate(u, SS_LIMIT) → env.step
```

- `ready` = 预测器**已训练**才为 1 (查 ckpt + R² 闸); 未训练 → 线路照跑并出证据, 但 `w=0`
  (面板显示"直连线路: 在跑 · 未训练 → 不注入"), 绝不拿噪声污染执行口。
- 开关 `SS_L4_INTENT_LINE`: 不设 = **逐位零变化** (I3)。`SS_L4_INTENT_LINE_W` 只用于探针显式加权。

## 5. 分工: 下层支撑上层, 上层依赖下层

| 层 | 支撑什么 | 依赖什么 | 量化指标 |
|---|---|---|---|
| L2 | 稳定执行 (任何输入下都在可行域内动) | 引擎状态机/接触/安全三层 | 插入深度误差 mm、done 率、V 单调 |
| L3 | 扩展流程 (换任务/换相位/换子目标) | L2 能准确执行 c_t | 任务族覆盖率、相位切换成功率 |
| L4 | 自主恢复 (扰动后重新给可行意图) | L2 稳定 + L3 条件 + 预测器可预测 | 三档扰动成功率、过冲 mm、V 不升 |

## 6. 验证口径 (老倪交付门槛: 有提升非仅不回退, 每条杆单独同口径对照)

1. **零回退**: 开关关闭 → 逐位一致 (hash)。
2. **收缩性**: 随机 5k 组越界参考 → 100% 落回 `U_L2`, 记录最大夹紧量。
3. **接口真跑**: 意图 → 预测器 → 流形式 → 动作头 → `u_int` 非零且带来源 (随机权重下只证"通")。
4. **质量 (需训练后)**: 流形式 readout R²/LOSO ≥0.3 (与 decoder 标定同一闸值) + 离线 v4 判闸逐槽
   MAE/pearson/std 比 + 闭环 3 seed × 两臂 × ≥3 重复的 done 率/插入 mm/过冲 mm。
5. **稳定性**: `V` 逐阶段单调不增; 开/关 L4 两臂同 seed 对照, V 不升才算"牵引导航有效"。

## 7. 落地顺序 (最便宜的直连线先上)

1. **预测器加意图口** (本文件 + `manifold/predictor_layer.py`, 零初始化门控)
2. **解码器出 `m_int`** (`policies/intact/decoder.py`, 老字段不动)
3. **能力栈仲裁模块** (`manifold/capability_stack.py`: 契约/收缩/否决/V 检查)
4. **引擎接线** (`SS_L4_INTENT_LINE`, L2 收口不变)
5. **探针取证** (`tools/probe_capability_stack.py`)
6. 之后: yaw 专家直连 (`ManifoldYawActuator.φ_ref` 已有意图入口, AOI 红光向下硬需求) → 位置/轨迹专家
   → `m_stop` 交权专家 (自主恢复判定, 现在还是硬编码排除"插入")
