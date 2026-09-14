# 权重结构: 共享编码器 + 每任务分片 (2026-09-13 实测)

## 用户问过的问题
"为什么要四个模型权重？没有泛化性么？" —— 标准答案: **不是四个独立模型**, 是「一个共享编码器 + 四份任务分片」。

## 官方发布包结构
`checkpoints_hf/INTACT-unified/PAPER_E5_GOAL_MANIFEST.json` (release `paper-e5-goal-v1`, model = Goal-displacement INTACT, epoch 5):

```
6 个 cell × 3 个训练种子 × 4 个任务分片 = 72 个 ckpt
每个训练种子 = 1 个 shared_state_sha256 + 4 个 shard
  seed 3072  shared_state_sha256 7cf4b0ca65011c7f…   official SR {pusht 79.67, cube 98.67, reacher 97.00, tworoom 78.67, macro 88.50}
    shard pusht    checkpoints/recovery_delta_full_pusht_s3072/weights_epoch_5.pt    84,734,848 B  sha256 24a598acac5f…
    shard cube     checkpoints/recovery_delta_full_cube_s3072/weights_epoch_5.pt     84,858,432 B
    shard reacher  checkpoints/recovery_delta_full_reacher_s3072/weights_epoch_5.pt  84,734,848 B
    shard tworoom  checkpoints/recovery_delta_full_tworoom_s3072/weights_epoch_5.pt  84,734,848 B
```
本机只下了 goal_intact cell × seed 3072 的 4 片 (本地 sha256 与清单逐字节一致 —— preflight 打出的
`sha256=24a598acac5f` 就是清单里的 pusht 分片)。

## 逐 key 比对实测 (pusht 为基准)
```
四份张量构成完全同构: encoder 198 + predictor 81 + inverse_actor 14 + projector 9 + pred_proj 9 + action_encoder 6 = 317
cube     完全相同 208 / 不同 109   其中 encoder.* 198 个 → 全部 torch.equal 相同; 只有 action_encoder.* 6 个不同
reacher  完全相同 208 / 不同 109   (同上)
tworoom  完全相同 208 / 不同 109   (同上)
⇒ 共享部分 = ViT-Tiny/14 编码器 (198 张量, 逐张量完全相同)
⇒ 任务相关 = action_encoder(6) + predictor(81) + inverse_actor(14) + projector(9) + pred_proj(9) = 109
```

## 踩过的坑: 分组别用子串, 要用前缀
第一次按 `"encoder" in key` 分组 → `action_encoder.*` 也被算进"编码器", 于是四份哈希全不同,
差点得出"编码器根本没共享"的错结论。**必须按 key 前缀 (`key.split(".")[0]`) 分组**,
再对每组逐张量 `torch.equal`。脚本: `scripts/diff_ckpt_prefixes.py`。

## 为什么必须分片 (物理约束, 不是泛化性缺失)
- 动作维度不同: `inverse_actor.action_dim` = **10** (pusht/reacher/tworoom = 5 步块 × 每步 2 维) vs **25** (cube = 5 × 5)
- 一个动作头不可能同时输出 2 维和 5 维动作; 数据集观测/动作语义也不同
- 共享编码器才是跨任务的部分 (论文第 5 组实验 E5 = shared-encoder 设定)

## 泛化性体现在三层
1. 跨任务: 共享编码器 (同一套视觉表征 + 潜空间服务四任务)
2. 任务内 (真正的评测口径): 起点是从数据集合法起始帧抽的 (pusht 1,869,611 个候选 / cube 1,760,000 个),
   配 goal_offset=25 的目标状态, 在**真实环境** rollout → 考未见过的起点/目标组合, 不是回放专家轨迹
3. 论文 6 cell 对照本身就是"接口设计"的泛化实验: CEM 300x30 / Direct / waypoint intent / goal intent /
   waypoint INTACT / goal INTACT, 每格 3 训练种子 × 4 任务 × 3 eval seed × 100 局

## 官方数字 (来源 PAPER_CHECKPOINTS.md / PAPER_E5_GOAL_MANIFEST.json)
```
任务      seed3072 列   三训练种子均值±样本std   本机 09-13 实测 (seed3072 片)
pusht     79.67         80.22 ± 1.26            76 / 85 / 77 = 79.33±4.93
cube      98.67         99.56 ± 0.77            100 / 97 / 99 = 98.67±1.53  ← 首次跑通, 与官方完全相同
reacher   97.00         95.67 ± 1.76            95 / 99 / 97 = 97.00±2.00
tworoom   78.67         82.11 ± 4.11            81 / 74 / 81 = 78.67±4.04
macro     88.50         89.39 ± 0.77            —
```
headline cell 是 goal_intact (macro 89.39±0.77)。
