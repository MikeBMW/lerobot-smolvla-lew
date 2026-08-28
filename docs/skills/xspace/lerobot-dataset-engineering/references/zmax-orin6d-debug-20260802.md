# Z-MAX orin_6d 数据集构建调试实录 (2026-08-02)

真实会话中逐个击破的 LeRobot 数据集错误链, 按出现顺序。每个错误 → 根因 → 修复。

## 背景
Orin 真机采集 JSON 包 (6D state/action + 320x240 JPEG base64) → 构建 LeRobot 数据集
`data/orin_6d` → ACT 训练。数据包格式:
```json
{"meta": {"source": "orin", "frames": N, "n_joint": 6, "n_action": 6,
          "labels": {"等待测试结果": N}, "time": <绝对秒>},
 "frames": [{"observation.state": [6], "action": [6], "label": "...",
             "timestamp": <相对秒>, "camera_b64": "..."}]}
```

## 错误链

### 1. hub 覆盖本地 root
`LeRobotDataset('lerobot/pusht', root='data/orin_6d')` 把 pusht hub 数据 snapshot_download
到本地目录 → info.json 变 pusht (state shape [2], total_frames 25650), 数据目录被污染。
**修复**: lerobot_dataset.py + dataset_metadata.py 的下载处加:
```python
if (root / "meta" / "info.json").exists():
    # 跳过 snapshot_download
```
症状消失的关键判据: build 后 info.json 保持本地内容。

### 2. parquet float64→float32 cast 失败
pandas DataFrame 写 list 列 → pyarrow 推断 float64 + variable-length list → 加载报
"Couldn't cast ... from double to float32" 或 length=2 (pusht schema 缓存)。
**修复**: 显式 pyarrow schema, 全部 float32 fixed-list + int64 索引列:
```python
schema = pa.schema([
    pa.field("observation.state", pa.list_(pa.float32(), 6)),
    pa.field("episode_index", pa.int64()),
    pa.field("timestamp", pa.float32()),
    ...
])
```

### 3. IndexError: Invalid frame index=517/580/602/1388
多轮出现, 数值不同但模式一致 (查询帧号 > 视频帧数)。
- 517/580/602: **缓存残留** + 视频帧数 < parquet 帧数 (ffmpeg 丢帧)
- **1388 (>755) = 决定性根因**: timestamp 用了全局 (total/30.0), 而
  `dataset_reader._query_videos` 把 `episodes[...from_timestamp]` 加回查询 ts →
  from_timestamp + 全局ts = 双重偏移 → torchcodec round(ts*30) 帧号翻倍。
  **修复**: timestamp 改 episode 内相对 `i/30.0`; frame_index 保持全局 (视频合并顺序)。
  验证: `ds[i]` 对 i=0, mid, last 全部可读, timestamp 从 0 开始。

### 4. IndexError: Invalid key: 22 out of bounds for size 22
IDLE 帧过滤后某包 (ep15) 空 → episodes 表 episode_index 不连续 (0..24 缺 15) →
LeRobot 用位置索引 `episodes[ep_idx]` → 错位。
**修复**: build 时用独立计数器 ep_idx 从 0 连续重编号 (frames 和 episodes 都用),
不用原始包序号 si。

### 5. unsupported operand type(s) for /: 'str' and 'str'
auto_loop 守护里 `train()` 用 `glob.glob()` 返回 **str** 列表, 直接 `ckpts[-1] / "pretrained_model"`
→ str/str 崩溃 → **训练成功但上传环节静默失败** (守护自动上传从未成功, 全是手动 scp)。
**修复**: `ckpts = [Path(c) for c in ckpts if "last" not in c]`。

### 6. 训练中途 Invalid key (45%进度)
守护训练中, 新数据包到达 → 又跑 build_dataset → 删除正在训练的数据集 → 中途崩溃。
**修复**: 训练锁 LOCK 文件 (train 前 touch, finally unlink), 锁存在时新包跳过等下轮;
锁检查放在 `SEEN.add(latest)` 之前 (否则锁期间到的包被永久跳过)。

### 7. IDLE 帧污染
IDLE 标签包 action==state (机器人静止, 动作=当前状态) → 无训练价值且触发异常。
**修复**: build 时按 label 过滤 `"IDLE" in label.upper()`。

## 验证命令 (构建后)
```bash
ffprobe -v error -count_frames -select_streams v:0 \
  -show_entries stream=nb_read_frames -of default=nokey=1:noprint_wrappers=1 \
  data/orin_6d/videos/observation.image/chunk-000/file-000.mp4
# 必须 == parquet 行数
python3 -c "
import pandas as pd
df = pd.read_parquet('data/orin_6d/data/chunk-000/file-000.parquet')
print(len(df), df['timestamp'].max())  # timestamp 应从 0 起相对
"
```

## 最终成果
957帧/24轨迹, episode_index 连续 0-23, timestamp 相对, 视频帧=parquet帧, loss 1.543。
