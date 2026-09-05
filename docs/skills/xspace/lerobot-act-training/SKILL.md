---
name: lerobot-act-training
description: Use when training ACT policies in lerobot-smolvla-lew fork.
---

# LeRobot ACT Training (lerobot-smolvla-lew fork)

Train ACT policies on the local GPU (RTX 4060, 8GB) for the Z-MAX closed-loop pipeline.

## Environment setup
- Python 3.12 required: `uv python install 3.12 && uv sync --python 3.12`
- Training needs extras: `uv sync --python 3.12 --extra dataset --extra training`
- Slow default CDN: retry, or try a mirror BUT mirrors can miss packages (aliyun lacks num2words) — fall back to official PyPI; cached downloads make retries fast.
- nvidia CUDA wheel extraction I/O errors are transient — just rerun `uv sync`.
- Verify: `.venv/bin/python -c "import torch; print(torch.__version__, torch.cuda.is_available())"` (expect 2.11.0+cu128)

## Training entrypoint (this fork)
```bash
PYTHONPATH=src .venv/bin/python -m lerobot.scripts.lerobot_train --config_path <file>.yaml
```
- `--config_path` with UNDERSCORE (NOT `--config-path`) — the draccus wrapper in `src/lerobot/configs/parser.py` reads it.
- lerobot version 0.5.2.

## draccus config format (TrainPipelineConfig)
Decoding errors look like `draccus.utils.DecodingError: The fields X are not valid for TrainPipelineConfig` — fix by matching fields exactly:

| Wrong | Right |
|---|---|
| top-level `dataset_repo_id` | `dataset: {repo_id, root, episodes}` |
| `training: {num_epochs}` | top-level `steps: 1000` (no num_epochs) |
| top-level `learning_rate` | `optimizer: {type: adam, lr: 1e-4}` |
| top-level `repo_id` | inside `policy: {repo_id, push_to_hub: false}` |
| `device: cuda` / `offline` | not top-level fields — omit |
| `num_inference_timesteps` (ACT) | ACT has NO such field — remove |

- ACT constraint: `n_obs_steps` MUST be 1 (`Multiple observation steps not handled yet. Got nobs_steps=2`).
- Valid ACT fields: n_obs_steps, n_action_steps, chunk_size, dim_model, dim_feedforward, n_heads, n_encoder_layers, n_decoder_layers, use_vae, latent_dim.

## Output & deploy
- Checkpoints: `outputs/train/<job>/checkpoints/<step>/pretrained_model/` (model.safetensors ~84MB).
- Deploy chain: push model via relay POST /upload → peer pulls GET /latest (POP — save immediately!) → deploy to edge device. Full relay ops (nginx 反代 / 弹栈队列 / 流式上传防OOM / JSON-vs-二进制判定 / WS心跳 / 部署脚本清单): `references/zmax-relay-deploy.md`.

## Pitfalls
- `outputs/train/<job>` must NOT exist when resume=false — delete it or change output_dir (`FileExistsError`).
- `'repo_id' argument missing` fires even with push_to_hub false — set `policy.repo_id` anyway.
- Throughput on 4060: 13-18 step/s → 1000 steps ≈ 76s. Fast enough to iterate.

## Dataset pipeline — npz → LeRobotDataset v3.0 (2026-08-02 治本)
**重大陷阱**: 若数据目录的 `meta/` 是从别的数据集拷贝的 (如 pusht 模板), `LeRobotDataset("lerobot/pusht", root=<dir>)` 会按 meta 的 features 读数据 — 训练出的模型 input_features 是模板的 (2D state/96×96/25650帧), **本地 npz 真实数据 (metaworld 4D / Orin 7D) 从未接入 = 假训练**。判别: 训练后 `config.json` 的 `input_features` shape 必须等于真实数据维度; 两个不同目录若 `meta/info.json` 相同即假。

修复工具: `tools/npz_to_lerobot.py --npz <x>.npz --out <dir> --task "名" --fps 30 --episode-frames 100` (npz 无 episode 边界, 按固定帧数切)。实测: metaworld 696帧→7ep/4D state/128², closed_loop 300帧→3ep/7D state/64²。

**v3.0 格式要点 (全部实测踩过)**:
- `meta/info.json` 的 `features` 决定模型 input_features: state `{"shape": [N]}`、图像 `{"shape": [H,W,3]}` (HWC)、dtype `video`。
- 帧数据 `data/chunk-000/file-000.parquet`: `observation.state`/`action` 用 `pa.list_(float32, dim)` (fixed_size_list) + episode_index/frame_index/timestamp/next.*/index/task_index。
- **视频必须 PyAV h264** (`av.open` + `add_stream("h264")`): cv2 的 mp4v 无关键帧索引, LeRobotDataset 解码报 `Invalid frame index=N for streamIndex=0; must be less than M`。图像 CHW float(0-1) → HWC uint8(×255) 再写。
- **所有 episode 共用一个视频文件** (`videos/observation.image/chunk-000/file-000.mp4` 含全部帧), episodes 表每行的 `videos/.../file_index=0`、`from/to_timestamp` **全局累计**。若每 episode 单独文件+文件内 timestamp → 越界。
- `meta/episodes/*.parquet` 每 episode 一行: 文件定位 + `length` + 每特征 `stats/<feature>/{min,max,mean,std,count}` (归一化统计来源); `tasks` 列类型 `pa.list_(pa.string())` (不是 string)。
- **episodes parquet 的完整必需列 (全踩过, 缺一即挂)**: `episode_index, length, data/chunk_index, data/file_index, dataset_from_index, dataset_to_index, videos/observation.image/chunk_index, videos/observation.image/file_index, videos/observation.image/from_timestamp, videos/observation.image/to_timestamp, tasks, meta/episodes/chunk_index, meta/episodes/file_index`。缺 `videos/.../chunk_index` → `KeyError: 'videos/observation.image/chunk_index'`; 缺 `.../file_index` → 同样 KeyError; 缺 `dataset_from_index` → `ValueError: Column 'dataset_from_index' doesn't exist`。
- **dataset_from/to_index 必须全局递增**: ep0=0..149, ep1=150..299 (每轨迹 length 连续累加), 不是每轨迹从 0 开始 — 否则 `Invalid key: 6909 is out of bounds for size 1200`。
- **frame_index 是轨迹内索引 (0..149)** 而非全局计数 — episodes 的 from/to 才承担全局定位。
- **episodes 的 `videos/.../from_timestamp`/`to_timestamp` 也要填** (0 和 (length-1)/fps), 否则视频帧寻址越界。
- 视频文件命名必须是 `file-000.mp4` (单一文件含全部轨迹帧), 不是 `episode_000000.mp4` 逐轨迹 — fork 的 `get_video_file_path` 按 `file-{file_index:03d}.mp4` 拼路径, 逐轨迹命名会 `IsADirectoryError: Is a directory: .../chunk-000`。多轨迹合并: `ffmpeg -f concat -safe 0 -i list.txt -c copy file-000.mp4` + 写 `file-000.mp4.metadata` (每行一个帧号)。
- **parquet 的 state/action 列必须 float32**: pandas 默认 float64 → `Couldn't cast array of type list<element: double> to List(Value('float32'), length=7)`。修法: `df[col] = df[col].apply(lambda v: np.asarray(v, dtype=np.float32))` 或写 parquet 前显式 cast。
- **改了 info.json 维度后必须清 datasets 缓存**: `rm -rf ~/.cache/huggingface/datasets ~/.cache/huggingface/hub`, 否则旧 features (如 2D state) 被缓存复用 → `List(Value('float32'), length=2)` 与 7D 数据不匹配。repo_id 相同也会复用旧 schema (metaworld_act 的 2D 污染过 joint_real)。
- **repo_id='lerobot/pusht' 的 schema 污染是持久的**: 即使用 `local/cartesian-v3` 这类本地 repo_id + root 指向本地目录, 缓存里残留的 pusht schema 仍会让 `Couldn't cast fixed_size_list[3] to List(float32, length=2)`。**换全新 repo_id 必须同时清缓存**, 且 repo_id 只影响 datasets 缓存命名 — 本地 root 的 info.json 才决定真实 schema。
- **本地 root 会被 snapshot_download 覆盖 (2026-08-02 根因级, 反复出现 "info.json 又变回 25650帧/state[2]" 的元凶)**: `LeRobotDataset(repo_id, root=本地目录)` 和 `LeRobotDatasetMetadata(repo_id, root=...)` 在 root 非 None 时仍调用 `snapshot_download(local_dir=root)` — 把 hub 上的 pusht 数据集**整个写进本地目录** (出现 `.cache/` `.gitattributes` `README.md`, 且 `meta/info.json` 被替换成模板 2D/25650帧)。于是 build 出来的正确 info.json 在实例化/训练加载时被静默覆盖 → 之后所有 cast 错误、维度错误都是假象。**修法 (本 fork 已打补丁)**: 在 `src/lerobot/datasets/lerobot_dataset.py` 的 `_download()` 与 `src/lerobot/datasets/dataset_metadata.py` 的 `_fetch` 里, `snapshot_download` 之前先判 `(root/"meta"/"info.json").exists()` → 存在即 `self.root = root` 直接 return, 跳过 hub 下载。**新环境/新 fork 拉下来后必须重新打这个补丁**, 否则本地数据集加载全部被污染。
- **"because column names don't match" CastError = info.json features 缺列**: parquet 有 `index`/`task_index` 列但 info.json features 没声明 → datasets cast 失败报 column names don't match (不是缺数据)。修法: features 补 `"index": {"dtype": "int64", "shape": [1]}` + `"task_index"` 同构。
- **episodes parquet 可能残留旧模板数据**: 生成器只 `df = pd.DataFrame(all_eps)` 写 episode_index/length, 若 meta/episodes 目录没清干净或生成脚本没重建, 会残留旧数据集的 206 条轨迹/25650 帧 → `IndexError: Invalid key: 6909 is out of bounds for size 500`。修法: 从主 parquet `groupby('episode_index')` 重建 episodes, 并重算 `dataset_from/to_index` 全局累加。
- **IDLE 过滤后 episode_index 必须连续重编号 (2026-08-02 实测)**: build 脚本跳过 IDLE 包后, 若仍用原始包索引 si 当 episode_index (0,1,...16,17 缺 15), LeRobot 用**位置索引**查 `episodes[ep_idx]` → 数据里 episode 15 无帧 → `Invalid key: 24 is out of bounds for size 24`。修法: 引入连续计数器 `ep_idx`, 数据帧 `episode_index=ep_idx` + 非空包后 `ep_idx+=1`, episodes 表 `eps["episode_index"]=range(len(eps))`。判别: `sorted(df['episode_index'].unique()) == list(range(len(eps)))` 必须为 True。
- **episodes 的定位列必须是 int64 不能是 float**: pandas 赋值 0/0.0 可能成 float → `ValueError: Unknown format code 'd' for object of type 'float'` (video_path.format 用 {:03d})。修法: `eps[c] = eps[c].astype('int64')` (dataset_from_index, dataset_to_index, data/chunk_index, data/file_index, videos/.../chunk_index, videos/.../file_index, meta/episodes/chunk_index, meta/episodes/file_index)。
- **stats.json 维度必须匹配 state**: 旧 stats 的 mean (2D) 与新 state (3D) 不匹配 → normalize 报 `RuntimeError: The size of tensor a (3) must match the size of tensor b (2) at non-singleton dimension 1`。修法: 重写 stats.json (`states.mean(axis=0).tolist()`), 同时确认 `ds.meta.stats['observation.state']['mean']` 长度正确。
- **use_imagenet_stats: true 需要 stats.json 有 image 统计**: 缺 `observation.image` 键 → `KeyError: 'observation.image'`。生成数据不写图像统计时设 `use_imagenet_stats: false`。
- `meta/stats.json` 帧级全局统计; `meta/tasks.parquet` 任务表。
- **评估必须走 LeRobotDataset 加载** (meta 对齐 state 维/图像尺寸), 直读 npz 数组会与模型 input_features 不匹配 (模型 2D vs npz 4D → `mat1 and mat2 shapes cannot be multiplied (1x4 and 2x256)`)。转换后 `ds[i]` 返回的 state/image 维度应等于真实数据。

