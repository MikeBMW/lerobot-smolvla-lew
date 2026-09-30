---
name: robot-policy-eval-training
description: 机器人策略(ACT/SmolVLA/AWE)评估管道同构性与训练数据坑, 防假0%抓取。
---

# 机器人策略评估与训练数据 (peg-insert 实测)

## 触发
- metaworld/仿真机器人策略 (ACT/SmolVLA/LEW/VLA-Touch/AWE) 训练或评估
- 评估 0% 但模型明明训练过 / 手动 rollout 能动但 eval 不动
- 行为克隆模型"后退/不动"（方向性退化）

## 评估管道同构 4 大坑 (每个都导致假 0%, 08-08 全踩过)

### ① 归一化逐维 + 按模型加载
- 每个模型 checkpoint 的 `policy_preprocessor_step_*_normalizer_processor.safetensors`
  是**逐维 mean/std**（39 或 45 个值），不是标量！
- 标量广播 → state 归一化全错 → 模型输入分布错 → 输出乱
- 必须按模型名选对应 checkpoint：`_load_stats(policy_name)`
- VLA-Touch/AWE checkpoint **无 preprocessor** → 直接用数据 `meta/stats.json`
  （但先查 checkpoint 是否有 normalizer 文件，用 glob 探 step_* 通配）

### ② 图像尺寸必须匹配
- SmolVLA: `siglip_image_size: 64` → 评估喂 64×64
- ACT: 128×128
- 喂错尺寸 → 视觉编码全错 → 模型看不懂 → 输出乱/恒定

### ③ diffusion 模型必须反归一化
- AWE/VLA-Touch 输出是**归一化空间动作**，eval 必须 `act*std+mean` 还原再 env.step
- ACT 走 `select_action` 分支有反归一化；AWE 无 `_cond` 走 else 分支——**else 分支也要加**
- stats 键名: 训练脚本存 `a_mean/a_std`（非 `action.mean/std`），两者都要兼容

### ④ 45D 相对向量评估补全
- 训练数据若含 rel_vec（39+6=45D: hand→peg, peg→hole），评估时 state 现场算相对向量拼上
- 否则形状 (1,39) vs 权重 (45,256) 报错

## 长轨迹数据平均化 (08-08 核心教训)
- **多阶段长轨迹（300 步"接近"+"插入"方向相反）→ 行为克隆学到平均动作 = 后退/不动**
- 证据: 5 个视觉模型全部 0%，距孔=初始值（peg 从没被碰过）
- **只有纯坐标映射模型免疫**: MLP 蒸馏（39D 直接映射）6/10 抓起、官方专家 85%
- 解法: ①分段数据（截断到"抓起"即停，方向一致）②坐标叠加架构

## 数据生成器截断 (stop_after_grab) 的坑
1. **官方专家必须 corner2 相机**（`camera_name="corner2"`）——无 corner2 专家状态机失效
2. **lifted 判断用 peg 相对初始升高**（`peg_z > peg_z0 + 0.03`），不能用手的高度
   （手初始 z 就高 → 永远 True → 跳过抓取直接转移）
3. **peg 位置每步重新获取**（`env.data.site_xpos[pid]` 循环内取，抓取点随 peg 移动）
4. **官方专家路径有自己的 continue** —— 截断检测必须加在官方专家路径内，
   且 continue 前检查 break（否则 grabbed_frames 到 30 也不断）
5. **锁存逻辑**: 抓起后每帧无条件 +1（`if grabbed>=1: grabbed+=1`），
   不能只在 peg 回落时 +1（peg 持续升高时永远不涨）
6. **截断后数据修 3 处**: info.json 的 `total_frames` + `splits`（`0:N` 按实际行数）
   + `features.observation.state.shape`（45D）+ 重建 `meta/episodes/chunk-000/episodes_000.json`
   （每 episode length 按实际截断后行数）——只改 total_frames 会 IndexError 1800 out of bounds

## 坐标叠加架构 (老倪: 坐标是逻辑主线, 图像是背景)
- ACT `modeling_act.py` encoder 输入: `latent_embed += encoder_robot_state_input_proj(state)`
- state 不再作独立 token（原来 49 图像 token 淹没 1 个坐标 token）
- 图像保留为背景 token；`n_1d_tokens` 减 1（state 不占位）
- 训练/推理共用 forward，select_action 也走叠加
- simulink 画布对应 🧩 坐标叠加节点 (coord_overlay, node_logic.py 注册)

## 训练环境坑
- **HF_HUB_OFFLINE=1 会阻止数据集 refs 解析**：lerobot_train 报
  `OfflineModeIsEnabled: Cannot reach huggingface.co/api/datasets/lerobot/pusht/refs`
  → 只用 `TRANSFORMERS_OFFLINE=1`（权重离线），数据集解析保持在线（本地 root 只查 refs）
- 删 `~/.cache/huggingface/datasets` 后首次训练重建缓存（慢）；数据 meta 修过必须清缓存，
  否则训练进程读到旧 meta（IndexError 1800 out of bounds 等）

## 参考
- `references/eval-pipeline-iso.md` — 完整 bug 链 + 修复代码位置
- 关联: yolo-3d-perception-chain（YOLO 感知同构）、hf-weight-download（权重下载）
