# 2026-08-07/08 实测记录 (Z-MAX peg-insert 训练评估全过程)

## 评估管道 bug 链 (每个都导致"假 0%")
1. `_load_stats()` 最初硬编码 ACT 目录 → 读到 39D 标量广播 → SmolVLA 逐维 39 值被广播错
   → 修复: `_load_stats(policy_name)` 按模型映射 + safetensors 逐维读取
2. SmolVLA 喂 128px 图 (config siglip_image_size=64) → 视觉编码全错
3. AWE/VLA-Touch `_cond`/else 分支输出未反归一化 → 归一化动作直接 env.step = 原地不动
4. VLA-Touch/AWE checkpoint 只有 config+model.pt 无 preprocessor → fallback 数据 stats.json
5. 45D 模型评估: st_raw 只有 39 → 现场补 6D 相对向量

## 坐标叠加实现 (modeling_act.py)
```python
latent_embed = self.encoder_latent_input_proj(latent_sample)
if self.config.robot_state_feature:
    state_embed = self.encoder_robot_state_input_proj(batch[OBS_STATE])
    latent_embed = latent_embed + state_embed   # 坐标叠加进 latent
encoder_in_tokens = [latent_embed]             # 不再 append state token
# n_1d_tokens = 1 (原 1+state+env=3) — 否则 pos_embed 18 vs 17 报错
```
- 训练报错 `The size of tensor a (17) must match the size of tensor b (18)` 即此因。

## 画布功能块注册 (simulink)
1. node_logic.py: `def node_coord_overlay(ctx)` + `_reg("coord_overlay", ["坐标叠加","CoordOverlay"], ...)`
2. simulink_module.py: NODE_TYPES 加 `"coord_overlay": {"cn":"坐标叠加","color":"#58a6ff"}`
3. paint 分支 (elif t == "coord_overlay": 画 + 号 + 文本)
4. 默认画布 5 模型行 "🔌 State Adapter" 后插 "🧩 坐标叠加"
5. 框架方法用 `fn = getattr(module, "_set_..._ctx", None); fn(...) if fn else None` 容错
6. 验证: `/usr/bin/python3 -c "import node_logic; node_logic.match_node('🧩 坐标叠加')"`

## BC 多阶段退化数据证据
- ACT 手动测试有方向性 (dist 0.173→0.065) 但评估 0% → 数据生成器 bug:
  `lifted = ee[2] > target_hole[2]-0.01` (手初始 z=0.155>0.121 永远 True) → 跳过抓取
- 修复后 grab-only 全丢弃: 接近速度 0.3 太快 → 0.18
- 官方专家动作序列夹爪先 -1 后 0.6 (离散), 多阶段专家夹爪 0→-0.8→-1 更适合 BC

## RL 组合 (train_peg_rl.py)
- 纯 PPO 60 轮 -9.9 卡住 (稀疏抓取奖励探索不到)
- 组合: run_episode 里位置动作用 RL (a[:3]*0.15), 夹爪规则:
  `d_hp<0.08 未抬起 → -1.0 闭合; lifted → 0.6; 否则 0.0`

## MLP 蒸馏 (唯一成功的学习模型)
- expert_mlp.pt: 39D obs → 4D act, Sequential(net.0/3/6/8 = Linear512×3+Linear4)
- 加载: `from tools.distill_expert import ExpertMLP` (结构一致)
- 输出 unbounded → `np.clip(act, -1, 1)` clamp
- 纯模型评估 6/10 抓起 3/10 插入; 夹爪辅助反而破坏 (模型自己会闭合)
- 找成功 seed: 15 seeds 里 seed1/5/10/14 插入 (最近距孔 0.004-0.027m)

## VAE 训练/推理不一致 (2026-08-08 决定性发现)
- ACT 原版 use_vae=true: 训练时 latent 由 VAE encoder 从未来动作编码 (偷看答案),
  推理时 latent=zeros (答案消失) → "考试作弊学生"问题
- 叠加架构 (latent += state) 放大该 gap: 有 VAE 时 state 叠加到一坨不稳定 latent 上,
  模型学乱 → 输出恒定平均动作, 距孔完全不变 (0/10)
- 数据量 17→68 条都不是瓶颈; **use_vae: false (纯 transformer 回归) 立即突破**:
  ACT 0.247→0.066m 大幅接近 (最近 0.029m, 200 步), 首次学会"走向 peg"
- 原版 VAE 好使条件: 多模态任务 (多条路都对, latent=多样性开关) + 大数据量;
  peg-insert 是单模态唯一路线 → VAE 的多样性能力用不上, 只留 gap
- 排查"模型不动"顺序: 先查 use_vae, 再查数据量

## stop_after_grab 截断实现细节 (2026-08-08 实测)
- 官方专家路径 (use_official) 有自己的 all_frames.append + `continue` →
  循环开头 break 被跳过 → 官方分支内也要加截断检测 + continue 前 break
- 锁存: `grabbed_frames = max(grabbed_frames, 1)` 后**每帧无条件 +1**
  (elif 只在回落 +1 时, peg 持续升高永远不增长)
- 阈值 0.04→0.03: 抓起瞬间 peg_z=0.065 (初始 0.03, +0.035<0.04 检测不到)
- 成功截断后轨迹 ~90-100 帧 (抓起点 ~65 + 30 帧保持), 数据方向一致:
  前半夹爪 -0.3 (闭合抓取) → 后半 +0.35 (保持)
- 100 eps 生成 → 实际成功 68 eps / 6040 帧 (官方专家有 ~30% 抓取失败率,
  丢弃后 episode_index 稀疏必须重编号)

## LeRobotDataset 元数据完整修复 (2026-08-08)
```
IndexError: Invalid key: 1800 is out of bounds for size 1015  ← episodes length 仍 300
KeyError: 'videos/observation.image/chunk_index'               ← 缺字段
ValueError: Column 'dataset_from_index' doesn't exist.          ← 缺全局区间列
```
- 数据 parquet: episode_index 重编号 0..N-1 (old2new map)
- episodes parquet 完整字段 (15 列):
  episode_index, length, tasks, dataset_from_index, dataset_to_index,
  videos/observation.image/{chunk_index, file_index, frame_index,
  from_timestamp, to_timestamp}, data/{chunk_index, file_index},
  meta/episodes/{chunk_index, file_index}
  (dataset_from/to = 全局累积帧区间, from/to_timestamp = (start..end-1)/30.0)
- info.json 三处: total_frames, total_episodes, splits {"train": "0:<N>"},
  features.observation.state.shape=[45]
- 改完必 `rm -rf ~/.cache/huggingface/datasets` (训练读缓存旧 meta)
- HF_HUB_OFFLINE=0 TRANSFORMERS_OFFLINE=1 (OFFLINE=1 数据集 refs 解析直接报错)

## 控制台训练节点默认配置坑 (2026-08-08)
- 训练节点生成 config_<policy>_runtime.yaml, root 写死 data/metaworld_peg (旧数据)
  + use_vae: true → 控制台自动训练产出无效模型
- 模型引擎远程容器化: 仅 gpu_mode=remote 且 remote_engine 已连才走 Docker,
  SSH 失败回退本地 (remote_engine=None)
- 启动训练前 grep config_act_runtime.yaml 的 root/use_vae 是否当前实验配置
