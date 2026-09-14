# 外部论文权重的原生评测 vs 域内直驱 (2026-09-12 实测口径)

用于判定"能不能拿外部项目已训好的权重直接开机器人", 以及**真跑官方评测**的运行口径。
INTACT-JEPA 本机实测, 但结论对任何"论文权重 + 冻结运行时"的外部项目同构。

## 1. 先分清两条线 (老倪会追问 "X 不是已经训好了么? 你为什么还要训练")

外部项目已训好的权重只覆盖**它自己的任务/动作空间**。以 INTACT 为例:

| 机器人 | 原生环境 | 动作空间 | 权重 |
|---|---|---|---|
| reacher | swm/ReacherDMControl-v0 (DMControl **两连杆臂**, qpos_match) | 关节 | recovery_delta_full_reacher_s3072 |
| pusht | swm/PushT-v1 (2D 推块) | 2D+夹爪 | recovery_delta_full_pusht_s3072 |
| cube | OGBench cube-single (3D 机械臂推方块) | 7 维关节 | recovery_delta_full_cube_s3072 |
| tworoom | OGBench tworoom (两房间导航) | 2D | recovery_delta_full_tworoom_s3072 |

⚠️ **命名撞车**: 原项目 `reacher` = DMControl 两连杆臂, **不是** metaworld 里 Sawyer 臂的 reacher。
本工程机器人 (metaworld peg-insert-side-v3, 动作 4D 笛卡尔) 外部项目**从没训过** → 想让它驱动必须域内微调。
回答"为什么还训练"时, 先把"哪些是已训好的 (只跑评测即可) / 哪些是我们域内新任务 (必须微调)"列清楚。

## 2. 官方评测的运行口径 (读源码 + 实测, 别按 README 猜)

```
cd <repo>/paper_runtime && PYTHONPATH=<repo>/paper_runtime \
  <repo>/.venv/bin/python eval.py --config-name=<task> solver=prior_only policy=<ckpt> \
    seed=42 eval.num_eval=6 output.filename=<task>_direct_seed42_n6.txt
```
- 在仓库根跑 → `Error locating target 'module.InverseTransitionActor'` (论文 checkpoint 的 config 引用
  paper_runtime 的 module; 根运行时参数布局不同)。
- 零搜索求解器在论文运行时里叫 **prior_only** (根 `direct_solver.py` 与论文 actor 命名不兼容 →
  `Error locating target 'direct_solver.DirectSolver'`)。
- 数据集必须落 `$STABLEWM_HOME/datasets/<dataset>.h5` (reacher=dmc/reacher_random.h5 · pusht=pusht_expert_train.h5 ·
  cube=ogbench/cube_single_expert.h5 · tworoom=tworoom.h5); **policy 的 process = 数据集 fit 的 StandardScaler**,
  没有数据集就没有正确归一化 → 在线 rollout 必是垃圾动作。
- 产物: `results_path = get_cache_dir()/cfg.policy` 的**父目录** = `$STABLEWM_HOME/` →
  结果 txt + **每 episode 一段 `env_*.mp4`**; ⚠️ 每跑一次会覆盖 → 跑前 `rm env_*.mp4`, 跑完立刻复制到自己的证据目录。
- 本机基线 (可当回归对照): tworoom 100% (6/6) · cube 83.3% (5/6) · 均 `get_cost_calls_sum=0.0` (真零搜索)。
  顶层 `get_cost_calls` 可能是回退默认值, 证据要看 `solver_timing.get_cost_calls_sum`。

## 3. 直接开的判决: 外部权重 → 本工程机器人 (实测两个负结果)

```
动作映射 (外部 chunk → 本工程动作空间): 单轴 |ρ| 0.131 / 0.388 / 0.144; 嵌套 5 折样本外 R² ≈ −0.0002
直驱闭环 (模型动作 → env.step): 0/2 失败; 模型动作 std 比教师小 ~20 倍 (动作头塌在均值)
离线回放 (真帧→模型→预测 vs 教师): xyz MAE 0.092 **劣于常数基线 0.086**
⇒ 外部权重直接开 = 不行 (结构性: 它输出的是"离目标多远"的意图位移, 不是速度指令)
```
**判决器铁律**: 上闭环前必须先过**离线回放闸且显著赢常数基线**; 并检查动作头是否塌缩
(预测 std 与教师 std 同量级才算学到动作; std 小一个量级 = 塌到均值, 管线通≠能跑)。

## 4. 域内微调的观察 (v2, 数据 8×, 动作头权重 0.1/0.05 → 1.0/1.0)

- 8GB 卡实测 batch24 OOM (`torch.OutOfMemoryError` ~7.6GB) → **batch16 + workers12** 稳定, ~2 it/s。
- 步数预算: 一个 epoch ≈ 数据帧数 / batch; 200 epoch 级预算别拍脑袋, 按实测 it/s 算时间点再定 epoch 数。
- 判闸做成**无人值守守护**: 每个 `weights_epoch_N.pt` 一落盘 → 立刻 CPU 跑离线回放 (不抢训练显存) → 追加日志 + json,
  过闸就提前上闭环, 不等满轮数。
- 进度观察 (epoch 1→2): MAE 0.112 → 0.0968 (常数基线 0.0993), 预测 std 仍小 ~16 倍 → **仍不能上闭环**;
  MAE 略胜常数 ≠ 学会动作, 报告里必须同时给 std 对比, 不许只报 MAE 说"有提升"。
