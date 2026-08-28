# LeRobot v3.0 本地数据集构建全要求（2026-08-02 六小时踩坑实测）

场景：手头有 raw 采集 JSON（frames: state/action/label/camera_b64）或 metaworld npz，
要构建 `LeRobotDataset` 能加载的本地数据集。下面每一条都是真踩过的坑。

## 0. 先修 fork 的两个 hub 覆盖 bug（不修必被覆盖）
此 fork 的 `LeRobotDataset` 和 `LeRobotDatasetMetadata` 在 `root=本地目录` 时仍会执行
`snapshot_download(repo_id, local_dir=root)`，把 hub 数据（如 lerobot/pusht）下载覆盖到
本地目录——你刚写好的 info.json/parquet 会被换成 pusht 的（症状：state shape 变 [2]、total_frames 变 25650）。
修复（已入库 src/lerobot/datasets/）：
- `dataset_metadata.py` `_download_from_hub`：`(root/"meta"/"info.json").exists()` 时打印
  "📂 metadata 使用本地" 直接 return，跳过 snapshot_download。
- `lerobot_dataset.py` `_download`：同样判断，本地存在即 `self.meta.root = requested_root`。
不改这两处，任何 root 都会被 hub 覆盖，info.json 检查永远看到旧内容。

## 1. parquet 必须 fixed_size_list<float32>（pyarrow 写）
pandas 默认把 list 列写成 `list<element: double>`（或 float64），datasets 库 cast 到
`List(Value('float32'), length=N)` 抛 `CastError: Couldn't cast ... list<element: double>`。
用 pyarrow 显式 schema 写：
```python
schema = pa.schema([
    pa.field("observation.state", pa.list_(pa.float32(), 6)),
    pa.field("action", pa.list_(pa.float32(), 6)),
    pa.field("episode_index", pa.int64()),
    pa.field("frame_index", pa.int64()),
    pa.field("timestamp", pa.float32()),
    pa.field("next.reward", pa.float32()),
    pa.field("next.done", pa.bool_()),
    pa.field("next.success", pa.bool_()),
    pa.field("index", pa.int64()),
    pa.field("task_index", pa.int64()),
])
table = pa.Table.from_arrays([
    pa.array([pa.array(s, type=pa.float32()) for s in states], type=pa.list_(pa.float32(), 6)),
    ...
], schema=schema)
pq.write_table(table, DATA / "file-000.parquet")
```
`next.reward/done/success`、`index`、`task_index` 必须都有——info.json features 也必须列全
（缺 `index`/`task_index` 报 "column names don't match"）。

## 2. frame_index 全局 / timestamp episode 内相对（2026-08-02 终极修正）
- `frame_index` = 全局帧号（0..N-1，按视频合并顺序），**不是**轨迹内索引。torchcodec 用
  `frame_indices = round(ts * average_fps)` 读帧；若用轨迹内索引，多轨迹合并后必然超界
  （实测 IndexError: frame index=517/580/602 > 515）。
- **`timestamp` 必须 episode 内相对（i/30.0），不是全局！** `dataset_reader._query_videos`
  会把 `ep[f"videos/{vid_key}/from_timestamp"]` 加到查询 ts（shifted_query_ts）——若 ts 已是
  全局绝对时间戳，再加 from_timestamp = **双重偏移** → 帧号翻倍（实测 1286 = 643×2，
  `Invalid frame index=1286 must be less than 515`）。相对化后 reader 自动加 from_timestamp
  = 全局正确位置。症状：单帧读取 OK、`ds[i]` 读中后段才报超界、episodes 过滤（如
  episodes=[18]）时更明显。
- episodes 表的 `videos/observation.image/from_timestamp` = `start/30.0`、
  `to_timestamp` = `(start+L-1)/30.0`（全局累加），不是每条从 0。