## Config generation pitfalls (cicd_pipeline 实测补充)
- **YAML 浮点陷阱**: yaml 把无小数点的 `1e-05` 解析为 **str** → draccus 类型错误。所有浮点插值必须保证带小数点: `_f(x) = f"{float(x):.6f}".rstrip('0').rstrip('.')` + 无小数点补 `.0`。
- **re.sub 行锚定**: 改写 YAML 一律 `(?m)^steps:` / `(?m)^(\s*)root:` (行锚定), 否则 `steps:` 会先匹配到更靠前的 `n_obs_steps:` (它含子串 "steps: 1") — 顶层 steps 反而不被替换。
- **temporal_ensemble 约束**: ACTConfig 校验 `n_action_steps must be 1 when using temporal ensembling` (每步查询才能集成)。用户策略的 n_action_steps=50 + ensemble=0.01 互斥 → 开 ensemble 时 n_action=1。
- 预训练初始化微调 (2026-08-02 修正, 三处全踩过): CLI 传 **`--policy.path=<ckpt_dir>` 必须等号形式** — 空格形式报 `unrecognized arguments: --policy.path`; `--policy <dir>` 报 `Expected a dict for a choice class`; **YAML 写 policy.path 会崩** (`The fields path are not valid for ACTConfig`, ACTConfig 无 path 字段)。正确: `lerobot_train --config_path <cfg> --policy.path=<ckpt_dir>`。维度不同 (如 4D→7D) 时权重加载失败 → 自动降级从零训练 (日志标注)。
- **微调续训 = 唯一可靠的\"接着训\"模式 (2026-08-07 实测, draccus resume 机制是坏的)**: `resume: true` + output_dir 指向已有目录会崩 `ValueError: A config_path is expected when resuming a run. Please specify path to train.yaml` — draccus resume 分支期望 config_path 指向**配置目录结构** (TRAIN_CONFIG_NAME), 单 yaml 文件不行, 别折腾 resume。**续训 = 预训练微调**: 新时间戳 output_dir + steps=目标总步数 + `--policy.path=<旧dir>/checkpoints/<最大步数>/pretrained_model` (用 `ls | grep -E '^[0-9]+$' | sort -n | tail -1` 取最大步数, 别写死 last)。曲线合并: 新训练 step 从 0 起 → **step 偏移 +1000** (旧 1000 步起点) 再 `setdefault` 合并旧曲线 + sorted; 训练后**必须 grep 日志** (`FileExistsError|Traceback|Error:`) 失败则不合并曲线 (否则旧曲线被覆盖成未变数据, 脚本\"看似成功\"实际没训)。已验证: act 1000→4000 步续训 loss 1.989 继续下降, 合并曲线 400 点 (5..2000)
- **训练曲线 json 是易失资产 (2026-08-07 二次踩)**: GUI 重启时 auto_run 触发的训练链启动会**清空/覆盖** `reports/train_curve_*.json` (训练中途 kill 后残留 act 50 点、其余 0 点)。教训: auto_run 默认不训练 (ZMAX_AUTO_TRAIN=1 才触发), 且曲线文件要视为可重建资产。**恢复途径: 从训练日志秒级恢复** — `/tmp/*.log` 里的 lerobot 日志 `INFO ... step:990 ... loss:1.818` (冒号格式!), 正则 `step[:=]?\s*(\d+)\b.*?loss[=:\s]+([\d.eE+-]+)` 解析 (vla/awe 独立脚本是 `action_loss:xxx` 每 5 步一行)。**`step:1K` = 1000 步的显示 (K 后缀) — 解析前先 `re.sub(r"step:(\d+)K\b", lambda m: f"step:{int(m.group(1))}000", log)` 展开, 且必须展开全部 K (1K→1000 … 4K→4000)**: 只硬编码替换 1K 的实现在 4000 步续训时曲线**停在 1995** (step:2K/3K/4K 未匹配, 表现=\"训练显示 4000 步但曲线只到 1995\", checkpoint 目录却是 004000 完整的 — 先查 ckpt 目录再断定训练没跑满); 解析后去重 + sorted (同 step 新覆盖旧)。修复的判定: 曲线尾点 step 必须递增且 == 配置步数 (995/1000) 或偏移后总步数 (微调续训 4000 步 → 5000)。**曲线 json 的 `ts` 字段必须写真实训练完成时间, 不能写\"当前时间\"**: 若写成现在时间 (比视频帧 mtime 新), GUI 的 `_check_newer_ckpt` (simulink_scope.py) 判定\"有新 checkpoint\" → **每次打开视频对话框都触发 7 模型重新生成 → 白屏**。修复: 曲线修正后 ts 回填真实训练时刻 (如 20260807_161840), 或重新 rollout 让视频帧更新。
- 微调学习率会毁掉基础权重 (2026-08-02 实测): 从基础模型 (act_metaworld 300步) 继续训练用 **lr=5e-5 → MSE 从 12037 恶化到 13052 (-8.43%, 过拟合/破坏基础权重)**; 同配置 **lr=1e-5 → 保护基础权重**。微调一律用低 lr (1e-5 起步), 不要沿用从头训练的 1e-4。判别是否真微调: 对比同数据下 MSE 必须 < 基础模型, 否则降 lr 重训。

## MetaWorld joint 观测采集 (tools/collect_metaworld_joint.py, 2026-08-02)
metaworld 默认观测是**任务空间**不是关节空间 (obs_type=plain → 末端 xyz+夹爪 4D; with_goal → 8D)。要关节角必须自己从 MuJoCo 读 `env.data.qpos`。

**与 Orin 维度对齐的采集方案 (Sawyer 7轴, 产线 珞石 6关节)**:
- **最终对齐 = 6D (2026-08-02 实测修正)**: state = `qpos[0:6]` 前6关节角 (**不加夹爪维度**) → 6D (对齐 Orin `n_joint=6`)。最初方案加夹爪归一化距离成 7D (对齐 Orin 7D), 但实测 Orin 真机是 **6 关节无夹爪维度** (relay 包 meta `n_joint=6`), 7D 模型微调迁移失败 `mat1 and mat2 shapes cannot be multiplied (8x6 and 7x256)` → **统一 6D 后 Stage3 权重迁移成功** (从预训练起点 loss 3.17 起步训练, 不再降级从零)。7D 方案废弃。
- action = 关节速度差分 `qpos[0:6]` 逐帧差 → **6D** (对齐 Orin 6D) — metaworld 3.x 无 joint action 模式 (默认 4D 末端控制), 只能记录差分作为动作
- image = `mujoco.Renderer(env.model, 64, 64)` offscreen (WSL headless 可用) → 64² 对齐 Orin
- 判别对齐是否成功: Stage1 模型 `input_features.state` shape 必须 == Orin 数据 state 维度 (6), 且 Stage3 训练日志无 \"权重迁移失败 → 降级\"。维度检查顺序: 先看 relay 包 `meta.n_joint` (真机定义), 别假设 Orin 是 7D。

**metaworld 3.1.1 API 坑 (全部实测)**:
- `MT1('reach-v3')` — v2 任务名报 `is not a V3 environment`; 用 v3 后缀
- 必须先 `env.set_task(mt.train_tasks[0])` 再 reset, 否则 `AssertionError: _last_rand_vec is None`
- Gymnasium API: `obs, info = env.reset()`, `obs, rew, term, trunc, info = env.step(a)`
- `env.data.qpos` 是 16D (Sawyer 7 关节 + 物体/夹爪等), **前 7 才是关节角**
- 夹爪 body 名: `rightclaw` / `leftclaw`
- 装包: venv 无 pip 时 `.venv/bin/python -m ensurepip` 再 `python -m pip install metaworld` (uv 可能不在 PATH)

产出: `data/metaworld_joint6_v2` (6D/6D/64²) 与 `data/orin_real_v1` (Orin 真实 6D/6D/64², action 恒等已修复) **完全同维度** → Stage2 Sim2Real 真正跑通。**6D 统一后实测 (21:51, 21帧真实数据)**: 仿真验证 MSE=0.0000 成功率100%, **Sim2Real MSE=0.0355 成功率 90.5% 零样本直接可用** (不再是 7D 时代的 0.0884/0% 需微调 — 6D 关节空间统一是 Sim2Real 有效的前提)。Stage3 权重迁移成功 (不再降级, 实测 loss 3.17→1.618 从预训练起点)。三阶段管线 Stage1/2/3 全部切 6D: S1=joint6_v2、S2=orin_real_v1、S3=orin_real_v1。**维度以真机 relay 包 meta (n_joint) 为准, 不要假设**。

## MetaWorld 数据自生成 (MuJoCo 渲染, 2026-08-02 老倪"你得自己生成啊"实测)
mujoco 3.3.0 + metaworld 已装 venv (两者都已 import 可用)。**WSL 无头渲染三连坑**:
- **`DISPLAY=:0 MUJOCO_GL=glfw` 是唯一可行组合** (WSLg X server 在 /tmp/.X11-unix/X0)。EGL 报 `EGLError: <exception str() failed>` (无 GPU 上下文); osmesa 缺 libosmesa 报 `AttributeError: 'NoneType' object has no attribute 'glGetError'`; 原生 `mujoco.Renderer` 报 "an OpenGL platform library has not been loaded"。先 `echo $DISPLAY` / `ls /tmp/.X11-unix/` 确认 X0 存在再 glfw。
- **execute_code 沙箱无 DISPLAY (2026-08-02 实测)**: 在 execute_code 里 subprocess 跑 metaworld 采集/渲染, 环境变量缺 DISPLAY → `GLFWError: (65550) X11: The DISPLAY environment variable is missing` → 采集 rc=1。修法: `subprocess.run(..., env=dict(os.environ, DISPLAY=":0", MUJOCO_GL="egl"))` 显式传 env (terminal 工具有 DISPLAY=:0, execute_code 没有)。验证脚本同理。
- `env.render()` 必须 `metaworld.MT1('reach-v3')` 建 env 时 `render_mode='rgb_array'`, 否则 `AttributeError: Unexpected mode: None, expected modes: human, rgb_array, ...`。
- **metaworld reach-v3 的 action 是 4D** (`dx,dy,dz,gripper`), 不是 6D! `AssertionError: Actions should be size 4, got 6`。旧数据 action=6D 是 padding 出来的假维, 别沿用。
- 专家启发式: 朝 goal site 移动 `env.data.site_xpos[env.model.site("goal").id]` — **用 `env.model.site("name").id` 取对象, `site_names` 不是 model 属性** (`AttributeError: 'MjModel' object has no attribute 'site_names'`)。
- 关节角 = `env.data.qpos[:7]` (16D qpos 前 7 才是 Sawyer 关节)。
- 生成脚本: `tools/gen_metaworld_data.py --eps 8 --steps 150` → `data/metaworld_joint_real` (1200帧/8轨迹/state7D/action4D/128² 真实图 var≈4300)。**生成后必须验证图像方差** (见下节黑图陷阱)。

## 数据质量检查 (黑图陷阱, 2026-08-02 重大)
**"模型输出全是 0 / MSE≈0 / 成功率100%" 的第一嫌疑是图像数据是黑图或占位图, 不是模型问题**。metaworld_joint_v2 旧数据 observations 全 0 (var=0.0) → ACT 视觉编码器 (ResNet) 从黑图学不到特征 → 输出趋零 → 假评估通过。
- 检查法: 加载数据集采样帧 `img.var()` — 真实渲染 var≈4000+, 黑图/占位图 var≈0-0.1。视频文件用 PyAV 直接解帧 `f.to_ndarray(format='rgb24').var()` 对比 LeRobotDataset 解码值, 可区分"数据黑"还是"解码 bug"。
- **现有基线 metaworld_act 的图像也是灰占位 (var=0.0, range 0.25→1.0) — 之前所有视觉训练都在占位图上**。真实渲染数据 (var=4327) 训练 loss 1.223 vs 黑图数据 loss 2.052 — 图像质量是决定性因素。
- 数据生成时每轨迹渲染后立即检查唯一色数/方差, 否则会产出"结构正常但全黑"的数据 (180帧/3轨迹/7D 看着齐全, 实际不可训)。
- **采集数据图像是 64x64 缩略图 vs 快照流 318x180 高清 (2026-08-02 老倪"看不清楚"实测)**: 小芳采集包 (camera_b64) 解码后只有 **64x64**, 而 ECS 归档快照 / 实时画面 (cicd.html) 是 **318x180** (像素差 25 倍)。所以"保存的原始图像"模糊、实时画面清晰是正常的 — 不是提取/保存出错。检查原始图像去 ECS 归档: `ls -t /root/zmax-relay/archive/snap_*.jpg` 提取 (318x180), 不要用采集包的 camera_b64。**训练数据也是 64x64** → 想让 ACT 视觉编码器吃高清帧, 需小芳采集时存高清 (≥318x180) 或用快照流接入训练数据; 64x64 图训练 = 视觉信息量低 (虽比黑图好, 但远不如 318x180)。

## 跨机器人泛化: 笛卡尔任务空间 (7轴→6轴, 2026-08-02 老倪\"泛化到六轴珞石可以么\"实测)
**关节角维度对齐 (joint-space) 只在机器人 DOF 相同时可行; 机器人与人不同 (Sawyer 7轴 vs 珞石 SR5 6轴) 时用任务空间 (cartesian) 泛化** — 让模型学\"任务\"而不是\"机器人\":

```
训练 (metaworld Sawyer 7轴):         部署 (珞石 SR5 6轴):
  输入: 图像 + 末端3D位置(x,y,z)  →    输入: 图像 + TCP位姿(x,y,z) ✅ 通用
  输出: 末端速度(dx,dy,dz+gripper) →  输出: 末端速度 ✅ 通用
                                       ↓
                                 珞石控制器内部 IK → 6D关节指令 (无需改模型)
```
- 关键: state 用**末端笛卡尔位姿** (`env.data.site_xpos[env.model.site("endEffector").id]`, 3D), 不用 qpos 关节角 (7D≠6D 无法迁移)。
- action 保持 metaworld 原生 4D 末端速度 (dx,dy,dz+gripper) — 之前 pad 成 6D 是假维, 别沿用。
- 前提确认: 目标机器人控制器支持笛卡尔控制 (珞石 `/robot/tcp_pose` + 内部 IK) — 部署前先让小芳确认控制器接口类型, 4D 笛卡尔 or 7D 关节决定模型维度。
- 数据生成器: `tools/gen_metaworld_data.py --eps 10 --steps 150` 改 state=末端3D → `data/metaworld_cartesian` (1500帧/10轨迹/state3D/action4D/真实图)。
- 实测: 2000步 loss 1.555, 模型 state[3]/action[4]。

## Orin 真机数据 → LeRobot 数据集 (tools/build_orin6d_dataset.py, 2026-08-02)
**实机确认 (小芳实测)**: Orin 上这台是**珞石 SR5 6 关节** (joint_1~6, `/sim_joint_trajectory` 收关节角轨迹, `/robot/tcp_pose` 有笛卡尔位姿), **不是 7 电机** — 老倪说的"7电机"是误解。所以:
- 关节空间模型 = **state 6D / action 6D** (真机数据维度)
- 笛卡尔模型 = state 3D (TCP位置) / action 4D (末端速度) — 见上节
- metaworld 7D 关节模型与 6 关节实机**直接部署不匹配** (维度错), 除非走笛卡尔接口。

小芳上传的 orin 数据包 (`data/orin_live/*.json`): `{meta: {n_joint, n_action, frames, labels}, frames: [{observation.state, action, label, camera_b64}]}` — 6D state/action + base64 图像。`build_orin6d_dataset.py` 转 LeRobot:
- 帧数据必须含 `next.reward/done/success` 列 (漏了 → `KeyError: 'next.reward'`)。
- 图像 base64 → jpg → **合并成 file-000.mp4** (ffmpeg 序列图 → libx264), 否则 info 声明 video 但目录只有 jpg → `FileNotFoundError: .../file-000.mp4` 训练直接崩。
- 真机帧的 timestamp/frame_index/episode_index 可能全是 None (小芳采集只填 state/action/label/camera_b64) → 训练时 `unsupported operand type(s) for /: 'str' and 'str'` (delta_timestamps 用 None 计算)。修法: build 脚本 `float(fr.get("timestamp") if fr.get("timestamp") is not None else i/30.0)`, episode/frame index 同理 `int(fr.get(...) or si/i)`。**重建后验证 `df['timestamp'].isna().sum()==0`**。
- **只保留有有效图像的帧 (2026-08-02 实测)**: 真机包常是"40帧中只有部分带 camera_b64" — 若把无图帧也写进 parquet, mp4 帧数 < parquet 帧数 → torchcodec 解码报 `FrameTimestampError` (query timestamp 超出 loaded 范围)。修法: base64 解码后 `Image.open(...).verify()` 验证, 无有效图 `continue` 跳过该帧 — **parquet 帧数 == mp4 帧数必须严格一致**。
- **视频帧时间戳精度陷阱 (FrameTimestampError: queried timestamps vs loaded timestamps, 2026-08-02 最新)**:
  - 症状: 训练 0% 即崩, 日志 `queried timestamps: tensor([11.3133])` vs `loaded timestamps: tensor([11.3000])` + `video: .../file-000.mp4` — 相差 > tolerance (默认 1e-4)。
  - 根因: parquet 存 `float32(i/30.0)` 与 ffmpeg 非精确 CFR 的 pts 量化 (11.3000) 微小错位, 严格容差下找不到对应帧。
  - 修法: ffmpeg 合并加 **`-vsync 0 -fps_mode passthrough`** (逐帧透传, 保留全部帧) — **不要用 `-vsync cfr -r 30 -fps_mode cfr`**: 该组合在实测中会**丢一帧** (515 张 jpg → 514 帧 mp4, 因末帧量化/截断), 而 parquet 仍是 515 行 → 训练报 `Invalid frame index=536 ... must be less than 515`, 症状与旧缓存幽灵一模一样但清缓存无效。**合并后必须验证 mp4 帧数 == parquet 行数**: `ffprobe -v error -count_frames -select_streams v:0 -show_entries stream=nb_read_frames` vs `len(df)`; 不等就调 ffmpeg 参数重合并 (vsync 0 / fps_mode passthrough / 末帧补帧)。
- 除 v3.0 通用坑外, 记得: tasks.parquet、features 补 index/task_index、episodes 定位列 int64。
- **"Invalid frame index=N for streamIndex=0; must be less than M" 的隐藏来源 = 旧数据集缓存幽灵 (2026-08-02)**: 数据重建后 (如 640帧→399帧) 仍报旧索引 (517 > 399), 且清了 `~/.cache/huggingface/datasets` 也无效 — datasets 库还缓存旧 arrow/索引。**每次重建数据集 + 重训前, 清 `~/.cache/huggingface` 和 `~/.cache/datasets` 整个目录** (不是只清子目录), 否则旧帧索引幽灵持续报错, 看着像数据错实际是缓存错。
- **torchcodec 越界的最终根因 = timestamp 双重偏移 (2026-08-02 收尾, 权威正解)**: 报错 `Invalid frame index=1393 ... must be less than 755` 且**帧号 ≈ 期望×2** (1286 = 643×2) — 这是**双重偏移签名**, 不是 delta 越界也不是缓存幽灵。根因: `dataset_reader._query_videos` 会把 `episodes.from_timestamp` **加**到查询 ts 上 (`shifted_query_ts = [from_timestamp + ts for ts in query_ts]`)。若 parquet timestamp 已是全局绝对 (total/30.0) → 绝对 + from_timestamp = 双重偏移 → 视频帧号翻倍越界。**正解**: **parquet timestamp 写 episode 内相对 (`i/30.0`, 0, 0.033, ...)**, reader 自动加 from_timestamp 后 = 全局正确位置; frame_index 保持全局 (视频合并顺序, 与 index 列一致)。单文件合并视频 + 相对 timestamp 即可训 ACT (n_action_steps=7), **无需每包独立视频** (小芳方案2 是备选, 实测单文件+相对 ts 已通: 755帧/19轨迹 loss 1.524)。调试法: 训练前冒烟 `ds[0]` 和 `ds[num_frames-1]` 读不出即数据问题不是模型问题; `episodes=[N]` 单轨迹测试必现双偏移, 全量偶现。

## Orin 采集端 action 恒等 bug 修复 (tools/fix_orin_action.py, 2026-08-02)
**实测发现**: Orin 采集端把当前关节状态当成了 action 记录 → 数据包内 `action == observation.state` (恒等)。用这种数据训练 ACT 会学到恒等映射 (输出=输入), 无效。判别: 数据包首帧 action 与 state 完全相同。

- 检测: `np.allclose(actions, states, atol=1e-3)` 且形状相同 → 恒等。
- 修复: action 改为**关节速度差分** `delta[i] = state[i+1] - state[i]` (末帧用前向差 `state[-1]-state[-2]`), 与 Stage1 metaworld joint 数据 (关节速度) 定义一致。写回时标记 `action_fixed=True` + 保留 `action_orig`。
- 用法: `.venv/bin/python tools/fix_orin_action.py pkg.json` (检测+修复写回) / `--check` (只检测) / `--out fixed.json` (写副本)。质量报告含 帧数/维度/action==state/图像/标签。
- 集成点: 训练拉取 relay 包后先过 fix 再转 npz/数据集。
- **数据体检顺序 (2026-08-02 全踩)**: ① ECS relay 的 87MB ".npz" 包可能是 **safetensors 模型权重** (部署包, `file` 命令看头 `8y\0\0{...safetensors` JSON 头), 不是采集数据 — 检查前先 `file <下载文件>` 确认格式; ② 采集包 state 可能是 6D (n_joint=6) 而本地旧 npz 是 7D — 维度以 relay 包 meta 为准; ③ 本地老 npz 各轴动作均值完全相同 (0.268) / 帧间变化全同 = 疑似合成占位数据, 不可信。

## 边学边练闭环守护 (tools/auto_loop.py, 2026-08-02)
小芳采集 → ECS 队列 → 守护轮询 → 拉取 → build 数据集 → 训练 → 上传 → 小芳部署 Orin → 循环:
- **WS 事件驱动 v2 (2026-08-03 升级)**: auto_loop v2 订阅 WS `data_arrived` (ECS zmax_relay 在 /upload 成功后 notify(:8766) 广播) → **毫秒级触发训练**, 60s 轮询仅作兜底, 断线 5s 自动重连。单测 6/6: 事件触发/非事件忽略/快照过滤/frames 阈值/全链路/并发锁。效果: 采集→训练延迟从 60s 轮询降到事件即时。
- 60s 轮询 `/api/relay/status`, 新包且 `frames >= 20` (阈值别设 50, 34 帧真机数据会被跳过) 才拉取训练; `orin_snapshot` 源直接跳过。
- **IDLE 标签数据会污染训练 (2026-08-02)**: 机器人空闲时自动采集的包 (cron zmax-auto-collect 触发) 标签全 IDLE、action 全 0/静止 — 混进训练集教会模型"不动"。构建数据集时过滤 label 为 IDLE/空闲态的包, 或提示采集方在任务执行中采集 (动作标签如 暂时松开/移动/等待测试结果 才有价值)。
- **网络拓扑铁律 (2026-08-02 实测)**: 4060 WSL **到不了** Mac (192.168.23.1) 和 Orin (192.168.23.66) — 192.168.23.x 是仅小芳可达的内网, 4060 直连报 `No route to host`。4060 唯一外联 = ECS 公网 (39.102.211.79, scp 84MB ≈ 40s)。**模型传递的桥节点 = 小芳 Mac** (唯一同时通公网 URL + Orin 局域网): Mac `curl -o model.safetensors <静态URL>` 再 `scp ... tashan@192.168.23.66`。Orin 直下公网 URL 很慢 (3M/30s → 84MB 要 13 分钟), 别让 Orin 直下。
- **训练配置必须用独立 output_dir** (如 `config_act_loop.yaml` 的 `act_loop`), 复用已有目录 → `FileExistsError: Output directory outputs/train/act_cartesian already exists and resume is False`。
- **repo_id 用 `lerobot/pusht`** (hub 存在, 配合本地 root 补丁跳过下载); 用 `local/xxx` 不存在的 repo → `Repository Not Found ... /api/datasets/local/...` 认证失败。
- 守护用 `--once` 单次或后台长期跑 (`background=true` 静默守护); 训练失败会留下 `outputs/train/loop_train.log` 查根因。
- **守护重启会立刻处理队列里所有未消费数据包**: 小芳持续采集时队列常有积压 (34/46/59/88帧 多包), 守护一启动就逐个拉取触发训练, 不是"等新数据" — 属预期行为。数据包被守护拉走后队列变空, 模型包 (.npz) 的 meta 无 frames 字段 → 不触发训练, 但会被 `check_new_data` 记为已见, 守护不消费二进制模型。
- 守护的 train() 复用同一 output_dir 会撞车**: 多轮训练串行时若上一轮失败残留目录, 下一轮 `rm -rf` 清掉重训 (auto_loop 内已做); 但手动训练与守护并行会互删目录 — 训练期间别同时手动跑同配置。
- **训练锁防并发重建数据集 (2026-08-02 实测)**: 守护训练中 (约 2.5 分钟) 若新数据到达又执行 `build_dataset()` → 正在训练的 orin_6d 被删 → 训练中途 `Invalid key: 22 is out of bounds for size 22` (45% 进度崩)。修法: 训练前 `LOCK.touch()` (如 `outputs/train/.loop_lock`), `finally: LOCK.unlink(missing_ok=True)`; 主循环里 `if LOCK.exists(): 该包留待下一轮, continue` **且不加进 SEEN** (否则锁结束后该包永不重试)。锁存在时新包不消费。
- **glob.glob 返回 str → `str / str` 崩溃, 守护自动上传从未成功 (2026-08-02 收尾根因)**: `train()` 里 `ckpts = sorted(glob.glob(...))` 返回 **str 列表**, `ckpts[-1] / "pretrained_model" / "model.safetensors"` 报 `unsupported operand type(s) for /: 'str' and 'str'` — 训练 log 显示 `End of training` 成功但守护立刻报错, **模型从未自动推回 ECS** (v1-v3 全是手动 scp)。修法: `ckpts = [Path(c) for c in ckpts if "last" not in c]`。**判别**: 训练成功但守护报 str/str 且时间戳与 End of training 相同 = 上传环节 str 路径拼接, 不是数据 timestamp 问题 (常见错误表里 str/str=timestamp None 是另一条, 别混)。
- **模型传递 (推模型给 Orin) 不要依赖弹栈队列竞速 (2026-08-02 反复踩, 闭环最后一环卡死的主因)**: 弹栈队列 (`GET /latest` 取走即删) 在**多消费者竞争**时必丢 — 小芳的自动部署监听器 30s 轮询、我的守护 60s 轮询、手动 curl 都可能先取走; 84MB 模型下载超时 (41MB 断) 后重试时包已被删 → 队列空。**可靠推模型按稳度排序**: ① **静态 URL 方案 (最优, 实测闭环闭合)**: `sshpass scp model.safetensors root@ECS:<site_root>/models/<name>.safetensors` + `chmod 644` (否则 nginx 不可读 → 404/403), 小芳 `curl -o model.safetensors https://datadrive.world/models/<name>.safetensors` — 不弹栈、可重试、永久可用。**/models/ 映射目录有歧义, 两处都验证过能 200 (2026-08-02 实测)**:
  - 首选: **`/www/wwwroot/datadrive.world/models/`** (nginx 站点根, `root /www/wwwroot/datadrive.world;` — 传这里 URL 直接可达, 实测 84MB 完整下载 200; 文件权限必须 644 否则 403)
  - 备选: `/root/zmax-relay/models/` (relay 加过 `/model` 静态端点读这里)
  - **传错目录先 `curl -I https://datadrive.world/models/<name>` 或 `find / -name \"<name>\"` 定位真实映射目录**, 再 chmod 644。两种路径都验证过: 先确认 nginx 配置 `root` 指令指向哪个站点根。② scp 直连 ECS 文件系统 `sshpass scp root@<ECS>:/root/zmax-relay/data/pkg_*.npz .`; ③ 推完**停掉 auto_loop 守护**再让小芳拉 (`pkill -f auto_loop`)。**推模型前后都确认队列**: `curl /api/relay/status` 看 `latest` 是模型名 + `size` 是 80MB+ 级别; 推完发现队列空 = 已被抢或已部署, 问对端确认而非重推。数据包 (.json) 与模型包 (.npz) 在队列共存时, 先消费数据包, 模型包单独处理。\n- **Orin 真实推理验证 (2026-08-02 闭环闭合确认)**: 笛卡尔模型 (state 3D TCP 位姿 → action 4D 末端速度) 部署后, 真实推理 `ssh tashan@192.168.23.66 \"python3 ~/.zmax/orin_real_infer.py 0.6639 -0.0293 0.2935\"` → 输出 (7,4) 动作块 (dx/dy/dz/grip 各 7 步, 量级 0.1-0.3 m/s 合理) = 推理成功; 别信 mock /infer (infer_count 恒 0 不增)。\n- **快照/实时画面端点排查 (2026-08-02 cicd.html 无推流)**: 推流数据在 ECS 归档 (`/root/zmax-relay/archive/snap_*.jpg` 4fps 持续写入) 时, 画面应接 **`GET https://datadrive.world/api/snapshot/latest`** (返回归档最新快照 JPEG, 实测 200/7KB/age~0.7s), **不要用 `/api/relay/peek` 的 snapshot_b64** (弹栈会被消费) 也不要从采集包 camera_b64 取 (64x64 缩略图)。前端加 `?t=Date.now()` 防缓存。若静态目录 404: 查 nginx `root` 指令实际站点根 + 文件权限 644。

- **CICD 面板/三阶段管线的 300 步快速验证输出是 2D pusht 演示模型, 勿部署真机 (2026-08-02 重要警示)**: Simulink 控制台跑 `on_train` (cicd_pipeline/config_act_metaworld.yaml, 300 步 ~40s) 产出的模型 `input_features.state` shape 是 **[2]** (pusht 模板) — 这是快速验证链路用, 不是真机 6D 模型。老倪跑 CICD 全流程后它被 push 到 ECS 队列 (`pkg_221208.npz`), 小芳差点部署到 Orin → 维度不匹配。**铁律: 真机部署只认静态 URL 的 v3 6D 模型 (`https://datadrive.world/models/act_cartesian.safetensors`, state6/action6), CICD 面板演示模型进队列要提醒对端"勿部署"**。判别: 训练目录 config.json `input_features.observation.state.shape` — [2]=pusht 演示, [6]=真机 6D 关节, [3]=笛卡尔。
- **Simulink 数据闭环控制台验证方法 (2026-08-02 实测)**: ① 无 GUI 验证三阶段链路: `tools/cicd_pipeline.py test` (最少迭代 20 步跑通 1→2→3, 输出 "链路测试通过"); ② GUI 模块导入验证: `QT_QPA_PLATFORM=offscreen python3 -c "import sys; sys.path.insert(0,'tools/gui'); import simulink_module"` (注意用**系统 python3** — PyQt5 在系统解释器, 不在 .venv); ③ 控制台远程数据源全部真实: `/api/relay/status` (队列/帧数) + `/api/relay/orin/status` (在线/推理/心跳) + `/models/act_cartesian.safetensors` HEAD (模型 URL) — 10s 轮询, 无模拟值。控制台 6 环节按钮绑定真实回调 (on_collect/on_train/on_validate/on_integrate/on_deploy/on_infer)。

## 本地 4060 磁盘铁律 (2026-08-07 老倪\"绝对不允许增加\"实测)
- **smolvla 系 (SmolVLM2-500M/LEW) checkpoint 每个 ~1.4G**: 4000 步训练按默认保存频率会存 ~25 个中间 ckpt = **35G/模型**, 三个模型微调直接 103G → 磁盘 14%。act 每个 ~1.4-1.8G 但保存少。
- **铁律: 任何训练/续训完成后立即清理中间 checkpoint, 每目录只留最后一步** (老倪硬性要求磁盘不允许增加):
```bash
for d in <train_dir>; do
  ck=outputs/train/$d/checkpoints
  last=$(ls $ck | grep -E '^[0-9]+$' | sort -n | tail -1)
  for c in $(ls $ck | grep -E '^[0-9]+$'); do [ "$c" != "$last" ] && rm -rf "$ck/$c"; done
  [ -e "$ck/last" ] && rm -f "$ck/last"; ln -s "$last" "$ck/last"
done
```
- rollout/load 用 glob 最新目录 + `last` 软链 → 删中间 ckpt 不影响加载。实测 103G→8.9G (outputs/train), 磁盘 133G→39G (5%)。
- **训练脚本必须带\"训练成功检查\"再落曲线/产物**: `grep -qE "FileExistsError|Traceback|Error" <log>` 失败则跳过合并曲线 (否则旧曲线被\"未变数据\"覆盖, 脚本看似成功实际没训)。
- 生成大文件前先 `df -h /` 看余量; 临时文件 (/tmp/*_rollout, 预览 png) 用完即删。

## 容量上限 (防磁盘满, 2026-08-03 老倪"上线100M"实测)
- **单包/缓冲上限 100M**: nginx `client_max_body_size 100m` (api/relay 两条; comfyui 500m 保留) + relay `MAX_PKG = 100*1024*1024` (do_POST 读 Content-Length 超限 413 拒绝) + 已有 MAX_BUF 缓冲总量 100M。三层一致, 防 ECS 3.5GB OOM。
- **disk_guard.py** (每小时自动, `--once` 手动): orin_live 限 60 包 / 训练产物保留 4 个 (每个 500MB-1GB, 是最大占盘源) / loop_train.log 限 5MB 截尾 / dds_flow 水流序列限 2 万行 / /tmp 清 7 天前。
- **ECS logrotate**: `/etc/logrotate.d/datadrive` 管 datadrive.world.log + error.log (daily / maxsize 100M / rotate 3 / copytruncate) — 未配时 nginx 日志可涨到 500M+ (access 300M + error 211M 实测), 是 ECS 40G 盘的主要占盘源。
- ECS 磁盘 40G 易满: 重点清 `/www/wwwlogs` (日志) + `/root/zmax-relay/archive` (快照 505M)。

## Orin 性能监控 → cicd.html (sys 字段, 2026-08-03 老倪"要显示百分比/带宽/总量"实测)
链路: Orin 心跳 /heartbeat 带 `sys` → relay 透传 (293行 `"sys": data.get("sys", {})`) → `/orin/status` 返回 → cicd.html 读 sys 显示。脚本: `hermes_gateway_mac/orin_sys_status.py`。
- **格式规范 (老倪明确要求, v2 改版)**: 全字段**带单位 + 已用/总量**, GPU 必须**百分比** (不能是 "orin-integrated" 字符串):
```json
{"cpu": {"pct": 97.9}, "gpu": {"pct": 45, "model": "orin-integrated"},
 "mem": {"pct": 69, "used_gb": 10.5, "total_gb": 15.3},
 "disk": {"pct": 25.3, "used_gb": 46.2, "total_gb": 182.7, "free_gb": 136.5},
 "net": {"rx_kbps": 7522, "tx_kbps": 7638, "rx_total_gb": 12.3, "tx_total_gb": 5.1},
 "temp": {"c": 60.4}, "load": [16.45, 15.88, 12.9]}
```
- GPU 百分比: Jetson 用 `tegrastats --interval 500` 解析 `GR3D_FREQ (\d+)%`; 失败回退 nvidia-smi。内存/磁盘 psutil 或 /proc/meminfo + statvfs。带宽 /proc/net/dev 差分 (rx+tx 累计, 每秒换算 kbps) + 累计总量 GB。温度 thermal_zone0/1000。
- 纯只读采集, 不干扰产线 (与珞石 SDK 只读查询同原则)。

## 全局数据空间 (水流 DDS + 主数据, 2026-08-03 老倪"原型全局数据空间"实测)
- **主数据层 (稳定权威, m_ 前缀表)**: `m_workpiece` (工件/插拔力/精度) · `m_equipment` (设备/DOF/topics/标定, 实测型号 XMS5-R800-W4G3B4C 固件3.2.1) · `m_station` (工位/布局/任务) · `m_process` (动作标签→维度→条件→原子技能) · `m_model` (维度/帧数/loss/延迟/URL/状态)。脚本 `zmax-website/init_master_data.py`。
- **流水层 (动态实时)**: `waterflow_dds.py` 每 10s 探测 7 节点 (采集/上传/训练/模型URL/部署/推理/控制台) → 写 `dds_flow` 时间序列 (flow_rate 水流强度) + `dds_node_state` 实时状态。流水**只引用主数据 ID** (推理节点 detail 带 `模型:MD-ACT6D-v3`), 不复制主数据内容 → 无冗余、可追溯。
- 设计文档: `zmax-website/docs/MASTER-DATA-SPACE.md`; 全景基准: `lerobot-smolvla-lew/docs/ZMAX-DATA-LOOP-OVERVIEW.md` (v4.0, 唯一基准, 旧 DATA-FLYWHEEL/ARCHITECTURE-OVERVIEW 指向它)。
- 旧 ECS 地址 106.75.239.80 → 39.102.211.79 批量替换 (zmax_auto_collector/dds_cycle/orin_pipeline/collect_upload_npz/ib_robot_config/studio/data_closed_loop/zmax_sys1), 用 sed 扫 `grep -rn '106.75' --include=*.py|*.json|*.yaml` 排除 .venv。

## 三阶段渐进式训练管线 (tools/cicd_pipeline.py, 2026-08-02)
Stage1 MetaWorld 仿真 (backbone 冻结 lr_backbone=0, lr 1e-4) → Stage2 Sim-to-Real 零样本测试 → Stage3 Orin 微调 (lr 1e-5, backbone 1e-6, ensemble 0.01, n_action=1)。自动流转 1→2→3, steps 可配 (`run --steps1 N --steps3 N` / `stage N --steps N` / `test --steps1 20 --steps3 20` 最少迭代链路验证)。

- 状态: `docs/PIPELINE_STATE.json`, **每阶段独立持久化** `stages: {"1": {state, ckpt}, "2": {state, result}, "3": {state, ckpt}}` — 全局 state 只反映当前阶段, 否则进入下一阶段时历史阶段状态被覆盖 (用户反馈 "运行了第一阶段应该显示已完成")。
- **维度不匹配降级模式**: 仿真域 (metaworld 4D) 与真机域 (Orin 7D) 维度不同是物理现实。Stage2 = 先在同分布 metaworld 数据上仿真验证 (必出 MSE/成功率数字), 再尝试 Sim2Real, 维度不匹配**作为提示而非报错** (用户不满 "怎么还是报错")。Stage3 权重迁移失败自动降级从零训练并日志标注。
- GUI 面板 (PipelinePanel, 控制台 🎯 三阶段按钮): 3 张阶段卡 2s 轮询状态色 (未开始灰/运行中青/成功绿/失败红), S1/S3 steps 可配, 每阶段可单独运行, ▶ 全流程。
- **改数据维度必须 S1/S2/S3 三处同步 (2026-08-02 漏改教训)**: 6D 统一时只改了 Stage1/3 的 `data`, 漏改 Stage2 → Sim2Real 评估还在旧 7D 数据集 → `mat1 and mat2 shapes cannot be multiplied (1x7 and 6x256)` (输入 7D vs 模型 6D)。判别: 报错里 mat1 是**评估数据**维度, mat2 是**模型权重**维度 — 谁的维度错先看 STAGES[x].data。改维度后跑 `python tools/verify` 类检查或直接 `stage 2` 验证三阶段数据集维度全等 (state/action/image)。
- **Stage2 失败根因 (2026-08-02 用户 "为什么阶段2失败了" 实测排查)**: ① **验证/测试脚本污染真实 `docs/PIPELINE_STATE.json`** (写入模拟 stages) → stages.1 丢失 → run_stage(2) 找不到 S1 ckpt; ② 旧兜底 `latest_ckpt("outputs/train/act_mw_v111")` 回退到**假训练时代的 2D/pusht 模型** → 在 4D 真实数据上仿真验证 `mat1... (1x4 and 2x256)` → failed。教训: 测试脚本不得写真实状态文件 (用临时路径或跑完恢复); **兜底必须用 `latest_s1_ckpt()`** (glob outputs/train/act_s1_* 按 mtime 最新, 真实 4D), 固定旧目录名会捡回假训练产物。判别模型真假: config.json `input_features` state shape (真 metaworld=4 / 真 orin=7 / 假 pusht 模板=2)。

## Evaluation & baseline comparison (2026-08-02 实测)
Compare a candidate checkpoint against a baseline on the SAME data with the SAME input features — different state dims (e.g. metaworld_mt50=4D vs act_metaworld=2D) make any comparison meaningless.

Tool: `tools/act_compare.py --baseline <ckpt> --candidate <ckpt> --dataset data/metaworld_act --report docs/CICD_COMPARE_v1.1.0.html` (outputs JSON + HTML; 4060 实测 100 帧 ≈ 1-2min). Auto-iterate: `tools/auto_iterate.py` (train → compare → if MSE improve <5% adjust steps+1000/lr×0.8 → retrain).

**Critical pitfalls (all hit in session):**
- `select_action()` returns NORMALIZED actions — must run through the unnormalizer postprocessor or MSE is nonsense (~78000 vs ~12000 after fix). Load it via `from lerobot.policies import make_pre_post_processors` (NOT `lerobot.processors` — no such module) + `make_pre_post_processors(policy_cfg=policy.config, pretrained_path=str(ckpt))`. ACTPolicy import path: `lerobot.policies.act.modeling_act` (not `policy_act`).
- `LeRobotDataset` AUTO-GENERATES `observation.image` for datasets whose parquet has no image column (metaworld_act has none, but `ds[i]` still returns observation.image 3×96×96 with real values) — don't infer image availability from parquet columns; check `policy.config.image_features` (dict after load) to decide what to feed.
- When parquet DOES have images: column is dict `{"bytes": PNG}`, decode with PIL (see zmax-data-pipeline).
- Fair comparison needs same feature shapes: verify via `config.json` `input_features`/`output_features` before comparing.
- Real numbers (4060, metaworld_act 2D): baseline 300-step MSE 12037, candidate 2000-step MSE 11155 → +7.33% improvement. Success-rate metric (<0.05 MSE) stayed 0% — MSE is the discriminating metric at these magnitudes.
- Auto-iteration v2 (3000 steps + lr 8e-5, auto-adjusted after v1 fell below 5% threshold): MSE 11053 → +8.18% ≥ 5% → auto-verdict 达标 → auto-deploy. Iteration path 300→2000→3000 steps: 12037→11155→11053.

**Auto-iteration tooling pitfalls (tools/auto_iterate.py, all hit in session):**
- **Regex editing YAML clobbers nested fields**: `re.sub(r"steps: \d+", ...)` ALSO matches `  n_obs_steps: 1` and `  n_action_steps: 7` (they contain `steps: \d+`) → sets them to 3000 → ACTConfig error `n_action_steps 3000 > chunk_size 7`. Fix: anchor to line start with `^steps: \d+` and `^lr: ...` using `flags=re.M` — only the top-level `steps`/`lr` get touched. After any config-rewriting helper, grep the config to confirm nested fields survived.
- **compare JSON path must follow `--report`**: act_compare.py originally hardcoded `Path("docs/CICD_COMPARE_v1.1.0.json")` while auto_iterate looked for `docs/CICD_COMPARE_auto.json` → "对比失败" with no visible error (JSON written under the wrong name). Fix: `json_path = Path(args.report).with_suffix(".json")` so HTML and JSON stay coupled.
- auto_iterate failure AFTER a config breakage may leave `outputs/train/<job>` deleted (script `rm -rf`s it each round) — retraining is required, don't expect the old checkpoint to survive.

详细实测记录 (加载/归一化/数据形状/数字): `references/act-baseline-compare.md`

中版本迭代 + GitHub Release 流程 (v1.1.0/v1.2.0 实测两次): `references/version-release-flow.md`

## 坐标叠加架构 (2026-08-08 老倪: "坐标是逻辑主线, 图像是背景 — 叠加而不是混合")
ACT 默认把 state 作为 1 个 token 混进序列 (与 49 个图像 token 并列) → 坐标信息被图像淹没。
**改造 (modeling_act.py forward)**:
```python
latent_embed = self.encoder_latent_input_proj(latent_sample)
if self.config.robot_state_feature:
    state_embed = self.encoder_robot_state_input_proj(batch[OBS_STATE])
    latent_embed = latent_embed + state_embed   # 坐标叠加进 latent (逻辑主线)
encoder_in_tokens = [latent_embed]              # state 不再占独立 token
# 图像特征仍是背景 token (旁路)
```
**必改配套 (漏一个就崩)**:
1. `n_1d_tokens = 1` (原为 1+robot_state+env_state=3) — 否则 pos_embed 尺寸不匹配
   (`The size of tensor a (17) must match the size of tensor b (18)`)
2. VAE encoder 分支 (训练用) 保留原样 — 它有自己的 robot_state token, 不受影响
3. 控制台 simulink 加 🧩 坐标叠加节点: `node_logic.py _reg("coord_overlay", [...])` +
   `simulink_module.py NODE_TYPES` 加类型+颜色 + paint 分支 (画 + 号 + `latent += state×gate`) +
   画布默认结构 5 模型行 State Adapter 后插入 "🧩 坐标叠加"。node_logic 框架方法用
   `getattr(module, "_set_...", None)` 容错 (module 可能没实现)。

## 无 VAE 结论 (2026-08-08 静界对照实验: overlay2❌/big❌/novae✅)
**peg-insert 是单模态唯一路线任务 (填空题) → use_vae: false 是决定性因素**。对照: 17条VAE❌不动 / 68条VAE❌不动 / 68条无VAE✅动了 (距离 0.247→0.066m 大幅接近)。
- **VAE = 多样性开关 (选择题用)**: 原版 ACT (ALOHA 穿衣) 多模态任务 (多条路都对) + 数百条 demo → latent 编码"路线偏好", 随机采样出多样动作。peg-insert 只有"对准→插"一条路, 多样性能力用不上。
- **VAE 副作用机制**: 训练时 encoder 偷看未来动作 (latent 含答案), 推理时无未来 → latent=0 → 模型傻眼; 叠加架构放大了这个坑 (state 叠加到不稳定的 latent 上)。
- **无 VAE 后**: latent 恒 0 → `latent(0) + state = 干净 state 信号` → 模型直接学 state→action 映射 (像 MLP 一样) — 几何条件叠加才真正起作用。
- **有效组合 (按贡献)**: 无VAE(决定性) > 几何条件叠加(基础) > 纯接近数据(支撑, 68条方向一致不平均化)。
- 控制台落地: ACT config `use_vae: false` (config_act_pegdata.yaml 已改), simulink ACT 行节点「🚫 VAE 编码器(无)」, 参数区标题 ACT/MLP 标 🚫无VAE。
- 训练数据: novae = `data/metaworld_peg_grab6` (68条纯接近, 1.6M) — 别用长轨迹 (见上方平均化坑)。

## 官方专家生成数据必须 corner2 相机 (2026-08-08 截断数据 300 帧不截断根因)
`env = mt.train_classes[task](render_mode="rgb_array")` **缺 camera_name="corner2"** →
官方专家 `SawyerPegInsertionSideV3Policy` 动作时序乱 (peg 抓取轨迹不同) → 触发检测
永远不满足 → 轨迹跑满 300 帧不截断。**生成器主 env 必须与验证 env 一致带 corner2**:
`(render_mode="rgb_array", camera_name="corner2")`。官方专家 85% 成功率依赖 corner2。

## 截断数据 (stop_after_grab) 后 meta 三处必须同步 (2026-08-08 反复踩)
截断轨迹 (抓起后 N 帧即停, 轨迹 < 300 帧) 后, 生成器写 meta 仍用旧值 → 加载即崩, 且错误信息误导:
- **`IndexError: Invalid key: 1800 is out of bounds for size 1015`** = `meta/info.json` 的
  `splits: {'train': '0:1888'}` (或 total_frames) 是旧帧数 — **splits 必须同步改** (只改
  total_frames 不够, splits 仍指向旧值 → 反复报同样 IndexError)
- **episodes parquet 的 `length` 列 = 旧 args.steps (300)** → sum(300×11=3300) > 实际 1015 →
  同一 IndexError。生成器 274 行 `all_eps.append({"episode_index": ep, "length": args.steps})`
  在截断模式下 length 必须用**实际帧数** (`len([f for f in all_frames if f["episode_index"]==ep])`)
- **数据 parquet 的 episode_index 可能稀疏** (丢弃轨迹后 0,3,5,6,7,8,10...19) → 重编号为连续 0..N-1
  (LeRobot 用位置索引查 episodes[ep_idx])
- **episodes parquet 标准必需列 (重建时照抄)**: episode_index, length, tasks,
  `videos/observation.image/chunk_index, /frame_index(l-1), /file_index, /from_timestamp(0.0),
  /to_timestamp((l-1)/30.0), /chunk-000/index, /chunk-000/from_frame(0), /chunk-000/file_index`,
  `dataset_from_index(全局累加), dataset_to_index(start+l-1)`,
  `data/chunk_index, /file_index, /chunk-000/...` 同视频列,
  `meta/episodes/chunk_index, /file_index`。缺 `dataset_from_index` → `ValueError: Column
  'dataset_from_index' doesn't exist`; 缺 `videos/.../file_index` → `KeyError`.
- **修完 meta 必须 `rm -rf ~/.cache/huggingface/datasets`** 再训练, 否则旧 schema 幽灵复现。

## 远程 Docker 容器化训练 (V100, 2026-08-08 打通链路)
远程 GPU (223.109.239.36:24424 root, V100 32G, 驱动 550.127/CUDA12.4) + docker 容器训练:
- **容器内 torch CUDA 版本必须 ≤ 驱动支持的 CUDA**: 镜像内 torch 2.11+cu130 (或混装 nvidia-cuda-runtime 13.0)
  在驱动 550 (CUDA12.4) 上 `torch.cuda.is_available()=False` + 警告 "driver too old (found 12040)"。
  **修: Dockerfile 显式固定 `pip install torch==2.4.1 torchvision==0.19.1 --index-url
  https://download.pytorch.org/whl/cu124`** (cu124 匹配驱动 12.4)。验证: 容器内
  `python -c "import torch; print(torch.cuda.is_available())"` 必须 True。
- **没有 nvidia-container-toolkit 时 `--gpus all` 报 `could not select device driver ""`** →
  用 `--device /dev/nvidia0 --device /dev/nvidiactl --device /dev/nvidia-uvm
  -v /usr/lib/x86_64-linux-gnu/libcuda.so.1:/usr/lib/x86_64-linux-gnu/libcuda.so.1:ro` (模型引擎同款)。
- **`nohup docker build ... &` 在 SSH 会话断开时会中断** (日志停在 pip 安装中段) → 用
  `setsid docker build ... > log 2>&1 < /dev/null &` 脱离会话, 后台轮询 `docker images | grep v2`。
- **容器名冲突**: 旧容器残留 `docker run` 报 `Conflict. The container name "/zmax_train" is already in use`
  → 先 `docker rm -f zmax_train zmax_test`。
- **容器内日志**: `docker run --rm` 退出即删日志 → 用 `bash -c "cmd > /tmp/x.log 2>&1"` 重定向到
  挂载卷 (如 /app 工程目录) 或去 `--rm` 再 `docker logs`。测试脚本放挂载目录 (容器内 /tmp 不挂载)。
- 远程数据/配置同步: `git pull` + 远程 config 的 `root:` 指向远程 `data/` (已同步 grab6)。
- **模型引擎自动连接**: 凭据写 `~/.zmax_ssh.json` (`{"host","port","user","pwd"}`), 控制台启动 3s 后
  `_auto_connect_gpu` 自动连 (无需手动点按钮); 连接成功设 `gpu_mode=remote` + `remote_engine`,
  训练节点提交远程容器; 失败回退本地。simulink_module 必须实现 `set_model_engine(engine)` 存引用,
  否则 studio.py `_build` 崩 `AttributeError: 'SimulinkModule' object has no attribute 'set_model_engine'`。
- **引擎远程训练默认配置是旧的** (root: data/metaworld_peg + use_vae:true) — 打通前先改远程
  config 指向新数据 + 无 VAE, 否则 V100 白训。

## Eval 管道归一化/反归一化 (eval_insert.py, 2026-08-08 全部模型踩过)
**\"评估 0% 抓起\" 的第一嫌疑 = 动作没反归一化或 state 归一化错源, 不是模型没学会**。eval_insert.py 的 run_episode 有 3 个动作分支, 每个都必须反归一化:
- ACT 分支 (`select_action`): `act * asd + am` — 一直正确
- `_cond` 分支 (VLA-Touch): 曾漏反归一化 → 输出恒定归一化值 → 0%
- **else 分支 (AWE, 无 `_cond` 属性!)**: 曾漏反归一化 → 动作恒定 → 0%。AWE 没有 `_cond`, `hasattr(policy, "_cond")` 判断会走 else — 修 else 分支而不是 _cond 分支
- 反归一化 stats 键名: AWE/VLA-Touch 训练脚本存的是 **`a_mean/a_std`** (checkpoint `policy.stats`), 不是 `action.mean/std` — 读取要兼容两种键 (`_st.get("a_std", _st.get("action", {}).get("std", ...))`)

**归一化 stats 来源 (2026-08-08 实测)**: 全局 `data/*/meta/stats.json` 会被磁盘清理删掉 (v5/v6/v7 目录消失) → `_load_stats()` 返回 None → eval 崩; 旧 stats 可能只有 1 维 (MEAN_STD 标量) → 39D 归一化全错。**正解**: 优先从 checkpoint 读 `policy_preprocessor_step_3_normalizer_processor.safetensors` (键 `observation.state.mean/std`、`action.mean/std`, 标量广播到 39D/4D); AWE/VLA-Touch 用 `policy.stats["s_mean"/"s_std"]` 做 state 归一化 (与训练一致, 别用全局 stats)。**曾发现 eval_insert 残留调试行 `sm=np.zeros(st_dim); ss=np.ones(st_dim)` 覆盖加载的 stats → 归一化失效 → 假 0%** — 删覆盖行。

## 长轨迹多阶段平均化坑 (2026-08-08 实测, ACT/SmolVLA/AWE 全中招)
**300 步完整轨迹 (Phase1 接近→抓取→插入) 不适合行为克隆训练**: 各阶段动作方向相反 (接近朝 peg、插入朝 hole), BC 模型回归学到\"平均动作\" → 动作趋零/漂移 → **方向学反** (ACT 手越走越远 d_peg 0.157→0.588, AWE 朝 x- 远离 peg)。判别: 长轨迹数据训练后 rollout 距离反而增大。
- **MLP 蒸馏免疫**: 39D 精确坐标直接映射动作, 每步独立条件反射, 不受时序平均化影响 — 唯一能插拔的学习模型 (抓起 6/10 插入 3/10)
- 方案: 要么短轨迹只学单阶段, 要么用 39D 直映射架构; 多阶段长轨迹只适合蒸馏 (专家→MLP) 不适合 BC
- 数据多样性: `env.reset(seed=N)` 不改手起点 (被关节限制固定), 但**不同 `train_tasks[i]` 索引 → 不同 peg 位置** (dist 0.149~0.240) — 用 task 索引做多样性
- 官方专家 `SawyerPegInsertionSideV3Policy` 状态机假设手在标准起点 (0,0.6,0.16) 附近, 远移后不拉回 → 远起点数据生成必须用手写多阶段专家 (Phase1-5, 任意起点可用)

## Rollout 推理 (rollout_video.py) 三根因修复
obs dict 解包 (V3 obs 是 dict → state 全零) / stats 39D-3D 广播 (np.pad 补零防 NaN) / ACT robot+env 39D 拆分; 光模块数据集生成 (官方专家采样) + 插入成功检测: `references/rollout-inference-fixes.md`

## 自定义 policy 工程化 (left_right 双脑, 2026-08-10 全流程踩坑)
把自定义模型封装成 lerobot 标准 policy 并用 `lerobot_train` 训练 — 完整踩坑清单 (全部实测):

**包结构** (src/lerobot/policies/<name>/): `configuration_<name>.py` + `modeling_<name>.py` + `processor_<name>.py` + `__init__.py` + factory.py 注册 (config import + `elif name == "<name>": return <Policy>` 两处)。

**PreTrainedConfig 抽象方法 (漏一个即 TypeError abstract)**: `action_delta_indices` / `observation_delta_indices` / `reward_delta_indices` (properties) + `validate_features` / `get_optimizer_preset` / `get_scheduler_preset`。
- **`get_optimizer_preset()` 必须返回 OptimizerConfig 子类** (`AdamWConfig(lr=..., weight_decay=..., grad_clip_norm=...)`), 不是 dict — 返回 dict 时 `use_policy_training_preset` 路径下 `cfg.optimizer.build` 崩 `'dict' object has no attribute 'build'`。

**PreTrainedPolicy 要求**: `config_class = <Config>` + `name = "<name>"` 类属性 (否则 __init_subclass__ 抛错); `__init__` 必须先 `super().__init__(config)` 再赋 nn.Module 子模块 (`cannot assign module before Module.__init__()`); `__init__` 签名要收 `dataset_stats=None, dataset_meta=None` (lerobot_train 会传)。
- 抽象方法: `reset()` / `get_optim_params()` / `predict_action_chunk()` + `select_action` / `forward` / `compute_loss`。
- **`get_optim_params()` 返回参数组列表** `[{"params": [...]}, ...]` (不是单 dict `{"params": [...]}` — AdamW.build 遍历报 `one of the params is str`)。
- **`forward(batch)` 返回 `(loss, output_dict)` 元组** (lerobot_train 里 `loss, output_dict = policy.forward(batch)`), 不是只返回 dict。`compute_loss` 内部 `loss, _ = self.forward(batch)`。
- `save_pretrained` 里 **PolicyFeature 对象不能 json.dump** (`Object of type PolicyFeature is not JSON serializable`) — 转 dict: `{"type": str(ft.type.value), "shape": list(ft.shape)}`。

**processor (processor_<name>.py)**: 用 `PolicyProcessorPipeline` (不是 DataProcessorPipeline — 旧版无 __call__ 报 `not callable`), 步骤照抄 act: `RenameObservationsProcessorStep + AddBatchDimensionProcessorStep + DeviceProcessorStep + NormalizerProcessorStep` (pre) / `UnnormalizerProcessorStep + DeviceProcessorStep(cpu)` (post)。
- **`normalization_mapping` 的键是 FeatureType 字符串** (`{"STATE": MEAN_STD, "ACTION": MEAN_STD}`), 不是 `observation.state`/`action` 特征名 — 否则 `ValueError: 'observation.state' is not a valid FeatureType`。
- features 用 `PolicyFeature(type=FeatureType.STATE, shape=...)` 对象, 不是 dict (dict 缺 type 报 KeyError)。
- factory 里加 `elif isinstance(policy_cfg, <Config>): make_<name>_pre_post_processors(...)` 分支。

**训练配置 (config yaml)**: `policy: {type: <name>, ...}` + `dataset: {root: 本地数据}` + 顶层 `steps/batch_size/optimizer: {type: adam, lr: 0.0001}`。
- **YAML 浮点陷阱**: `lr: 1e-4` 被 yaml 解析成 **str** → Draccus 类型错误; 写 `0.0001`。
- **数据集 state 维度必须与模型输入一致**: left_right 用 39D, 但 tactile2 数据集是 49D → `mat1 and mat2 shapes cannot be multiplied (8x49 and 39x512)`。选数据前先查 `meta/info.json` 的 state shape。
- 无 `training:` 字段 (`The fields training are not valid for TrainPipelineConfig`), 顶层直接 `steps:`。

**checkpoint 序列化**: 标准产物 = `config.json + model.pt + <pre/post>processor.json + <pre/post>processor_step_*_normalizer_processor.safetensors` — 训练 3000 步自动落盘, `from_pretrained` 可加载。

**状态机常量编号必须与参照脚本一致 (2026-08-10 实测)**: 把 state machine 搬进 policy 时, 若参照脚本 (train_full_pipeline.py) 用 8 状态 (`ST_APPROACH,ST_ALIGN,ST_DESCEND,ST_GRASP=0,1,2,3; ST_LIFT,ST_TRANSFER,ST_INSERT,ST_DONE=4,5,6,7`) 而 policy 用 6 状态 (DONE=5), **DONE 判定/插入计数/状态名打印全错位** (eval 里 `state_names[policy.state]` 越界、插入计数口径不同)。修法: 常量定义与参照脚本逐行对齐, eval 插入判定统一走 `policy.state == ST_DONE` (状态机 DONE 口径), 不要混用 env 距离口径。**判定结果差 2-3 个 seed 先怀疑常量/口径不一致, 再怀疑随机性** (见上方随机性陷阱 — 两者叠加曾把 7/8 vs 4/8 误判为实现差异)。

## 评估随机性陷阱 (2026-08-10 决定性验证)
**metaworld `env.reset(seed=N)` 后仍有物理随机** (`_freeze_rand_vec=True` 冻结 rand_vec, 但每次 reset 的初始扰动不同) → **单次 8-seed 评估结果不可信, 必须多次重复取范围**:
- 同权重同代码 3 次重复: 抓起 5/8→7/8→6/8, 插入 5/8→4/8→6/8 — **波动 2-3 个 seed 是常态**。
- "手写脚本 7/8 vs policy 4/8" 逐帧对比发现: 同一 seed 两次运行行为完全相反 (一次卡抓取、一次插入成功) — **不是实现差异, 是随机抽样**。
- **判别法**: 怀疑"代码 A 比 B 好"时, 先各跑 3 次重复取范围, 范围重叠即无差异; 逐帧对比单 seed 无意义 (同一 seed 每次物理都不同)。
- 数据增强降波动 (120 eps 随机种子 0-499 vs 原 0-49): 抓取下限 5→6、均值 7.0 (右脑 contact 判断见过更多扰动); 插入波动不变 (转移卡顿是物理, 非初始扰动)。转移加 z 保持反而更差 (垂直力干扰水平转移) — 已回滚。
- 转移速度自适应 (近距减速: d>0.2m→0.6速, 0.05-0.2→0.35, <0.05→0.15): 抓起方差略优 (6,7,7 更集中), 插入持平 4-6 — **≈ 无显著改善**。结论: 转移卡顿是**物理碰撞** (peg 与孔边/台面几何干涉), 无接触反馈的控制参数调不动 → 需真机力控/视觉对齐, 仿真里别继续调转移参数 (止损点)。

## 39D obs 结构矛盾 (2026-08-10, 状态机必须用 env 真值)
metaworld peg-insert-side-v3 的 39D obs: `obs[0:3]=hand`, **`obs[18:21]=hand 重复` (不是 peg!)**, `obs[36:39]=hole` — **obs 里没有 peg 位置段**。状态机/接触判断要用 peg 位置时, **必须从 `env.data.site_xpos[env.model.site("pegGrasp").id]` 读真值** (policy 加 `set_env(env)` 接口注入), 不能从 obs 索引取 — 否则状态机把 hand 当 peg, d_hp 恒 ~0 → 误触发抓取。

## Templates
- `templates/config_act_closedloop.yaml` — known-good ACT training config (copy + adjust)
