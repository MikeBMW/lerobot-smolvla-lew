---
name: layered-capability-stack
description: "Use when 打通分层能力栈或给已有链路加可选通道 — 上层只给意图/条件, 执行由最下层收口 + 零回退取证."
version: 1.0.0
author: Hermes Agent
license: MIT
tags: [architecture, layered-control, intent-conditioning, zero-regression, capability-stack, wiring]
metadata:
  hermes:
    tags: [architecture, layered-control, intent-conditioning, zero-regression, capability-stack, wiring]
    related_skills: [integration-level-audit, zmax-state-space-architecture, robot-policy-eval-pitfalls]
trigger: "Use when the user asks to 打通/串起 分层架构 (L2 执行 → L3 条件 → L4 意图/世界模型), to connect one model's output into another module's input, or to add an OPTIONAL conditioning channel to a live chain that must change nothing when disabled. Also use before claiming '能力叠加/打通了'."
---

# 分层能力栈接线 (上层只给意图/条件, 执行由最下层收口)

## 为什么需要

分层架构最常见的事故不是"某层不够强", 而是**层之间是替换关系而不是叠加关系**:
每档各管一段、装配时把别的档关掉 ⇒ 上层拿不到下层的能力, 只能靠自己那点权重硬扛
(实测: L4 直驱过冲 152~331mm, 而解析链只有 10.9~62.6mm)。

**判据 (先做这一步)**: `grep -nE "SS_L3|SS_L4|if .*enable.*layer" tools/gui/*.py` 找有没有
"开 A 就 pop 掉 B" 的开关。有 = **档位互斥**, 能力不可能叠加; 必须先改成"参考+收口"结构再谈提升。

## 一、分层契约 (单向依赖: 上层依赖下层的准确执行)

| 层 | 只准产出 | 禁止 |
|---|---|---|
| L4 意图层 (世界模型/意图解码器) | 意图 `m_t` (目标位移/姿态/交权) | 写执行量、直接产动作 |
| L3 条件层 (VLM/DiT/流程) | 条件 `c_t` (相位/子目标/条件向量) | 写执行量 |
| L2 执行层 (解析伺服/技能/状态机) | 执行量 `u ∈ U_L2` —— **唯一出口** | —— (有对上层参考的最终否决权) |

把"层语义"做进**类型**里 (如 `LayerOut(layer="L4", kind="action")` 直接抛异常), 越权就是运行期错误,
而不是靠 review 记得。

## 二、四条硬约束 (缺一条就是假接线)

1. **单出口 I1**: 只有最下层写执行量 (引擎里 = `sched.decide()` + `safety.saturate()`); 上层只写参考槽 (`u_ff`)。
   接线后 `grep -c "u, stage = self.sched.decide("` 必须仍是 **1** —— 出口被复制/绕过即接错。
2. **收缩投影 I2**: `u = proj_{U_L2}((1−w)·u_L2 + w·u_up)`; 越界必夹紧并记账 (`clip_max`), 不许直接采信上层。
   可行域逐层收窄: `U_L2 ⊇ U_L3 ⊇ U_L4`。
3. **语义护栏 I3**: 见上 (类型强制)。
4. **稳定性判据 I4**: 选一个李雅普诺夫候选, 例如 `V = ‖peg/hand − hole‖² + w·θ_err²`,
   要求沿阶段**逐帧单调不增**; 改动前后**同 seed 两臂对照**, V 不升才算"导引有效"。

## 三·补、给上层换"喂什么进去"而不重训 (实测有效的一招)

需求"把 A 模型预测出的潜空间喂给 B 预测器"时, B 既然已经有训练好的权重, 维度又对不上,
**不要重训 B**, 而是标定一个**丛映射** `ẑ = A_map · z_pred + b` (ridge + LOO R² 闸 ≥0.3),
让 B 的输入维与口径保持不变, 只换数据来源。实测: z_pred(192) → ẑ7(7), R²_loso=0.607,
B 权重一字未改而"预测潜空间"真的进了执行链 (证据: 预测器输入来源字段 = `fiber(A·z_pred+b)`)。

## 四、加一条可选条件通道 = 数学上真零回退 (最易踩的坑)

- ❌ **concat 进既有 MLP 输入** (`torch.cat([z, a, m])`): 第一层对应输入列的权重是随机初始化的 →
  即使把 m 置零、门控置零, 输出也**不逐位相同**。"关掉就零变化"的要求会被当场戳穿。
