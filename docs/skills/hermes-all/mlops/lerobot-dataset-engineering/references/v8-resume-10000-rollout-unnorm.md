# v8 续训到 10000 步 + rollout 反归一化 (2026-09-09 实测补充)

## 续训 3000→10000 步
- resume 三坑见 `lerobot-train-resume-notes.md` (config_path 指 train_config.json / resume 改 true /
  `--config_path=` 等号)。resume 成功后进度从剩余步数起 (如 7000)。
- 10000 步完成后: `action_loss 0.92→0.011`、loss 0.507→0.229 — 模型在训练分布上动作预测极准。
  checkpoint `last -> 010000`, training_step.json step=10000 确认。

## ⚠️ 关键: action_loss 收敛 ≠ rollout 能跑 — 先查反归一化 (比"欠训练"更常见)
**症状**: 收敛模型 (action_loss 0.011) rollout 每步输出动作但 peg 距 hole 恒定不动、
gripper 恒 0 → 之前 reference 判断"裸 rollout 不收敛是常态" — **部分结论**。真正的第一嫌疑是:
**select_action 输出在归一化空间 (MIN_MAX/MEAN_STD), 直接 np.clip 送 env.step = 动作全错**。

**修复**: 加载 postprocessor 并反归一化:
```python
from lerobot.policies import make_pre_post_processors
pre, post = make_pre_post_processors(policy_cfg=policy.config, pretrained_path=ckpt)
...
act = policy.select_action(batch)
if post is not None:
    act = post(act)      # MIN_MAX 反归一化 → 真实动作空间
act = act.cpu().numpy().flatten() if hasattr(act, "cpu") else np.asarray(act).flatten()
```
- 修复前: act 幅度 ~0.3-1.0 (归一化空间饱和/漂移) → 修复后: ±0.1 伺服级小位移 (数据 action 真实范围
  ±0.34 + gripper 0-1) — 幅度突降本身就是"反归一化生效"标志。
- 与训练数据比对: `data action: min ~[-0.34], max ~[0.31], gripper 30% 时间=1`。
  若 rollout gripper 恒 0 而数据 30% 闭合 → 动作仍没进对空间或没学到抓取时机。

## 反归一化后仍不收敛的真实剩余原因
10000 步 + 反归一化正确后 rollout 距孔仍 ~0.27-0.30 不动 (光模块从未被拿起):
1. **covariate shift**: 训练数据是 8 阶段专家轨迹 (状态机切阶段), 裸 rollout 无状态机引导 →
   每步观测都在训练分布外, 模型输出无意义小扰动。
2. **epoch 数不足**: 129883 帧 / batch1 / 10000 步 ≈ 每帧只见过 0.08 次。
3. 结论 (汇报口径): "端到端动作预测准 (action_loss 0.011) 但闭环插拔未成" — 下一步是
   阶段状态机引导 rollout (VLM 出动作 + 引擎状态机管阶段切换) 或继续训练 2-3 万步。
   诚实准则不变: 不要拿"模型驱动 metaworld 跑了 N 步"冒充"学会了插拔"。

## 训练中磁盘红线交互
disk_redline.sh (2h cron) 会删中间 ckpt 只留 last — 训练中删已完成 ckpt 不影响当前 run
(resume 用 last/), 但 resume 指向的 ckpt 若被删需退到 last/。大训练前确认红线脚本没刚跑过。