- episodes 索引列（dataset_from_index/dataset_to_index/data·video 的 chunk/file_index/
  meta/episodes/*）必须 `astype("int64")`，否则 `Unknown format code 'd' for object of type 'float'`。

## 2b. episode_index 必须连续编号（IDLE 过滤后）
IDLE 帧过滤后包索引不连续（缺 ep15），episodes 文件若保留原始 si → LeRobot 用位置索引
查 episodes → `Invalid key: 24 out of bounds for size 24`。修复：build 用独立计数器 ep_idx
连续编号（0..N-1），数据 parquet 与 episodes 文件都用它；空包（全 IDLE）不 append。
IDLE 帧特征：label 含 "IDLE" 且 action==state（值完全相同）→ 无训练价值，直接 continue。

## 3. 视频：file-000.mp4 + .metadata，帧数必须=parquet 帧数
- 文件名必须 `videos/observation.image/chunk-000/file-000.mp4`（不是 episode_000000.mp4）。
- `file-000.mp4.metadata` 内容为每帧索引一行（0..N-1）。
- **ffmpeg 合并丢帧坑**：`-vsync cfr -r 30` 会把 jpg 序列 515 帧压成 514 帧 mp4
  （metadata 514 行）→ torchcodec 读末帧超界。必须 `-vsync 0 -fps_mode passthrough`
  保留全部帧。验证：`ffprobe -count_frames` 帧数 == parquet 行数 == metadata 行数+1。
- 只保留有图的帧（camera_b64 有效 JPEG 才入帧，`Image.open().verify()` 验证），
  否则 mp4 与 parquet 帧数不一致 → FrameTimestampError / IndexError。

## 4. info.json 必备字段
```json
{"codebase_version": "v3.0", "robot_type": "...", "total_episodes": N, "total_frames": N,
 "total_tasks": 1, "chunks_size": 100, "fps": 30,
 "splits": {"train": "0:N"},
 "data_path": "data/chunk-000/file-000.parquet",
 "video_path": "videos/{video_key}/chunk-{chunk_index:03d}/file-{file_index:03d}.mp4",
 "features": {"observation.image": {"dtype":"video","shape":[H,W,3],"fps":30,
               "names":["height","width","channel"],
               "video_info":{"video.fps":30.0,"video.codec":"h264","video.pix_fmt":"rgb24",
                             "video.is_depth_map":false,"has_audio":false}},
              "observation.state": {...}, "action": {...},
              "episode_index": {"dtype":"int64","shape":[1]}, "frame_index": {...},
              "timestamp": {...}, "next.reward": {...}, "next.done": {...},
              "next.success": {...}, "index": {...}, "task_index": {...}}}
```
`meta/tasks.parquet` 必须存在（`pd.DataFrame([{"task_index":0,"task":"reach",
"language_instruction":"reach target"}]).to_parquet(...)`），缺了报 FileNotFoundError。

## 5. 加载验证（每个数据集构建后必做）
```bash
rm -rf ~/.cache/huggingface/datasets ~/.cache/huggingface/hub   # 清缓存，否则读到旧 schema
PYTHONPATH=src .venv/bin/python -c "
from lerobot.datasets.lerobot_dataset import LeRobotDataset
ds = LeRobotDataset('lerobot/pusht', root='data/<name>')
print(ds.num_frames, ds.num_episodes)
item = ds[ds.num_frames-1]   # 末帧必读，超界问题只在末帧暴露
"
```
`IsADirectoryError: ... videos/observation.image/chunk-000` 是视频路径模板不符的噪音警告，
不影响 state/action 加载，但训练会因帧数不匹配崩——必须修到帧数严格一致。

## 6. ACT delta 查询边界
ACT 训练时 delta_timestamps 会查未来 7 帧（+7/30 s），query_indices clamp 到 ep_end-1，
不会真超界。**真正的超界根因是 §2 的 timestamp 双重偏移**（timestamp 全局化 + reader 加
from_timestamp）——修复 timestamp 相对化后，单合并视频 + 多 episode 即可稳定训练
（实测 957帧/24轨迹 全量训练通过）。无需每包独立视频。若仍遇边界问题，再考虑
- 方案2：每包一个独立视频文件（episode_XXXXXX.mp4 各自），episodes 表各自指向。
- 或训练配置不把最后一个 episode 采完（留出 7 帧余量）。

## 7. metaworld MuJoCo 数据生成（WSL 实测）
- 渲染后端：**`DISPLAY=:0 MUJOCO_GL=glfw`**（WSLg 的 X server）。egl/osmesa 在 WSL 无 GPU
  上下文会失败（`mjr_makeContext` FatalError / glGetError NoneType）。
- metaworld MT1('reach-v3')：action_space 是 **Box(4,)** = dx,dy,dz+gripper（不是 6D！），
  state qpos 16D，取前 7 = Sawyer 关节角。动作传 6D 报 `AssertionError: Actions should be size 4`。
- 专家策略：末端 site 位置朝 goal site 移动（`env.data.site_xpos[env.model.site("goal").id]`），
  速度 `delta/norm * min(norm, 0.08)` + gripper 0 → 100% 非零动作帧。
- 生成脚本：`tools/gen_metaworld_data.py`（渲染→128x128 jpg→ffmpeg 合并 mp4→parquet/info/stats）。
- 生成的 info.json 若被旧内容覆盖（state shape 变 2），是 §0 的 hub 覆盖 bug，不是脚本问题。

## 8. 图像有效性判别
- 采集数据 camera_b64 可能是 **64x64 缩略图**（视觉训练质量差）；归档快照是 **318x180 高清**。
  要高清训练数据：按时间戳把归档快照融合进采集帧（包 meta.time + 帧相对 timestamp = 绝对时间）。
- 纯色/占位帧判别：`np.unique(arr.reshape(-1,3), axis=0)` 唯一色数 >500 = 真实场景，
  ==1/<50 = 纯色测试帧。MSE≈0 且成功率 100% 先查动作幅度（reach 任务 ±0.01 正常）和图像
  是否全黑（var=0），别当模型神了。
