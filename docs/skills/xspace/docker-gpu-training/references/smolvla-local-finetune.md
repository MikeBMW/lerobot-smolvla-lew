# smolvla_lew 本地微调全链路 (gui-venv311 离线, 2026-09-09 实测)

4060 8GB 本机（gui-venv311, torch 2.7.1+cu128, transformers 5.16.1）直接训 smolvla_lew，
不依赖 docker。链路：扩数据 → 构建 LeRobot 图像数据集 → lerobot_train 微调 → resume →
from_pretrained 加载 → rollout 真实执行。全部坑实测排掉。

## 1. 训练依赖 (gui-venv311 需补)
```bash
gui-venv311/bin/python -m pip install termcolor draccus 'datasets<4' av accelerate diffusers
# diffusers 必装 (DiT TimestepEncoder require_package 报错); 国内 pip 直连失败用清华源 -i
```
注意: pip install -q 会静默失败 (无输出但没装上) → 逐个装 + `python -c "import x"` 验证。
`lerobot_train` 完整导入链还需 einops/pytorch_lightning/tensorboard/peft (`--no-deps` 逐个补)。

## 2. 训练数据源 (metaworld 真实帧)
`tools/gen_ss_metaworld_episode.py --seed N` (带视频, ~176帧/700步, 每4步渲染1帧 RENDER_EVERY=4)
产出 reports/ss_episode_<tag>.npz (39D state + u_exec 4D + obs43) + 同名 mp4。
左脑 MLP 数据 (ss_mw_lerobot_v4w 等) 是 **state-only 无图像** — smolvla 微调必须重新采带视频的。

