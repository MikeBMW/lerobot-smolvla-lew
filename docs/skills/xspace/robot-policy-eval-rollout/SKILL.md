---
name: robot-policy-eval-rollout
description: 评估/rollout 已训练机器人策略(ACT/SmolVLA/AWE/MLP), 0%成功率排查, 行为视频生成。
---

# 机器人策略评估与 rollout（0% 成功率排查 · 行为视频）

## 触发
- 评估已训练策略的插拔/抓取成功率（eval_insert.py / run_episode）
- 评估结果全 0% / 模型"不动"或"后退"，怀疑评估管道而非模型
- 生成模型行为视频（证明方向性/插拔，双面板趋势）

## 0% 成功率排查清单（按顺序查，每项都曾导致假 0%）
1. **归一化 stats 用模型自己的 checkpoint preprocessor**（2026-08-08 实测）
   - SmolVLA 是**逐维 39 个 mean/std**；ACT 旧版是**标量**（需广播）
   - 用错模型 stats → 归一化错位 → 模型看不懂输入 → 假 0%
   - `_load_stats(policy_name)` 按模型名映射 ckpt；先逐维，标量才广播
   - 证据：`state mean` 维度 = 39（逐维✅）还是 1（标量❌）
2. **图像尺寸按模型**：SmolVLA `siglip_image_size=64`（喂 128 视觉编码全错），ACT 是 128
   - eval 里按 `type(policy).__name__.startswith("smolvla")` 判断
3. **diffusion 策略（AWE/VLA-Touch）输出是归一化空间**：env.step 前必须 `act*std+mean`
   - stats 键名 `a_mean/a_std`（不是 action.mean/std）；normalizer safetensors 键是 `observation.state.mean`
4. **训练/评估同构**：训练用 YOLO 检测 state → 评估也要（见 yolo-3d-perception-chain）
5. **看 dist 是否恒定**：所有 seed 的 peg→hole 距离完全一样 = peg 从未被碰 = 模型动作没生效或方向错

## 多阶段轨迹"平均化"坑（训练数据层，最重要）
- 长轨迹（300 步）含**方向相反**的阶段（接近→插入）→ 行为克隆学到**平均动作 = 后退**
- 症状：评估全 0%，行为视频显示手朝反方向 / 距离上升
- **MLP 39D 直接映射免疫**（每步条件反射，不依赖时序）→ 唯一能插拔的学习模型
- 解法：短单方向轨迹（只到抓起）/ 分阶段训练 / 用 39D 直接映射架构
- 教训：反复重训大模型浪费时间，先验证数据阶段方向一致性

## 夹爪辅助 grip_assist
- 接近阈值（<8cm）强制闭合夹爪 = 真实机器人"视觉+力控"混合，不是作弊
- ⚠️ 先测纯模型：MLP 纯模型 6/10 抓起 > 加辅助 0/10（辅助覆盖破坏行为）
- 只在模型有接近能力但缺离散夹爪决策时用

## 行为视频生成
- 双面板：左画面 + 右**距离趋势曲线**（画面位移小，趋势图才证明方向）
- 旋转 180°：`ffmpeg -vf "transpose=2,transpose=2"`
- 方向标准以用户反馈为准（本用户曾"原版不旋转"后又"旋转180"——每次生成后问或两种都出）
- 批量转码后一起发（用户嫌"一个一个发"）

## 视频生成脚本的模型加载坑 (2026-08-12 双脑 gen_insert_video.py 实测)
"生成视频慢/不生成"排查顺序（4 个根因都踩过）:
1. **训练产物权限**: docker root 产物 `-rw------- root` 当前用户读不了 → 加载失败。修复: `sudo find outputs/train/ -type d -exec chmod 755 {} + && find ... -type f -exec chmod 644 {} +`(全量, 历史产物同样 600); GUI 遍历训练目录必须 try/except 容错(权限异常会让**整个 GUI 启动崩溃**)
2. **脚本写死旧模型**: 改按 `os.path.getmtime` 排序取最新 `outputs/train/left_right_*/checkpoints/last/pretrained_model/model.pt`(字母序会把 left_right_std 排最前, 必须按时间)
3. **网络结构版本不匹配**(权重键匹配决定用哪个实现): 同一模型名两个版本 — 旧管线版有 align_head(forward 3 值), lerobot 训练版无(2 值 next, contact); 用错版 load_state_dict 报 Missing key(s); 调用处解包数也要匹配(3 值→2 值 ValueError)
4. **归一化参数来源**: checkpoint model.pt 只存权重 {left, right, obs_dim, act_dim}, 归一化在 preprocessor/postprocessor safetensors(`observation.state.mean/std`、`action.mean/std`, 标量整段) — 别假设和旧管线 pt 一样有 xm/xs/ym/ys
- 生成慢 = seed 试跑(12×500 次推理)+ 渲染 + ffmpeg; GPU 空闲 48s, CPU 数十分钟
- 训练完自动生成(后台 force 模式不弹窗)让用户点节点秒开, 不等生成

## 数据生成 pitfall（多阶段专家）
- `lifted` 判断用 **peg 高度**（pegGrasp z 相对初始 +0.04），**不用手高度**（手初始 z 高 → 永远 True → 跳过抓取直接转移）
- **peg 位置每步重新获取** `env.data.site_xpos[pid]`（循环外取值是初始位置，抓取点全错）
- 官方专家仅标准起点有效（手被远移后状态机失效 → 用手写多阶段专家）

## 用户节奏偏好（老倪）
- 催"快点出结果"时：**停止无限调试**，交付已有最佳产物（成功视频/报告）+ 诚实状态
- 大模型反复重训投入产出比低——先确认数据/评估管道正确再重训

## 参考
- `references/peg-insert-eval-2026-08.md` — 各模型 ckpt/stats 表 + 排查时间线
