# LeRobot 数据集构建 (raw→标准格式) + metaworld 数据生成 + 边学边练闭环

2026-08-02 实测系列坑。覆盖: 从原始 JSON/仿真环境构建 LeRobotDataset 的全部格式要求、muJoCo/metaworld 无头渲染、笛卡尔接口跨机器人泛化、auto_loop 闭环守护。

## 一、LeRobot v3.0 数据集格式硬性要求 (缺一即 DatasetGenerationError)

### 目录结构
```
<root>/
  data/chunk-000/file-000.parquet      # 帧数据 (无图像列! 图像在 videos/)
  meta/info.json                       # 特征/统计/路径定义
  meta/stats.json                      # mean/std (必须与 shape 匹配)
  meta/tasks.parquet                   # task_index/task/language_instruction — 必须有!
  meta/episodes/chunk-000/file-000.parquet
  videos/observation.image/chunk-000/file-000.mp4 (+ .metadata)
```

### parquet 必须用 pyarrow 写 float32 fixed-size list
pandas 默认写 double → datasets 报 `Couldn't cast list<element: double> to List(Value('float32'), length=N)`。正确写法:
```python
import pyarrow as pa, pyarrow.parquet as pq
schema = pa.schema([
    pa.field("observation.state", pa.list_(pa.float32(), 6)),
    pa.field("action", pa.list_(pa.float32(), 6)),
    pa.field("episode_index", pa.int64()), pa.field("frame_index", pa.int64()),
    pa.field("timestamp", pa.float32()), pa.field("next.reward", pa.float32()),
    pa.field("next.done", pa.bool_()), pa.field("next.success", pa.bool_()),
    pa.field("index", pa.int64()), pa.field("task_index", pa.int64()),
])
table = pa.Table.from_arrays([
    pa.array([pa.array(s, type=pa.float32()) for s in states], type=pa.list_(pa.float32(), 6)),
    ...df['index'].astype('int64').values,
], schema=schema)
pq.write_table(table, path)
```
info.json `features` 必须含 `index` 和 `task_index` (与 parquet 列对齐)，否则报 "column names don't match"。

### episodes parquet 必备列 (全 int64，不能 float)
`episode_index, length, dataset_from_index, dataset_to_index, data/chunk_index, data/file_index, videos/observation.image/chunk_index, videos/observation.image/file_index, videos/observation.image/from_timestamp, videos/observation.image/to_timestamp, tasks, meta/episodes/chunk_index, meta/episodes/file_index`
- `dataset_from/to_index` 是**全局帧索引递增** (ep0: 0-149, ep1: 150-299...)，不是每轨迹 0 起
- `length` 必须与 parquet 实际帧数一致；索引列 `.astype('int64')` 否则 `Unknown format code 'd' for object of type 'float'`
- **帧 parquet 的 frame_index = 全局索引 (0..N-1, 视频合并顺序)**；timestamp = **episode 内相对 (i/30.0)**
- ⚠️ **最深的坑 (2026-08-02 通宵定位)**: timestamp 不能存全局 (total/30.0)。`dataset_reader._query_videos` 会把 ep 的 `videos/observation.image/from_timestamp` **加到查询 ts 上** — ts 若是绝对时间戳则双重偏移 → torchcodec `round(ts*fps)` 帧号翻倍 → 一系列幽灵 IndexError (517/580/602/632/1196/1388 全见过)。**最终正确组合: frame_index=全局 + timestamp=episode 内相对 i/30.0**, reader 自动加 from_timestamp 后=全局正确位置
- ⚠️ **IDLE 过滤后 episode_index 必须连续重编号** (0..N-1): 用包索引 si 会因过滤不连续 → episodes 表与数据错位 → `Invalid key: 24 out of bounds for size 24`。build 时用独立 ep_idx 计数器

### 视频必须是 file-000.mp4 单文件
LeRobotDataset 按 `video_path` 模板 `videos/{video_key}/chunk-{c:03d}/file-{f:03d}.mp4` 找文件 — **不支持 episode_XXXXXX.mp4 每轨迹多文件** (会 IsADirectoryError)。多轨迹合并:
```bash
ffmpeg -y -f concat -safe 0 -i vlist.txt -c copy file-000.mp4
# 写 file-000.mp4.metadata: 每行一帧 (0..total-1)
```
info.json `video_path` 用模板格式，`observation.image` feature 用 `video_info` 嵌套结构 (fps/codec/pix_fmt)。info.json 里的 `data_path`/`video_path` 若是 `file-{file_index:03d}` 模板形式会被当成 chunk 模板 — 固定格式 `data/chunk-000/file-000.parquet` 最稳。

