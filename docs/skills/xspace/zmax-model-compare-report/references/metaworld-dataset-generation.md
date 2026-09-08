# Metaworld 场景数据集生成完整清单 (2026-08-06 peg-insert-side-v3 实测)

生成器: `tools/gen_metaworld_data.py --task <MT1任务> --eps 5 --steps 150 --out data/<name>`
`DISPLAY=:0 MUJOCO_GL=glfw` 前置 (渲染必须)。

## 生成后必查 5 件事 (缺一即加载/训练失败)

### 1. tasks.parquet — 缺则 `FileNotFoundError: meta/tasks.parquet`
生成器**不写** tasks.parquet (旧 bug)。修复:
```python
import pandas as _pd
_pd.DataFrame({"task_index": [0], "task": [args.task]}).to_parquet(out / "meta" / "tasks.parquet")
```
(已在生成器补丁中加入)

### 2. episodes parquet 标准列 — 缺则解码 `KeyError: 'videos/observation.image/from_timestamp'`
必需列 (对照旧数据):
```
episode_index, length,
dataset_from_index, dataset_to_index,
data/chunk_index, data/file_index,
videos/observation.image/chunk_index, videos/observation.image/file_index,
videos/observation.image/from_timestamp (0.0), videos/observation.image/to_timestamp ((L-1)/30),
tasks, meta/episodes/chunk_index, meta/episodes/file_index
```

### 3. 视频合并 + metadata — 缺则加载失败或解码错位
- 生成器每轨迹一个 `episode_000000.mp4` → 必须合并为单文件 `file-000.mp4`:
  `ffmpeg -f concat -safe 0 -i <(for f in episode_*.mp4; do echo "file '$PWD/$f'"; done) -c copy file-000.mp4`
- metadata 也合并: `cat episode_*.mp4.metadata > file-000.mp4.metadata`
- **帧数校验**: `ffprobe -count_frames` 应 == metadata 行数 (concat 可能丢帧 → 重建 metadata: 写 0..N-1 每行一帧号)
- info.json `video_path` 必须 `videos/{video_key}/chunk-{chunk_index:03d}/file-{file_index:03d}.mp4`

### 4. info.json features — 缺则 `KeyError: 'names'` / `column names don't match`
- `index` / `task_index`: `{"dtype": "int64", "shape": [1]}` (**不要** `"names": null`)
- `observation.image`: 需 `"names": ["height","width","channel"]` + video_info (video.fps/codec)
- 偷懒法: 直接复制旧数据集 (如 data/metaworld_cartesian) 的 info.json 对应字段覆盖

### 5. stats.json 三件套 — 缺则 SmolVLA `KeyError: 'observation.image'` 或 MIN_MAX ValueError
```json
{
  "observation.state": {"mean": [...], "std": [...]},
  "action": {"mean": [...], "std": [...], "min": [...], "max": [...]},   // SmolVLA 要 min/max!
  "observation.image": {"mean": [0.485,0.456,0.406], "std": [0.229,0.224,0.225],
                        "min": [0,0,0], "max": [1,1,1]}                  // ImageNet 统计
}
```
- ACT config `use_imagenet_stats: false` → 不查 image 键
- SmolVLA/LEW config 必须 `use_imagenet_stats: true` (否则 factory.py L130 KeyError)

## 加载验证 (每次修完必测)
```bash
rm -rf ~/.cache/huggingface/datasets ~/.cache/huggingface/hub   # 防 repo_id 缓存 schema
.venv/bin/python -c "
from lerobot.datasets.lerobot_dataset import LeRobotDataset
ds = LeRobotDataset('lerobot/pusht', root='data/<name>')
print(len(ds))  # 应为 eps*steps
item = ds[10]; print(item['observation.state'].shape, item['action'].shape)
"
```
- **图像有效性判断**: 归一化后 var≈0.066 + mean≈0.59 = 真画面 (还原 var = var*255*255 ≈ 4300)。var≈0 且 mean≈0 才是黑
- repo_id 用 `lerobot/pusht` 占位 (root 指向本地), 不要用 `local/<name>` — 会被 datasets 库当 hub repo 拉取 (fork bug)

## 专家策略 — 朴素直线移动产生恒定 action (2026-08-06 实测大坑)
**症状**: 生成完成但 `action.std()` 全 ≈0 (如 [0.001,0.001,0.003,0]) — 数据无训练价值。
**根因**: 默认"朝 goal 直线移动"在 peg-insert 等接触任务上, 环境把末端速度衰减 (peg 每步移动仅 ~0.0004, 理论 0.08×1/30≈0.0027 的 1/7) → 150 步只走 0.15 → action 几乎恒定。

**修复: 多阶段专家策略** (Phase 1 快速接近 → Phase 2 缓慢插入+夹爪 → Phase 3 保持):
```python
# 目标用 hole site (peg 任务), 回退 goal
delta = target - ee
dist_xy = np.linalg.norm(delta[:2]); dist_z = abs(delta[2])
if dist_xy > 0.05:
    horiz = np.array([delta[0], delta[1], max(delta[2]-0.05, -0.05)])
    vel = horiz / max(np.linalg.norm(horiz), 1e-6) * 0.12   # Phase1 水平快进
    gripper = 0.0
elif dist_z > 0.03:
    vert = np.array([delta[0]*0.2, delta[1]*0.2, delta[2]])
    vel = vert / max(np.linalg.norm(vert), 1e-6) * 0.05     # Phase2 垂直缓插
    gripper = -0.5                                          # 夹爪闭合
else:
    vel = np.zeros(3); gripper = -1.0                       # Phase3 保持
action = np.concatenate([vel, [gripper]])
```
**生成后必检**: `action.std()` 每维 >0.01、夹爪维 unique 值数 ≥2 (0/-0.5/-1)、`np.unique(acts[:,3])` 多样 → 好数据。
(200 步版本实测 std=[0.05,0.018,0.022,0.469], 夹爪 3 档。)

## 典型任务参数 (MT1)
| 任务 | 特点 | AWE 适配 |
|---|---|---|
| reach-v3 | 单段短程 | 一般 |
| push-v3 | 单段推 | 不突出 (AWE 世界模型无用武之地) |
| **peg-insert-side-v3** | 对准→插入→力反馈 多阶段 | **最佳** (接触演化预测) |
