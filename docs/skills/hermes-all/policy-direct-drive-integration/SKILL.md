---
name: policy-direct-drive-integration
description: "Use when 策略直接输出指令开机器人 (直驱) 或先判动作头能否用."
version: 1.0.0
author: Hermes Agent
license: MIT
tags: [policy, direct-drive, action-head, offline-replay-gate, finetune, robot]
metadata:
  hermes:
    tags: [policy, direct-drive, action-head, offline-replay-gate, finetune, robot]
    related_skills: [robot-policy-eval-rollout, zmax-policy-training-eval, cross-venv-model-canvas-node]
---

# 策略直驱接入 + 动作头可用性判闸

## When to Use

- 用户要求"**让模型直接输出指令控制机器人 / 跟原来的项目一模一样**"(不经过解析控制器、不加前馈槽位)。
- 要把外部/自训策略 (ACT / INTACT-JEPA / VLA / 世界模型) 的 action chunk 接到机器人的 `env.step`。
- 训练完一个策略要判"**它现在能不能开机器人**", 而不是先烧几小时闭环。
- 微调后闭环成功率为 0, 需要快速区分"接线错"还是"模型没学会"。

## 0. 口径 (先说清, 免得被当成功)

**直驱 = 模型输出 action → 直接 `env.step(action)`**, 中间没有解析控制器 / 前馈槽位 (u_ff) / 流形 / 标定。
唯一允许的换算是**训练归一化的数学逆运算**: `a_raw = z·std + mean` + clip 到机器人动作范围。
- `action_dim = frameskip × 数据集动作维` (实测帧跳 2 × 4 维 = 8 维: 前半 = 第 t 拍, 后半 = 第 t+1 拍)。
- 逆归一化用的 mean/std 必须**从训练数据集同口径算出** (finite 行 + ddof=1), 落成 json 供复用, 不许手写常数。
- 报告里要写清"这是训练归一化的逆变换, 不是新增映射逻辑" — 否则会被当成偷偷标定。

## 1. 落地写法 (引擎侧零行为改变)

1. 引擎加**默认关闭**的直驱钩子:
   ```python
   _dact = getattr(self, "_direct_act", None)
   if _dact is not None:                      # 直驱: 该值就是 env 级动作 (±1), 不再换算
       act = np.clip(np.asarray(_dact, float).ravel()[:4], -1.0, 1.0)
   else:
       act[:3] = np.clip(u_vec[:3] / K_ACT, -1.0, 1.0)   # 原路径一字不改
   ...
   if _dact is not None:  pass                # 夹爪也用模型值, 不做阈值化/重夹
   elif regrip > 0: ...
   else: act[3] = CLOSE if u_vec[3] > 0.5 else OPEN
   ```
2. 包调度器的 `decide()`: **先调原函数只取阶段标签, 丢弃解析指令**, 每 tick 渲染当前帧 → 外部模型 → 写 `_direct_act`。
   这样引擎的观测/阶段/成功判据/manifold 记账全不变 → 解析链 baseline 与直驱可在**同一进程同 seed 同轮**对照。
3. 一次调用 = 一次真推理, 记 `model_calls`; 推理异常要写进结果 (别静默回退成零动作 = 假接入)。
4. 输出里带动作统计 (均值/std/|max|) 与阶段直方图 — 判断"机器人在动没动 / 卡在哪一段"全靠它。

## 2. 上闭环之前: 离线回放闸 (最快判决器, 秒级)

在**模型自己的训练数据**上跑: 真帧 → 模型 → 预测动作 vs **教师动作**(数据集 action 列),
并与**常数基线 (永远输出教师均值)** 比 MAE。

| 判据 | 通过 | 失败形态 (实测) |
|---|---|---|
| xyz MAE vs 常数基线 | 模型显著更低 | 模型 0.092 vs 常数 0.086 → **不如常数** |
| 逐轴相关 | \|ρ\| 有信号 | \|ρ\| ≤ 0.27 |
| 预测 std / 教师 std | 同量级 | 预测小 **10~25 倍** → 动作头塌缩到均值 |