### 最隐蔽的坑: snapshot_download 覆盖本地 root
`LeRobotDataset(repo_id, root=本地目录)` 的 `_download()` 和 `LeRobotDatasetMetadata` 都会对 root 执行 `snapshot_download(local_dir=root)` → **把 hub 上的 pusht 数据下载覆盖本地数据集** (info.json 变回 pusht 的 2D/25650帧/10fps)。修复 (已 patch 到 fork):
```python
# lerobot_dataset.py _download() 和 dataset_metadata.py 两处:
if (self._requested_root / "meta" / "info.json").exists():
    print("📂 使用本地数据集 (跳过 hub 下载)")
    self.meta.root = self._requested_root
else:
    snapshot_download(...)
```
症状识别: 构建后 info.json 又变回旧内容 / 加载出 25650 帧 pusht / `List(Value('float32'), length=2)` 缓存 schema 污染。每次构建后**验证 info.json 内容未被覆盖**。

### 其他
- `stats.json` mean/std 长度必须匹配特征 shape (state 3D → mean len 3)，否则 normalize_processor 报 tensor size mismatch
- 清缓存排障: `rm -rf ~/.cache/huggingface/datasets ~/.cache/huggingface/hub` (datasets 按 repo_id 缓存 schema，复用 `lerobot/pusht` 时被旧 schema 污染)
- LeRobotDataset 加载成功但图像解码 var≈0.1 是**解码路径问题**，不是数据问题 — 用 `av.open`/ffmpeg 直接验证 mp4 帧 var 正常即数据 OK

## 二、metaworld/MuJoCo 无头数据生成 (WSL)

环境: `.venv` 已有 mujoco 3.3.0 + metaworld。**WSLg 有 X server** (`/tmp/.X11-unix/X0`)：
```bash
DISPLAY=:0 MUJOCO_GL=glfw .venv/bin/python gen_metaworld_data.py
```
- EGL 在 WSL 无 GPU 上下文报 "OpenGL platform library has not been loaded"；osmesa 未装 → **用 glfw + DISPLAY=:0**
- 渲染: `env = mt.train_classes[task](render_mode="rgb_array")`; `img = env.render()` 返回 480x480 RGB (var~4300, 6000+色 = 真实画面)
- 动作空间: reach-v3 是 **4D** `(dx,dy,dz,gripper)` — `env.step` 断言 len(action)==4，6D 直接 AssertionError
- 关节状态: `env.data.qpos[:7]` (Sawyer 7关节 right_j0~j6)；末端/目标位置: `env.model.site("goal").id` + `env.data.site_xpos[...]` (无 site_names 属性)
- 专家策略(简单启发式): 朝 goal 移动 `vel = delta/|delta| * min(|delta|, 0.08)`

### 笛卡尔接口 = 跨机器人泛化的关键 (7轴→6轴)
Sawyer(7关节) → 珞石 SR5(6关节) **不能迁移关节角** (7D≠6D)，要迁移**任务空间**:
- state 用**末端 3D 位置** (x,y,z)，不用 7D 关节角 — 机器人无关
- action 用 4D 笛卡尔速度 (dx,dy,dz+gripper) — 机器人无关
- 部署端: 珞石有 `/robot/tcp_pose` 笛卡尔位姿 + 内部 IK → 4D 笛卡尔速度可直接执行
- 训出的模型: state[3]/action[4] — 用 `data/metaworld_cartesian` (10轨迹×150帧)

## 三、边学边练闭环守护 (tools/auto_loop.py)

老倪要求: 小芳边学边练→采集→静静训练→部署回 Orin→循环。守护模式:
```python
# 每60s poll /status; 新包 frames>=20 (别用50, 34帧的真实包会被跳过) 且 source!=orin_snapshot
# → GET /latest 拉取 → 存 data/orin_live/auto_*.json → build_orin6d_dataset.py
# → 训练 config_act_loop.yaml (独立 output_dir=act_loop, 否则 FileExistsError)
# → upload_model.py 推回 ECS → 小芳监听器自动部署
```
- 训练配置 output_dir 必须每次独立 (复用已存在目录报 FileExistsError)
- 数据源 JSON 帧结构: `{observation.state[6], action[6], label, camera_b64}`；`frame_index/timestamp` 可能为 None — build 时用循环 i 生成，不依赖帧内字段
- 状态确认: relay 队列空 + 无最新包 = 数据被消费完；Orin `infer_count` 不涨 = 推理服务未被调用

## 四、快照读取端点 (恢复实时画面)
- `GET /api/relay/cam/latest.jpg` (归档快照优先) + `GET /api/relay/cam/status`
- 别名 `GET /api/snapshot/latest` (小芳/web 建议命名): nginx 加 `location /api/snapshot/ { proxy_pass http://127.0.0.1:39053/api/snapshot/; }`
- 注意 nginx 正则 `~ \.jpg$` 会拦截带 .jpg 后缀的 API 路径 → `^~` 前缀匹配优先
- cicd.html 视频窗口由 web 维护；改页面后验证是否被 web 并发更新覆盖 (grep 现有实现再改)