## 3. LeRobot v3.0 图像数据集构建 (最容易踩的坑)
参照: data/smolvla_peg_img (8eps/2400帧 完整示例)。info.json features 结构照抄。
**铁律**:
- **data/chunk-000/file-000.parquet 绝不能有 videos/ 列** — CastError "Couldn't cast"!
  视频索引只在 meta/episodes/*.parquet (episode_index/length/videos.observation.image.chunk_index/
  frame_index/file_index/dataset_from_index/dataset_to_index/from/to_timestamp/data.chunk_index/
  data.file_index/tasks/meta.episodes.chunk_index/file_index)
- **meta/tasks.parquet 必须存在** (task_index+task 列) 否则 FileNotFoundError
- **meta/stats.json 必须含 mean/std/min/max** — 缺 min/max 报 "MIN_MAX normalization mode
  requires min and max stats"。action 训练归一化是 MIN_MAX (看 config normalization_mapping)。
  image 用 ImageNet 假值 [0.485,0.456,0.406]/[0.229,0.224,0.225], state/action 从 parquet 实算
- **时间戳按视频帧对齐** (最隐蔽的坑): 采集每 4 步才渲染 1 帧 → 数据行 timestamp 必须 =
  (frame_index//4)/fps, 不是 frame_index/fps! 否则 DataLoader worker 报 FrameTimestampError
  "query timestamps violate tolerance" (视频时长只有数据时间轴的 1/4)。
- mp4 每 episode 独立文件 (file-{ep_idx:03d}.mp4) + info video_path 模板
- 视频文件可用 `import av` 解码验证帧数; mp4 压缩后 176帧 480x480 ≈ 110KB 属正常

## 4. 数据集 repo_id 与离线
- config dataset.repo_id 填**本地路径** `data/xxx` 也会查 HF (offline 抛 OfflineModeIsEnabled)
  → 该 fork 的 LeRobotDatasetMetadata 只要 revision 非 None 就 get_safe_version 查 hub。
  解法: HF_HUB_OFFLINE=1 下 repo_id 用本地路径 + `huggingface_hub` monkeypatch
  list_repo_refs 返回空 _Refs (见 docs/skills/xspace/zmax-console/references/manifold-predictor-train-2026-09-09.md),
  或 utils.py get_safe_version 加本地兜底 `if version in ("main","local",""): return version`。
- 训练 config 结构: 顶层 batch_size/steps/num_workers/log_freq/eval_freq/save_freq/save_checkpoint/
  seed + optimizer(type: adam/lr/weight_decay) + wandb(enable:false)。不是 training: 子段。

## 5. 训练启动
```bash
cd /home/ubuntu/lerobot-smolvla-lew
env PYTHONPATH=$PWD/src HF_HUB_OFFLINE=1 gui-venv311/bin/python -u \
  -m lerobot.scripts.lerobot_train --config_path configs/policies/smolvla_lew/config_smolvla_lew_v8.yaml
```
- 首次训练 output_dir 会 FileExistsError → 换时间戳目录
- GPU 显存: SmolVLM2-500M 冻结 + DiT-B + LEW 6层 batch1 ≈ 2.4GB (4060 无压力), 1.3 step/s
- loss 观察: 3000 步 action_loss 0.92 → 10000 步 0.011 (真实收敛但裸 rollout 未学会闭环 — 见 §7)

## 6. Resume 续训 (3 个坑)
- config_path 必须指向 `outputs/train/<run>/checkpoints/<last_step>/pretrained_model/train_config.json`
  (不是启动 yaml!) — resume 分支 `parser.parse_arg("config_path")` 要真实存在的 train_config
- 命令行必须 `--config_path=路径` (=号) — parse_arg 只匹配 `--name=` 前缀, 空格分隔找不到
- train_config.json 里 resume 字段手动改 true + steps 改成目标步数; resume state 在
  checkpoints/<step>/training_state/ (optimizer/scheduler/rng/training_step)

## 7. from_pretrained + rollout (真实执行验证)
- checkpoint config.json 训练时**不写 policy type 键** → from_pretrained 解析报
  "Expected a dict with a 'type' key" → 手动 `d['type']='smolvla_lew'` 写入
- 必须用具体类: `SmolVLALewPolicy.from_pretrained(ckpt)` (PreTrainedPolicy 抽象类直接调报
  "Can't instantiate abstract class")
- **输出必须反归一化**: select_action 返回 MIN_MAX 归一化空间 → 需
  `make_pre_post_processors(policy_cfg=policy.config, pretrained_path=ckpt)` 的 post(out)。
  未反归一化动作幅度错 (±1 乱摆 vs ±0.1 伺服级) — rollout 距孔不动/乱晃先查这个!
- rollout 渲染: EGL 在 torch CUDA 同进程冲突 (EGL_NOT_INITIALIZED) → 用 MUJOCO_GL=glfw +
  DISPLAY=:0 (真机 X11), 或用 xvfb
- metaworld step 返回 5 元组 (obs, reward, term, trunc, info), trunc=True 后必须 reset
- **诚实预期**: 10000 步 action_loss 0.011 (训练分布准) ≠ 裸 rollout 插拔成功。训练数据是
  状态机专家轨迹, 无状态机引导的端到端裸 rollout 出分布 (covariate shift), gripper 不抓、
  距孔不收敛。要闭环成功需: 状态机引导 rollout 或更多轮训练。别拿 loss 冒充闭环成功。

## 8. 引擎 (RealStateSpaceSim) 直接驱动训练产物
- 引擎旁路 predictor 期望 `models/l4_mani_predictor_v1.pt` (裸 state_dict, 无元数据包装);
  加载日志 "🏆 L4 流形预测器 v1 已部署 ... trained=True" = 权重真加载
- JEPA 训练数据同构铁律: 引擎落 tr['z7_vec']/mani_* 字段, 训练脚本直接消费 tr 字段不重算
  (z7 可辨识性: 夹持后 x→光模块头 x+_grasp_off0+head_off, 否则 rem 不可辨识 28% 上限)
- 物理容差判据 (progress≤0.03/risk≤0.01/V≤0.01/eta≤0.05/rem≤15mm/dperp≤15mm) — 相对误差在
  真值≈0 维度必死; rem 分层 (深插<3cm/浅插/转移) 报段成功率才诚实
- v1 基线 (342K/200ep/16872帧): 帧级 16.4%, 插拔段 38.2%, 浅插 77.9%; 分维 rem 28% 最低
  (改进方向: 分维加权 rem/dperp/risk 3× + hidden 512/4层 + 多 seed 含失败轨迹)
