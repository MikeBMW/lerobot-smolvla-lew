---
name: robot-policy-eval
description: 机器人策略仿真评估管道陷阱, 归一化来源, 图像尺寸, 反归一化, 长轨迹平均化, 假0%诊断。
---

# 机器人策略评估管道陷阱 (仿真 rollout)

## 触发
- 评估 ACT/SmolVLA/AWE/VLA-Touch/MLP 插拔或抓取成功率
- 评估结果全 0% 但训练 loss 正常 → 先查本技能的管道 bug
- 新模型评估前（防"假 0%"）

## 铁律 1: 归一化必须与训练完全一致（最常见假 0% 根因）
- **来源**: 从该模型 checkpoint 的 `policy_preprocessor_step_*_normalizer_processor.safetensors` 读 mean/std
- **逐维 vs 标量**: SmolVLA/AWE 是逐维 (39,)；旧 ACT 是标量 (1,) 需广播。读时判断 `sm.size==1 → np.full(39, ...)`
- **VLA-Touch/AWE checkpoint 无 preprocessor**（只有 config.json+model.pt）→ 它们的 stats 从**数据 stats.json** 读（`data/metaworld_peg_seg/meta/stats.json` 45D）——`_load_stats` 里对 `vla_touch/awe_zflow` 直接走数据 stats 分支
- **不要默认用数据 stats.json**: v5/v6/v7 数据目录可能被清，且可能是 1 维坏 stats → 全错（仅 VLA/AWE 这类无 preprocessor 的模型才 fallback 数据 stats）
- **AWE/VLA-Touch 的 state 归一化**还要用 checkpoint 自己的 `s_mean/s_std`（`policy.stats` 字段），不是全局 stats
- eval_insert.py 曾有 `sm=zeros, ss=ones` 调试残留覆盖归一化 → 删干净

## 铁律 2: 输出必须反归一化 (act*std+mean)
- ACT select_action 输出归一化空间 → 反归一化后才 env.step
- **AWE/VLA-Touch diffusion 输出也是归一化空间** — `_cond` 分支 AND else 分支都要反归一化（曾只改一处，else 分支漏了仍 0%）
- stats 键名: AWE 用 `a_mean/a_std`（不是 action.mean/std），读取要兼容两种
- 归一化动作直接 env.step = 动作尺度全错 = 假 0%

## 铁律 3: 图像尺寸按模型
- SmolVLA: `siglip_image_size=64` → 视觉输入 **64×64**
- ACT: 128×128
- 喂错尺寸 → 视觉编码错 → 模型输出乱 → 假 0%
- 判断: `type(policy).__name__.lower().startswith("smolvla") → 64 else 128`

## 铁律 4: 长轨迹平均化（行为克隆固有限制）
- 300 步长轨迹 = 接近(方向A) + 插入(方向B) 方向相反 → BC 回归学到"平均动作/后退"
- **实测 ACT/SmolVLA/AWE 长轨迹训练全部学到后退**（dist_hole 恒为 peg 初始→hole 距离 = peg 从未被碰）
- **MLP 蒸馏免疫**: 39D 坐标直接映射动作，每步独立决策，不受时序平均化影响
- 结论: 插拔主力 = MLP 蒸馏 + 官方专家；大模型长轨迹重训是死路
- **45D+分段数据后的实测 (08-08)**: ACT-seg 从"原地不动"进步到"会动"（dist 变化）但仍 0/10 抓起；VLA-Touch/AWE-seg(2000步) 仍不动；SmolVLA-seg 0/10 → 45D 解决方向性，**夹爪离散决策仍是最后瓶颈**（回归学不会"何时捏"，需 grip_assist/独立夹爪头）

## 铁律 4b: RL 也学不会插拔（稀疏奖励）
- PPO 60 轮 0% 抓起（奖励 -9.9 卡住=学"原地不动"）；官方专家 warm-start 后 -5.0 仍 0%
- 根因: "抓起"是稀疏事件，随机探索碰不到"刚好捏住"瞬间 → 拿不到 +10
- 出路: **RL+规则混合** — 位置动作用 RL（距离奖励平滑），夹爪交给规则触发（grip_assist）——尚未实测，是待试方向

## 铁律 5: 数据集 episodes 坑
- 丢弃轨迹后 episode_index 有空洞 → 显式 `episodes: [0..N-1]` 列表触发 reader `KeyError`（绝对/相对索引映射缺项）
- 修: 配置去掉 episodes 显式列表（用全部）或重编号 0..N-1
- config 继承会残留 steps=10 调试值 → 检查 steps 再训

## 铁律 6: 目标条件化 (rel_vec, 45D) — 训练与评估必须同构
- 2026-08-08 方案: state 39D → 45D，尾部 +6 = `[peg-hand, hole-peg]` 相对向量（MLP 成功的核心，分享给所有模型）
- 生成器: `--rel-vec` 生成 45D 数据；info.json 的 `features.observation.state.shape` 必须同步改 `[45]`（否则 CastError）
- **评估必须补同样 6 维**: `st_raw[:39]` + 从 env site 算 rel_vec 拼上，否则 `(1x39) vs (45x256)` 形状错误
- `_load_stats` 候选列表要含当前模型 45D checkpoint（否则读到 39D 旧 stats → broadcast 错误）
- 实测效果: ACT-seg 45D 后"动了"（dist 变化）但仍未抓起 → 45D 解决方向性，夹爪仍需 head 分离

## 铁律 7: 数据生成器三个坑（多阶段专家）
- **lifted 判断**: 用 `peg_z > peg_z0 + 0.04`（peg 相对初始升高），**不要用 `ee[2] > target_hole[2]`**（手初始 z=0.155 就高 → 永远 True → 跳过抓取直接转移）
- **peg 位置每步重新获取**: `site_xpos[pid]` 会随物理变化，循环外取一次 = 目标永远初始值
- **官方专家远起点状态机失效**: SawyerPegInsertionSideV3Policy 假设手在标准起点，手被移走后策略错乱（接近不了）→ --far 用多阶段专家
- grab-only 数据生成常全丢: 接近加速 0.3 太快抓取失误 → 加速降到 0.18 仍不稳；官方专家夹爪序列"先-1后0.6"（前30步闭合）是固有特性，MLP 能学但大模型难
- **分段数据 (stop-after-grab)**: 抓起后保持 30 帧即停记录，避免转移段方向反转（铁律 4 的解法）

## 快速诊断（评估全 0% 时按序查）
1. dist_hole 是否恒为初始值（0.35 左右）→ peg 没被碰 → 模型动作没生效
2. 手动单步打印动作: 归一化 vs 反归一化后数值是否合理
3. 查 _load_stats 返回 mean 维度 (39 vs 1)
4. 查图像尺寸 vs 模型 config
5. 夹爪: MLP 自己学会夹爪时机（纯模型评估 6/10），grip_assist 强制闭合反而破坏 → 先纯模型再辅助

## 参考
- `references/eval-pipeline-bugs-2026-08.md` — 本次 3 bug 完整排查过程
- `references/relvec-45d-and-data-gen-bugs-2026-08.md` — 45D 目标条件化实现 + 数据生成器 bug 链 (lifted判断/peg每步获取/官方专家远起点失效)
