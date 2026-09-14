# v3.0 图像数据集构建 (episode npz+mp4) + smolvla_lew ckpt 加载 — 2026-09-08 实测

## 场景
gen_ss_metaworld_episode 类采集器产 npz(数值轨迹) + mp4(渲染帧, RENDER_EVERY=4 → 每 4 步 1 帧)。
把 (npz, mp4) 对转 LeRobot v3.0 **图像**数据集给 VLM(SmolVLM2-500M) 微调。连踩 5 坑:

### 1. ⚠️ timestamp 必须按视频帧对齐, 不是按步 (FrameTimestampError)
视频只有 T/4 帧但数据有 T 行。若 `ts = i/fps`(每步), 查询时间戳(≈11s)超视频时长(≈7s) →
`FrameTimestampError: One or several query timestamps unexpectedly violate the tolerance
(tensor([11.08, 11.12]) > tolerance_s=0.0001)`。
**修复**: `ts = (i//STRIDE)/fps` 且 `fi = min(i//STRIDE, vn-1)` — 每 STRIDE 步共享同一视频帧时间。
episodes meta 的 `videos/.../to_timestamp = (vn-1)/fps` 同源。验证: ep 数据 ts_max ≤ 视频时长。

### 2. ⚠️ data parquet 绝不能含 videos/* 列 (CastError)
视频索引列 (chunk_index/file_index/from_timestamp/to_timestamp) **只放**
`meta/episodes/chunk-000/file-000.parquet`; data parquet 只放纯列
(observation.state/action/各索引/next.*)。把 video 列塞进 data parquet →
`datasets.table.CastError: Couldn't cast` (列与 info.json features 不匹配, datasets 库 cast 阶段崩)。

### 3. v3.0 本地加载缺三件套
- 缺 `meta/tasks.parquet` → pandas FileNotFoundError → 落回 hub 拉取 → 离线时
  `OfflineModeIsEnabled: Cannot reach https://huggingface.co/api/datasets/.../refs` **假象**
  (真因是本地 meta 缺文件, 不是网络)。补 tasks.parquet 即可。
- 缺 info.json `features` → `TypeError: DatasetInfo.__init__() missing 1 required positional argument: 'features'`。
- repo_id 直接设本地路径 `repo_id: data/xxx` + `HF_HUB_OFFLINE=1`, 本地 meta 完整就加载不查 HF。
- 本地 meta 修复后必须 `rm -rf ~/.cache/huggingface` 清 datasets schema 缓存。

### 4. stats.json 必须 mean/std + min/max 四件套
训练归一化 MIN_MAX 模式报:
`ValueError: MIN_MAX normalization mode requires min and max stats`。
参照可用数据集的 stats keys = [mean, std, min, max]; image 特征用 ImageNet 固定值
(mean [0.485,0.456,0.406], std [0.229,0.224,0.225]); state/action 的 min/max 从输出 parquet 实算。

### 5. 每集独立 mp4 vs 单文件合并
每 episode 独立 `file-{ep_idx:03d}.mp4` 可行 — episodes meta 每行 file_index 指向自己的 mp4,
data parquet 不出现视频列。此前技能#10 的"单文件合并"是另一种布局, 二选一, 不要混。

## 训练 (lerobot_train, smolvla_lew)
- gui-venv311 缺训练依赖逐个补: termcolor / draccus / datasets / av / accelerate / einops /
  diffusers (smolvla_lew DiT 硬要求, 缺失报 `'diffusers' is required but not installed`)。
- config 结构: 顶层 `batch_size/steps/num_workers/log_freq/eval_freq/save_freq/seed` +
  `optimizer: {type: adam, lr, weight_decay}` + `wandb: {enable: false}` — 不是 training: 段。
- 显存: 冻结 SmolVLM(约1.4GB) + DiT-B/LEW-192 → 4060 8GB 实测峰值 2.4GB, 1.2-1.4 step/s。
- 3000 步 loss≈0.5 但 rollout 不收敛属正常 — BC 长程任务需 3-5 万步 + 阶段引导 (见下)。

## 训好 ckpt 加载/rollout (SmolVLALewPolicy)
- **from_pretrained 用具体类**: `SmolVLALewPolicy.from_pretrained(ckpt)` — 抽象基类会报
  `Can't instantiate abstract class PreTrainedPolicy with abstract methods ...`。
- **config.json 补 type**: 训练写的 ckpt config.json 无 `type` 键 → draccus
  `ParsingError: Expected a dict with a 'type' key for PreTrainedConfig`。
  修: `json.dump` 读改写加 `{"type": "smolvla_lew"}`。
- **select_action 返回 cuda tensor**: 转 numpy 前 `.cpu()` (`can't convert cuda:0 device type
  tensor to numpy`)。
- **EGL 渲染 + CUDA 同进程冲突**: 已加载 CUDA 的进程里 `MUJOCO_GL=egl` 报
  `EGLError: EGL_NOT_INITIALIZED` (无 nvidia EGL 厂商库 libEGL_nvidia 时必现; 只有 mesa)。
  有 X11 → `MUJOCO_GL=glfw` + `DISPLAY=:0` 可渲染。
- **⚠️ 裸 rollout 不收敛是常态, 别冒充成功**: 3000 步 + 无任务阶段引导 → 模型每步输出
  动作但 peg 距 hole 恒定不动 (光模块没被送向孔口)。端到端 VLM 要插拔成功需 3-5 万步 +
  阶段状态机引导 (或分阶段数据)。汇报必须区分: 引擎解析伺服(规则)能完成 ≠ VLM 策略已学会。

## 数据规模参照
smolvla_peg_v8: 124 eps · 129883 帧 (480×480 corner2) · state 39D · action 4D (u_exec)。
