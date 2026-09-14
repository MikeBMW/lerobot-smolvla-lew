# 引擎内"真接上"的取证: 假跑签名 + 定量零回退 (2026-09-14 夜 直连线专项)

这份是 L2/L3/L4 **档位级**审计的补强: 除了"节点在位/有连线/capability 清单"这些结构判据,
还要能回答"这条档位**每一帧真的跑到推理了吗**"和"新通道有没有悄悄改变执行"。

## 1. 假跑签名: 计数全绿 ≠ 真推理跑到了

实测 (引擎 `SS_L4_INTACT=1` 的 L4 直驱档, v6 权重):

```
calls = 220 / 220        ← 每帧都"进了"这条路径, 看起来全绿
refused = 0, blend = 0
u_ff_src = "analytic(L4 推理异常)"
err      = RuntimeError: INTACT 推理失败/未训练, 拒绝返回零动作:
           ValueError: checkpoint was trained with a skill channel (skill_dim>0)
           but info['skill_ctx'] was not provided — refusing to silently degrade
```

真因: 该路径调 `node.step(fr, obs_source=...)` 时**从不构造 skill_ctx**, 而 skill 版权重在
`jepa.get_action` 里有硬闸 → 220/220 帧全被拒 ⇒ **该档在引擎里从未跑到真推理**, 只是每帧计数 +1。

审计动作 (别只看 `calls`/`ran`):
- 读计数字典里的 `err` / `u_ff_src` / `refused` / `blend` / `w_zero`; `u_ff_src` 里出现
  `analytic(...)` / `拒绝` / `异常` = 该帧没接管。
- 修法 = 把上游该给的东西**在唯一入口补齐**: 这里改成与采集/直驱共用
  `lerobot.policies.intact.skill_ctx.build_skill_ctx` (L2 势场取不到 → 退化为相位+夹爪并**如实计数**, 不装)。
- 泛化: 任何"带硬闸的上游 + 中间层漏传字段"的组合都会长成这样 —— 计数在涨、日志有 err、执行毫无变化。

## 2. 零回退必须定量, 不能用 hash 相等

闭环引擎自身 run-to-run **就有 FP 非确定性** (L4 档 INTACT CPU 前向 + 闭环放大):

| 对比 | 前 30 帧 max\|Δu_ff\| | 全局 max\|Δu_ff\| | 读法 |
|---|---|---|---|
| A1 vs A2 (同配置跑两遍, 新通道全关) | 2.99e-4 | 3.1e-3 | **引擎噪声基线** |
| A(关) vs B(开但不注入, w=0) | 9.2e-5 | 6.3e-2 | < 噪声 ⇒ 等价 (前 30 帧判) |
| B(w=0) vs C(w=1, 注入) | 7.09e-2 | 2.2e-1 | ≈237× 噪声 ⇒ 真在改执行 |

⇒ **判据**: 先量噪声基线 (同配置跑两遍), 再要求"关 vs 开不注入"的差 **< 噪声**;
注入臂必须显著大于噪声 (给倍数)。只报 hash 相等/不等在闭环里是错的判据 (它会永远判失败)。
单元级 (纯函数/模型前向) 仍可用严格逐位 hash: 预测器 `m=None` / 零初始化门控 → 三方 hash 相同。

## 3. 三档取证模板 (每次接新通道都跑)

`关` / `开但不注入(w=0)` / `开且注入(w=1)` 各一段真跑, 报:
`frames / ran / applied / w_zero / refused / ready / w_last / clip_max` +
每帧 `u_int` 范数均值 + 流形式读数末帧 + 与基准的 Δu_ff。脚本示例: `tools/smoke_intent_line_engine.py`
(输出 `/tmp/intent_line_smoke.json`)。

实测三档 (220 步):
- A 关: frames=0 ran=0 applied=0
- B 开 w=0: frames=28 **ran=27**(真推理) applied=0 refused=1 (`z7 历史为空`, 首帧, 诚实计数)
- C 开 w=1: ran=27 **applied=212**(逐帧融合) w_last=0.3 clip_max=0 (u_int 从未越界)

## 4. 落地纪律 (推理端不许"有文件就 ready")

- ckpt `meta` 必须带质量指标 (`loso_r2_mean` 等) 与架构/口径 (`input_kind`/`hidden`/`layers`);
  推理端**先读 meta 再建模型** —— 实测顺序错 → 首帧 `size mismatch for predictor.mlp.*` + refused=1。
- ready 判据: `meta.loso_r2_mean >= 0.30` 才允许注入执行口; 否则"线路照跑但 w=0"并在面板写明原因;
  未过闸的 ckpt 挪 `rejected/` 留证。**不许把未训练模型注入执行参考**。
- 训练用标准化 ⇒ `scaler` 存进 ckpt, 推理端同源应用 + 反标准化 (流形/动作都要回去); 无 scaler ⇒ 直通。
- 上层只写"参考", 执行出口不动: 融合后仍必须经 `sched.decide → safety.saturate → env.step`
  (审计时确认该出口全文件只出现一次, 别被新通道旁路)。
