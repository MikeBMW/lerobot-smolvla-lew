# LeRobot v3.0 本地图像数据集构建 + smolvla_lew 微调/续训 (2026-09-09 实测)

Z-MAX 场景: 用采集的 metaworld episode (npz 数值 + mp4 帧) 构建 smolvla_lew 微调数据集, 离线 (无网) 训练/续训。4060 8GB 可跑。

## 一、v3.0 数据集目录结构 (缺一个都加载崩)
```
<root>/meta/info.json            # features 必须写全 (见下)
<root>/meta/tasks.parquet        # {task_index:int64, task:str} — 缺 → FileNotFoundError tasks.parquet
<root>/meta/episodes/chunk-000/file-000.parquet  # 每 episode 一行 + video 索引列
<root>/meta/stats.json           # image=ImageNet mean/std; state/action 须含 mean/std/min/max
<root>/data/chunk-000/file-000.parquet   # 帧行 — 不含 video 列!
<root>/videos/observation.image/chunk-000/file-NNN.mp4
```
- `meta/stats.json` 缺 min/max → `ValueError: MIN_MAX normalization mode requires min and max stats` (smolvla 用 MIN_MAX)
- `meta/info.json` 缺 features → `DatasetInfo.__init__() missing 'features'`
- data parquet **不要**写 `videos/*` 列 — 视频索引在 episodes parquet (videos/observation.image/{chunk,file}_index + from/to_timestamp), 参照 smolvla_peg_img

## 二、时间戳对齐 — FrameTimestampError 头号坑
采集脚本每 4 步渲染 1 帧 (RENDER_EVERY=4), mp4 25fps → 视频时长只有步数的 1/4。
**timestamp 列必须 = (frame_index // 4) / fps** (映射到真实存在的帧), 写成 i/fps 会超视频时长 → DataLoader worker `FrameTimestampError: query timestamps exceed tolerance`。
episodes parquet 的 `to_timestamp = (视频帧数-1)/fps`。

## 三、离线训练 (无网)
- `dataset.repo_id` 是 draccus 必需字段, 但填任意 id 都触发 hub 检查 → 断网必炸 OfflineModeIsEnabled
- 两件套 (同 docker-gpu-training 主文): ① runner monkeypatch `huggingface_hub.HfApi.list_repo_refs` 返回空 _Refs; ② src/lerobot/datasets/utils.py `get_safe_version` 加本地兜底 `if version in ("main","local",""): return version`
- 权重走 HF 缓存 + `HF_HUB_OFFLINE=1`; SmolVLM2-500M-Video-Instruct 缓存后 ~489 块秒载

## 四、续训 resume (三步缺一不可)
```bash
# 1. config 改 steps 到目标总数; output_dir 不变
# 2. 编辑 <out>/checkpoints/NNNN/pretrained_model/train_config.json: 设 resume=true (训练时存的是 false)
# 3. 启动必须 --config_path= 带等号 指向该 train_config.json (不是 yaml!):
gui-venv311/bin/python -u -m lerobot.scripts.lerobot_train --config_path=outputs/train/xxx/checkpoints/NNNN/pretrained_model/train_config.json
```
- `parser.parse_arg("config_path")` 只认 `--config_path=值` (带 =), 空格分隔 → `ValueError: A config_path is expected when resuming`
- output_dir 已存在 + resume false → `FileExistsError`
- 完成后 checkpoints/last → 最新 step 目录; model.safetensors ~1.2GB (500M VLM + head)

## 五、CPU vs GPU 训练速度 (MLP 也要 GPU)
- 550 万参数 MLP × 8.4 万帧 × 1000ep: CPU 多核 ~17h+ (torch intra 24 线程仍吃不满, 线性层小 batch 并行差)
- 同配置 GPU (4060 8GB): ~12min — **大数据 MLP 训练一律 .to(cuda), batch 提到 2048+**
- gui-venv311 缺训练包时: `pip install termcolor draccus datasets av accelerate diffusers einops` (torch/transformers 已就绪)

## 六、验证模型真加载
- config.json 可能缺 `type` → 加载报 Can't instantiate abstract class → 补 `{"type": "smolvla_lew"}`
- 用具体策略类加载: `SmolVLALewPolicy.from_pretrained(ckpt)` (不是 PreTrainedPolicy 基类)
- select_action 输出需 postprocessor 反归一化 (MIN_MAX→真实动作), 否则动作幅度错乱
