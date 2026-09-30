# 评估管道 3 bug 完整排查过程 (2026-08-08)

场景: 7 模型 peg-insert 对比。MLP 蒸馏 6/10 抓起，但 ACT/SmolVLA/AWE 全 0%。
特征: 所有 seed 的 dist_hole 数值完全一样 (0.352/0.291/0.319...) = peg 初始→hole 距离
      = peg 从未被碰 = 模型动作没生效。这是"假 0%"的典型指纹。

## Bug 1: 归一化用错来源 (标量 vs 逐维)
- 旧 `_load_stats()` 硬编码读 ACT checkpoint (标量 mean/std, shape (1,)) → 广播到 39D
- SmolVLA/AWE 训练是逐维归一化 (39 个独立 mean/std)
- 结果: 喂给模型的 state 分布全错 → 输出乱
- 修: 候选 checkpoint 列表逐个找 normalizer safetensors，读 `observation.state.mean/std`，
  `sm.size==1 → 广播`, 否则直接用逐维

## Bug 2: diffusion 模型输出未反归一化
- eval_insert 里 AWE 走 `hasattr(policy, "_cond")` 分支 → 后来发现 AWE 没有 _cond
  (AttributeError) → 实际走 else 分支 `policy(s_t, t_t, act_hist, None)`
- else 分支当时无反归一化 → 归一化空间动作直接 env.step → 动作尺度错
- 且 `_cond` 分支的反归一化用了错误键名 (`action.mean/std`) → AWE 存的是 `a_mean/a_std`
- 修: 两个分支都加反归一化 + 键名兼容 (`a_std` 优先, 回退 `action.std`)
- AWE 的 state 归一化还要用 `policy.stats["s_mean/s_std"]`（checkpoint 自带）

## Bug 3: SmolVLA 图像尺寸 128 vs 64
- config: `siglip_image_size: 64, num_vision_tokens: 64`
- eval_insert 统一 resize 128×128 → SmolVLA 视觉编码错
- 修: `img_size = 64 if type(policy).__name__.lower().startswith("smolvla") else 128`

## Bug 4 (数据集): 显式 episodes 列表触发 KeyError 1800
- 生成器丢弃失败轨迹 → episode_index 空洞 (如 0,1,2,3,4,6,7)
- config `dataset.episodes: [0..11]` → reader 绝对/相对索引映射缺项 → KeyError
- 修: 移除 episodes 显式列表（用全部）

## 长轨迹平均化 (设计层教训)
- 用 300 步长轨迹 (接近+插入) 重训 ACT/SmolVLA/AWE → 全部学到"后退"
- 原因: BC 回归对多阶段相反方向取平均 → 动作趋零/反向
- MLP 蒸馏 (39D 输入→4D 输出, 每步独立) 不受影响 → 唯一能插拔的学习模型
- 官方专家 85% (19/20 抓起 17/20 插入) 仍是真值锚点

## 有效指纹
- dist_hole 恒定 = peg 未动 = 评估管道问题 (不是模型问题)
- 修复后同一评估从 0/10 → 有真实行为 (如 MLP 6/10)
