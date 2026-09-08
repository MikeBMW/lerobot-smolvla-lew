# peg-insert 评估排查时间线（2026-08-07/08 实测）

## 各模型 checkpoint → 归一化 stats 映射（_load_stats policy_hint）
| policy | ckpt 目录 | stats 维度 |
|---|---|---|
| smolvla | outputs/train/smolvla_peg_long2/checkpoints/004000 | 逐维 39 |
| act | outputs/train/act_pegdata_4000/checkpoints/004000 | 标量(广播) |
| awe_zflow | outputs/train/awe_zflow_20260808_002622/checkpoints/000050 | checkpoint 自带 s_mean/s_std(39) + a_mean/a_std(4) |
| vla_touch | outputs/train/vla_touch_20260807_141958/checkpoints/000050 | 同 AWE |
| expert_mlp | outputs/rl_peg/expert_mlp.pt | MLP 直接输入原始 39D（无需归一化） |

## preprocessor safetensors 键名
- normalizer: `policy_preprocessor_step_3_normalizer_processor.safetensors`
- 键: `observation.state.mean/std` (39 或 1), `action.mean/std` (4 或 1)
- AWE 可能用 step_2 → glob `policy_preprocessor_step_*normalizer*`

## 排查顺序（每个 bug 的症状）
1. 标量广播 vs 逐维 → 模型"不动"或恒定动作（dist 全不变）
2. 图像 128 vs 64（SmolVLA）→ 视觉编码错 → 动作乱但变化
3. 缺反归一化（AWE/VLA-Touch）→ 动作恒定归一化值 [-0.01,-0.215,...] 直接执行
4. dist_hole 恒 = peg 初始到 hole 距离 → peg 从未被碰

## 训练数据阶段方向验证
```python
# 检查轨迹阶段方向是否一致（防平均化）
a0 = 轨迹0动作
print(前30步均值)  # 应接近阶段（朝 peg）
print(中30步均值)  # 应抓取（夹爪 -1）
print(后30步均值)  # grab-only: 应保持
```
- 官方专家数据夹爪顺序先 -1 后 0.6（离散决策），BC 学不到闭合时机
- 300 步长轨迹：接近(x+) + 插入(x-) 方向相反 → 学成平均/后退

## 各模型最终结果（诚实记录）
- 官方专家：85%（19/20 抓起 17/20 插入）— 基准
- MLP 蒸馏（expert_mlp.pt 22:36 版，纯模型）：抓起 6/10、插入 3/10
- ACT/SmolVLA/AWE 长轨迹 4000 步：全 0%（学成后退）
- 视频：mlp_insert_success_rot180.mp4（插入 0.013m）、smolvla_long_behavior_rot180.mp4（后退证明）

## 用户节奏教训
老倪"你到底要折腾到什么时候，快点给我出结果"→ 停止数据生成/重训循环，
先发已有成功视频（MLP + 专家），再给诚实状态。大模型反复重训不做（投入产出比低）。
