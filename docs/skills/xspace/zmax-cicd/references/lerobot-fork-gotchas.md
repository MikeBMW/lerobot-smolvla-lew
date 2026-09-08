# lerobot-smolvla-lew fork 训练/评估坑 (v0.5.2-zmax)

## draccus 配置 (config_act_*.yaml)
- CLI 参数是 **`--config_path`** (下划线)，不是 `--config-path` — 用后者报 unrecognized arguments
- 顶层字段看 `TrainPipelineConfig`：`dataset`(dict 含 repo_id/root/episodes)、`output_dir`、`job_name`、`batch_size`、`steps`(不是 num_epochs)、`optimizer`(dict: type/lr/weight_decay)、`scheduler`、`wandb`、`eval`
- **没有** `dataset_repo_id`/`training`/`learning_rate`/`offline`/`device` 顶层字段 — draccus 报 "fields not valid for TrainPipelineConfig"
- `repo_id` 必须放在 `policy:` 下并配 `push_to_hub: false`，放顶层会报错；缺 repo_id 时 validate 报 "'repo_id' argument missing"
- ACT 无 `num_inference_timesteps` 字段 (那是 smolvla 的)；无 `n_obs_steps>1` 支持 — **`n_obs_steps: 2` 报 "Multiple observation steps not handled yet"**，必须 1
- 训练命令: `PYTHONPATH=src .venv/bin/python -m lerobot.scripts.lerobot_train --config_path <cfg>.yaml`
- 输出目录已存在且 resume=false 报 FileExistsError → 先 `rm -rf outputs/train/<dir>`

## 环境安装
- `uv sync --python 3.12` (系统 python3.14 无 torch 兼容)；需 `--extra dataset --extra training`
- UV 官方源(Fastly)极慢(84MB 模型场景下 10s 零增长) → `export UV_DEFAULT_INDEX/UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/`；但阿里云缺 num2words → 解析失败。策略：官方源 + 大缓存重试，或 `--no-default-groups` 先装核心再补 extra
- nvidia-cuda-cupti 解压 I/O 错误是瞬时故障，重试即可

## ACT 推理/评估
- `select_action(batch)` 接收 **dict**：`{"observation.state": tensor}`，裸 tensor 报 "dictionary update sequence element" 错；有图则加 `"observation.image"`
- 模型 config 加载后 `image_features` 是 dict (即使 json 里是 None) — 有图模型必须喂图
- **必须反归一化**：`policy.select_action(batch)` 输出归一化动作，直接用会 MSE ~78000 失真；用 `from lerobot.policies import make_pre_post_processors; pre, post = make_pre_post_processors(policy_cfg=policy.config, pretrained_path=str(ckpt)); out = post(policy.select_action(batch))`，反归一化后 MSE 正常
- ACTPolicy 在 `lerobot.policies.act.modeling_act` (不是 policy_act)
- LeRobotDataset 加载无图 parquet 时会**自动生成 observation.image** (0-1 float 96x96) — 与训练管道一致，评估用它而非裸 parquet
- parquet 直读时 `observation.image` 列是 dict `{"bytes": png字节}`，需 `row.get("bytes")` 再 PIL 解码

## 数据集对比要点
- **公平对比必须同数据同特征维度**：metaworld_act (2D state/action, 25650帧) ≠ metaworld_mt50 (4D, 480x480 图) — 维度不匹配报 mat1/mat2 shape 错误，MSE 无意义
- 基线 checkpoint: `outputs/train/act_metaworld/checkpoints/000300/pretrained_model` (300步 21.9M)
- 提升路径实测: 300步→2000步 MSE 12038→11155 (-7.3%) → 3000步+lr8e-5 → 11053 (-8.2%)

## 自动迭代 (tools/auto_iterate.py)
- 改进配置改 `steps` 必须 `re.sub(r"^steps: \d+", ..., flags=re.M)` — 无行首锚点会误匹配 `n_obs_steps`/`n_action_steps` 导致 chunk_size 校验失败
- compare() 从 `--report` 同名 .json 读结果；act_compare.py 的 JSON 输出路径必须与 HTML 同根 (`.with_suffix(".json")`)，否则 auto_iterate 读到旧文件
- 阈值 5.0%，达标才部署+版本号；未达标自动 steps+1000 / lr×0.8 重训

## 报告
- `tools/gen_cicd_report.py` 生成 HTML 报告；release 用 GitHub API (无 gh CLI)：`POST /repos/{owner}/{repo}/releases` + `POST /uploads/.../assets`，token 从 ~/.git-credentials 正则提取