**结论用法**: 三项任一失败 ⇒ 动作头没学会本任务动作 ⇒ **别再上闭环** (白烧算力)。
闭环实测对照: 直驱 0/4 vs 同轮解析链 1/4; 失败时动作 std 比教师小 20 倍 → 一直卡在"接近/对位"。
排除"读错槽位": chunk 的 slot0 / slot1 各评一遍 (两槽都塌缩 ⇒ 不是读法问题)。

## 3. 微调为什么塌缩 (按这个顺序查)

1. **动作头 loss 权重被世界模型压死** — 实测 `local_weight=0.1 + goal_weight=0.05` vs `forward_weight=1.0`
   ⇒ 动作头只分到 ~15% 梯度; 世界模型 loss 一路下降而动作输出恒为均值
   (负的 action NLL 也会"变好": 学成均值 + 大方差)。
2. **epoch / 数据量太小** — 实测 8 epoch × 36 回合 (1.8 万帧) 不足以把预训练策略的动作空间搬到新域。
3. **只改一样通常不够** → 数据 ×8 + 权重 1.0/1.0 + 3~6 epoch 一起上, 再过同一道闸。

## 4. 不要拿"解析控制器 u_ff"当标定目标

解析 u_ff 是**分阶段状态机语义**, 线性/岭回归拟合它不可达 (实测全局样本外 R² 0.043;
分阶段样本内 0.177 但样本外 −0.63 = 过拟合假象)。模型输出通常承载**它自己训练目标**的语义
(实测 chunk 各维与目标位移模长 |Δ| 的 |ρ| 0.44~0.62 = "离目标多远"而非速度指令)。
⇒ 这类信号应接**流形/目标点通道**; 要接速度槽位就得先靠域内训练把动作空间搬过来。

## 5. 算力预算与无人值守

- **先算 ETA 再开跑**: `steps/epoch ≈ 样本数 / batch`, `ETA = steps/epoch ÷ 实测 it/s × epochs`。
  实测教训: 8.1× 数据 + 计划 30 epoch = **≈50 小时** → 砍到 3 epoch。
- 8GB 卡: batch 24 OOM → **batch16 + `num_workers=12`** (实测 2.1 it/s, 比 4 workers 快 ~40%; 单进程 5.8GB 稳定)。
- 每 epoch 都落 ckpt → 挂**逐 ckpt 判闸守护**: 每落一个 `.pt` 自动跑离线回放闸 (CPU 推理, 不抢训练显存),
  任何 epoch 过闸就**提前上闭环**, 不等满计划轮数。
- 数据要放大时: 分块采集 + 流式合并 (见 references), 别一次性 concat。

## 6. Pitfalls

| 坑 | 症状 | 修法 |
|---|---|---|
| 直接 concat 全部采集帧 | 15 万帧 ≈ 22GB → 进程被 OOM 杀, **一个文件都没落盘** | 按帧数阈值分块落 `*_partNN.npz`, 再流式合并 h5 |
| 官方数据集解析器 | `Cannot resolve '<name>': not a local path or HF repo id` | 名字**要带扩展名** (`.h5`); 验证失败不许 `return` 跳过后续清理 |
| 中间产物不删 | 合并完仍留 7GB part npz | 删除放在 `try/except` 之后 / 无论验证成败都执行 |
| 单轮单臂对比 | 同参数重跑也能 1/N → 2/N, 误判"有提升" | 同 seed 内 base↔候选**背靠背配对** ≥16 对, 净胜 <2 判"在噪声内"; 另跑默认值做噪声对照 |
| 只看成功率不看真推理次数 | `calls=0` 却与 baseline 同分 → 被当成"接管不回退" | 报告必须同时给模型真推理次数与动作统计 |
| 观测来源不明 | 拿合成/黑帧喂模型 = 蒙眼 = 假结论 | 逐帧标 `obs_source`, 抽样 `frame_std > 5` 才算真图 |

> 📄 完整命令/数字/落盘路径 (数据分块采集 → 流式合并 → 官方加载器验证 → 逐 ckpt 判闸脚本):
> `references/direct-drive-and-action-gates.md`