- ✅ **独立 additive 分支 + 末层零初始化**:

  ```python
  z_pred = self.mlp(torch.cat([z, a], dim=-1))
  if m is not None and self.intent_proj is not None:      # m_dim>0 才建分支
      z_pred = z_pred + self.gate * self.intent_proj(m)   # proj 末层 weight/bias 全零
  ```
  `nn.init.zeros_(self.intent_proj[-1].weight); nn.init.zeros_(self.intent_proj[-1].bias)`
  → `m=None` 或未训练时增益恒 0, 输出**逐位等于旧实现**; 训练后打开才有影响。
- **取证 (必须做)**: 同一套主干权重下三态输出 hash 相同 —— 旧实现 / `m=None` / 给了 m 但零初始化:
  `hashlib.sha256(np.ascontiguousarray(x, dtype=np.float64).tobytes()).hexdigest()[:16]`
- **"通道是活的"取证**: 手工给末层加小随机权重 → 增益 >0 **且下游读数变化** (证明不是摆设)。
- **未训练时的纪律**: 线路**照跑出证据** (每帧真前向 + 来源标注 + 面板写"在跑 · 未训练 → 不注入"),
  注入权重 = 0; 绝不拿未训练的输出污染执行口, 也不许因为"没训练"就把线路悄悄关掉 (那是假接入的另一种形态)。

## 四、六查探针 (照抄这个结构, 每查都要有机器可判的判据)

| 查 | 判据 |
|---|---|
| A 零回退 | 三态输出 hash 相同; 未训练增益 = 0.0; 训练后增益 >0 且下游变化 |
| B 收缩性 | 5000 组越界参考 → 0 违规; `w=0` 时逐位等于下层原值; 层语义护栏真抛异常 |
| C 接口真跑 | 意图 → 预测器 → (流形式/中间读量) → 动作头 → u 非零且带来源 (随机权重只证"通") |
| D 判据自检 | 单调序列判通过 / **注入一次回升**必须被抓 (证明检查器不是恒真) |
| E 上层字段 | 新字段有值带来源; 被排除的阶段**诚实拒绝**; 老字段一个未变 |
| F 引擎接线静态 | 方法在位 / 环境守卫在位 / 融合调用在收口之前 / 唯一出口计数 = 1 |

⚠️ **静态自检 ≠ 运行时联调**。汇报必须分开写"接线已证 / 运行时未联调 (需开控制台)"。
点击自检、双击节点、只测形状与有限性, 都不算接上。

## 五、汇报模板 (三段分开, 不许一句"打通了"盖过)

> 接线段: 逐条给 hash / 计数 / 夹紧量 (可复现命令)。
> 质量段: 模型是否**已训练**; 未训练就写"不注入, 指标待训后出 (R²/LOSO 闸值 ≥0.3 之类)"。
> 闭环段: 未跑就写"未跑"。

## 六、落地顺序 (最便宜的线先上)

0. 诊断档位互斥 → 定契约与不变量
1. 下层消费者加**可选条件口** (additive + 零初始化)
2. 上层解码器输出该条件 (老字段不动, 新字段带来源与门控)
3. 仲裁模块 (契约类型 / 收缩投影 / 记账 / V 检查) —— 纯 numpy、可单测, 不依赖引擎
4. 引擎接线 (环境变量守卫; 不设 = 逐位零变化)
5. 六查探针 + 报告落盘
6. 训练该通道 → 出质量指标 → **同口径两臂 A/B** (开/关) 才允许进默认档
7. 再往上叠下一个专家 (接口最齐的那条先接, 如已有 `φ_ref` 入口的姿态/偏航专家)

## 参考

- `references/zmax-direct-line-2026-09-14.md` — Z-MAX L4 意图 → 流形专家预测器 → 动作头 直连线的落地实录:
  改动的四个文件、六查探针实测数字、不变量表、以及"档位互斥"诊断命令。
- `references/fiber-bundle-l4-layer-2026-09-15.md` — **纤维丛联络层** (动作丛→接触丛→DiT) 落地实录:
  丛结构/联络数学、丛映射换源不重训、四个真坑 (桥白名单吃键 / 采数死锁 / 零回退仪器前提 /
  行号写死误导) 与配套工具 (probe / fit_fiber_map / audit_l4_edges / verify_zero_regression)。
- 接入分级取证 (节点级 vs 档位级、孤岛识别): `integration-level-audit` (相邻技能, 有部分重叠)。
