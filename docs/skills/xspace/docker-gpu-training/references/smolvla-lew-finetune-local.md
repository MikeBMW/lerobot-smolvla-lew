# smolvla_lew 微调 · 本地 GPU 直训 + LeRobot 图像数据集自建 (2026-09-09 v8 实测)

## 本地 4060 直训可行性
4060 8GB 直接 gui-venv311 训 smolvla_lew 可行: SmolVLM2-500M 冻结 (freeze_smolvlm: true)
→ 只训 DiT ActionHead + LEW 世界模型, 显存峰值 ~2.4GB, ~1.3 step/s (39 分钟/3000 步)。
无需等容器。HF 权重缓存完整时用 `HF_HUB_OFFLINE=1` 离线训。

## 本地直训依赖补装 (lerobot_train import 链逐个报, 一次装齐)
```
pip install termcolor draccus datasets av accelerate einops \
            pytorch_lightning tensorboard peft diffusers \
            -i https://pypi.tuna.tsinghua.edu.cn/simple
```
- diffusers 是 DiT ActionHead 必需 (报 "'diffusers' is required but not installed")
- 装完验证全导入: `python -c "from lerobot.scripts.lerobot_train import main"`

## LeRobot v3.0 图像数据集自建 5 铁律
踩过: CastError / FrameTimestampError / DatasetInfo missing features / stats 缺 min/max / tasks.parquet 缺

1. **data parquet 绝不含 video 列** — video 索引只在 `meta/episodes` parquet。
   每 episode 一行: episode_index, length,
   videos/observation.image/{chunk_index, frame_index, file_index, from_timestamp, to_timestamp},
   dataset_from_index, dataset_to_index, data/{chunk_index,file_index}, tasks,
   meta/episodes/{chunk_index,file_index}。video 帧放 videos/observation.image/chunk-000/file-NNN.mp4。
2. info.json 必须含 features 完整定义 (observation.image dtype=video + state/action 每维 shape/names)
   — 缺报 `DatasetInfo.__init__() missing 1 required positional argument: 'features'`。
3. `meta/stats.json` 必须预置 mean/std/**min/max** — MIN_MAX 归一化缺 min/max 报
   "MIN_MAX normalization mode requires min and max stats"。image 用 ImageNet 值。
4. `meta/tasks.parquet` 必须有 (task_index int64 / task str) — 缺报 FileNotFoundError。
5. **视频时间戳对齐 (最容易漏)**: 采集脚本每 RENDER_EVERY=4 步渲染 1 帧写 mp4 →
   data parquet 每行 timestamp 必须 = `(frame_index//4)/fps`, 不是 `frame_index/fps`!
   否则数据时间轴是视频的 4 倍 → DataLoader 报
   `FrameTimestampError: query timestamps violate tolerance`。

## resume 续训 3 坑
报错特征: "A config_path is expected when resuming a run. Please specify path to train_config.json"
1. `--config_path` 必须指向
   `outputs/train/<run>/checkpoints/<最后步数>/pretrained_model/train_config.json` (不是 yaml!)
2. 该 train_config.json 里 resume 手动改 true (训练存档时是 false; FileExistsError 即此因)
3. CLI 必须 `--config_path=<路径>` 带等号 — parser.parse_arg 只认 `--x=` 前缀, 空格分隔查不到
   (draccus 消费掉 config_path 后 validate() 重新 parse sys.argv 找不到)

resume state 在 checkpoints/<步数>/training_state/ (optimizer/scheduler/rng/training_step)。

## checkpoint 加载 + rollout
- config.json 无 type 键 → 必须用具体类:
  `SmolVLALewPolicy.from_pretrained(ckpt)` — PreTrainedPolicy 抽象类会
  TypeError "Can't instantiate abstract class with abstract methods select_action..."
- select_action 输出**归一化空间** → 必须反归一化才能送 env:
  `from lerobot.policies import make_pre_post_processors`
  `pre, post = make_pre_post_processors(policy_cfg=policy.config, pretrained_path=ckpt)`
  `act = post(act)` — 否则动作量级全错 (训练 action MIN_MAX ±0.34, 裸输出 -1~1 乱晃)
- rollout 不收敛 ≠ 模型没训好: v8 实测 loss 0.507→0.229 (action_loss 0.011) 但裸 rollout
  距孔不动 → covariate shift (训练=状态机分段专家轨迹, 裸 roll 无阶段引导出分布)。
  验证闭环要状态机引导 rollout (VLM 每帧出动作 + 状态机管阶段切换) 或 2-3 万步更久;
  **单看 loss 曲线不能证明闭环成功**。

## 采集产物格式 (gen_ss_metaworld_episode.py)
- npz 的 obs 是 43D 状态 (非图像帧); 渲染帧只进 mp4 (每 RENDER_EVERY=4 步 1 帧, rot90 朝向)
- npz 含 x/peg/stage/done/u_* 全向量 + meta (seed/success/孔口现场几何)
- 数据集构建时从 mp4 抽帧 + npz 数值对齐 (见"5 铁律"第 5 条)
