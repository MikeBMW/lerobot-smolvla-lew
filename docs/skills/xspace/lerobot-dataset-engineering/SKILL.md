---
name: lerobot-dataset-engineering
description: LeRobot 数据集构建坑 — timestamp相对/索引重编号/视频对齐/hub覆盖。训练数据出错时用。
---

# LeRobot 数据集构建 (踩坑全记录)

> 参考: `references/zmax-orin6d-debug-20260802.md` — Z-MAX 真机数据构建完整错误链实录
> (hub覆盖→cast失败→IndexError 1388→Invalid key 22→str/str→并发锁→IDLE过滤)

## 触发条件
用 LeRobotDataset / lerobot_train 训练时报错: IndexError 超界、Invalid key、
str/str、视频解码失败、数据集被覆盖。适用于任何 LeRobot fork 本地数据集构建。

## 核心规则 (按优先级)

### 1. timestamp 必须 = episode 内相对时间戳, 不是全局!
```
"timestamp": float(i / 30.0)   # i = 轨迹内帧号, 0, 0.033, 0.066...
```
**为什么**: `dataset_reader._query_videos` 会把 `episodes[videos/*/from_timestamp]`
**加回** 查询 timestamp (`shifted_query_ts = from_timestamp + ts`)。若 parquet 里已是全局
timestamp → 双重偏移 → `torchcodec` 帧号翻倍超界 (`Invalid frame index=1388 must be less than 755`,
`632=632` 边界案例)。相对 timestamp + reader 自动加 from_timestamp = 全局正确位置。

### 2. frame_index = 全局索引 (与 index 列一致)
视频是全局合并的单文件时, `frame_index` 必须是全局递增 (视频合并顺序), 不是轨迹内。

### 3. episode_index 必须连续重编号
过滤掉任何轨迹 (IDLE 帧、坏帧) 后, 包索引会不连续 (如缺 ep15) → LeRobot 用**位置索引**
`episodes[ep_idx]` 查 → 错位 → `IndexError: Invalid key: 22 out of bounds for size 22`。
**修复**: build 脚本用独立计数器 `ep_idx` 从 0 连续递增 (frames 和 episodes 表都用它),
不用原始包序号 si。

### 4. 视频帧数必须 = parquet 帧数
ffmpeg 合并 jpg → mp4 用 `-vsync 0 -fps_mode passthrough` 防丢帧; 之后必须校验
`ffprobe nb_read_frames == parquet 行数`。帧数不一致 → 最后几帧读取超界。

### 5. 图像只保留有效帧
无 camera_b64 的帧直接 `continue` 跳过 (不是存 None), 保证 mp4/parquet 帧数严格一致。
IDLE/空闲标签帧 (action==state) 也跳过, 无训练价值且污染模型。

### 6. hub 下载覆盖本地 root (LeRobot 已知行为)
`LeRobotDataset(repo_id, root=本地)` 会 snapshot_download 覆盖 root 目录 (包括 info.json
被 pusht 等 hub 数据替换 → 各种离奇错误如 length=2)。
**补丁**: `lerobot_dataset.py` 和 `dataset_metadata.py` 的下载逻辑里,
`root/meta/info.json` 存在时跳过 snapshot_download。补丁后 info.json 不再被覆盖。

### 7. parquet 必须 float32 fixed-size list
pandas 写 list 列默认 float64/list 无固定长 → cast 失败。用 pyarrow:
```python
pa.list_(pa.float32(), 6)   # 固定长度6
pa.field("episode_index", pa.int64())  # 所有索引列 int64
```

### 8. 训练守护必须防并发
守护进程训练中若新数据到达又重建数据集 → 正在训练的数据集被删 → 中途 `Invalid key`。
**修复**: 训练锁文件 (LOCK.touch()/unlink), 锁存在时新包跳过等下轮; 锁检查必须在
`SEEN.add(latest)` 之前 (否则锁期间到的包被永久跳过)。

### 9. glob 返回 str → `str / str` 崩溃
`ckpts = sorted(glob.glob(...))` 返回 str 列表, 直接 `ckpts[-1] / "pretrained_model"`
报 `unsupported operand str/str` → **训练成功但后续环节静默失败**。必须 `Path(c)` 转换。

### 10. gen_metaworld_data.py 生成器标准列 (2026-08-06, peg 场景踩坑)
数据生成器必须写全 LeRobot 标准文件, 缺一个就加载失败:
- **tasks.parquet** (`meta/tasks.parquet`): `{"task_index": [0], "task": [task_name]}` — 缺失报 DatasetGenerationError
- **episodes 列** (补在 eps_df 上): `dataset_from_index`/`dataset_to_index` (全局帧区间)、
  `videos/observation.image/from_timestamp` (0.0)/`to_timestamp` ((len-1)/fps)、
  `data/chunk_index`/`data/file_index`=0、`tasks`=0、`meta/episodes/chunk_index`/`file_index`=0
- **video_path 模板**: `"videos/{video_key}/chunk-{chunk_index:03d}/file-{file_index:03d}.mp4"`
  (不是 `videos/observation.image/chunk-000/` — 会 KeyError)
- **视频必须是 file-000.mp4 单文件** (不是每轨迹 episode_*.mp4): concat 合并
  `ffmpeg -f concat -safe 0 -i <(for f in episode_*.mp4; do echo "file '$PWD/$f'"; done) -c copy file-000.mp4`
  合并后 metadata 也拼接: `cat episode_*.mp4.metadata > file-000.mp4.metadata`
- **metadata 行数 = 视频帧数** (750帧视频 → metadata 750 行; concat 可能丢 5 行 → 重建
  `[str(i) for i in range(n_frames)]`)

### 11. info.json features 结构必须对齐旧数据集 (KeyError: 'names' / 'observation.image')
生成器写的 features 与 LeRobotDataset 期望不匹配 → `KeyError: 'names'` 或 `KeyError: 'observation.image'`:
```python
# 参考已能加载的旧数据集 (如 metaworld_cartesian) 覆盖:
feats["index"] = {"dtype": "int64", "shape": [1]}          # 无 names (names:null 会崩)
feats["task_index"] = {"dtype": "int64", "shape": [1]}
feats["observation.image"] = {                              # 需 names + video_info
    "dtype": "video", "shape": [128,128,3], "fps": 30,
    "names": ["height", "width", "channel"],
    "video_info": {"video.fps": 30.0, "video.codec": "h264", ...}}
```
修完 info.json 必须清缓存 (`rm -rf ~/.cache/huggingface`) 再验证加载。

### 12. 归一化 var 判定黑屏 (2026-08-06 认知修正)
LeRobotDataset 解码返回 **0-1 float32**, `img.numpy().var()` ≈ 0.066 **是正常图像**!
还原: `var * 255 * 255 ≈ 4318` 与 ffmpeg/PyAV 直解一致。判定标准:
- 归一化域: var > 0.02 且 mean 0.3~0.7 → 真图 (mean≈0.59, var×255²≈4300 实测正常)
- unique=1 且 var≈0.0001 → 黑屏
先用 `ffmpeg -i file.mp4 -frames:v 1 f.png` 直抽帧对比原始 var, 再判解码路径是否真坏。

### 13. 动作数据内容必须真实 (2026-08-06, "视频里机械臂不动"根因)
**症状**: 训练/加载全正常 (零报错), 但 rollout 视频里机械臂几乎不动 (视频对比"都差不多/没拿起来")。
**根因**: 生成器存的是**派生量**而非 env 实际执行的动作。
```python
# ❌ 坏: 存"每帧末端位移×fps" — metaworld 是速度控制, 每帧位移只有 0.01-0.03,
#    ×30 后动作仍被压到 std≈0.03 (几乎全零) → 模型学到"不动"
vel = (ee_after - ee_before) * 30.0
action = np.concatenate([vel, [gripper_cmd]])

# ✅ 好: 直接存专家策略输出 (速度指令), clip 到 env 范围与 step 实际执行一致
a4 = expert.get_action(obs_vec)          # 专家输出已是标准动作 (metaworld: delta_pos∈[-1,1])
action = np.clip(a4[:4], -1.0, 1.0)
```
**诊断**: 检查 parquet/rollout 的 actions 统计 — 正常专家数据 std≈0.3-0.7、|max|>0.5;
std<0.1 或 |max|<0.1 = 动作被压扁。rollout 的 `actions.npy` 同样可查:
```python
a = np.load("reports/rollout_<p>/actions.npy"); print(a.std(), abs(a).max())
```
模型学得好坏一眼可见: 专家 std 0.64 vs 60步模型 std 0.22 vs 压扁数据训的 std 0.05。
**教训**: 数据内容 (动作值域/分布) 与 env 语义必须一致, schema 正确 ≠ 数据正确;
视频对比前先看动作统计, 不要先怀疑模型/rollout 代码。

### 14. info.json features 必须声明 parquet 全部列 (CastError: "column names don't match")
parquet 有 `index`/`task_index` 列但 info.json features 没声明 → datasets 库 cast 失败:
```
CastError: Couldn't cast ... because column names don't match
```
**修复**: 补声明 (int64 列 names 可为 None, 不会崩 — 崩的是 video/image feature 缺 names):
```python
feats["index"]      = {"dtype": "int64", "shape": [1], "names": None}
feats["task_index"] = {"dtype": "int64", "shape": [1], "names": None}
```
注意区分: `KeyError: 'names'` 来自 feature_utils.py L153 对 **video/image** feature 读 `ft["names"]`
→ 必须给 `observation.image` 补 `"names": ["height", "width", "channel"]` (#11);
int64 列 names 缺失不触发, 但 CastError 会 (列没声明)。

### 15. config 的 episodes: [0] 只取 1 条轨迹 (训练不足陷阱, 2026-08-06)
config yaml 里 `dataset.episodes: [0]` 只加载 1 个 episode (如 180 帧) —
数据量小 loss 降得快但模型学不到完整动作 (夹爪永不闭合等)。**正式训练删掉
episodes 字段** (用全部轨迹); 快速验证链路才用 [0]。smolvla_lew config 该字段在
L36 附近, act/smolvla_lew 系检查时别漏。删后若报 CastError 检查 #14 (index/task_index 声明)。

### 16. 旧数据生成进程与重建竞争 (rm -rf 后旧进程仍在写)
先后台启动数据生成 (旧代码) → 改完生成器再 `rm -rf` + 重启新生成 → **旧进程可能还在
写同一目录** (生成完成通知晚到)。必须核对最终产物: info.json 是否新格式 (含 index/
names) + 视频是否 file-000.mp4 + 无 episode_* 残留 + 动作 std 正常 — 确认无污染再训练。

### 17. len(ds) 按 meta 帧数, 但 hf parquet 实际行数更少 (IndexError: 3608 out of bounds for size 3600, 2026-08-06)
**症状**: 训练数据采样 `ds[i]` 报 `Invalid key: 3608 is out of bounds for size 3600`
(VLA-Touch/AWE 1000 步训练失败)。**实测**: `len(ds)=4500` (meta 帧数) 但
`hf_dataset` 只有 3600 行 → 采样索引 ≥3600 全越界 (3608 恰是 step 采样的第一个越界点)。
**根因**: 数据集构建/过滤后 meta 帧数没同步 (部分轨迹写入失败或过滤后未更新 meta)。
**修复**: load_data 采样范围用 hf 实际行数截断:
```python
n = len(ds)
try:
    n = min(n, len(ds._ensure_reader().hf_dataset))   # hf 实际行数为准
except Exception:
    pass
step = max(1, n // max_frames)
idxs = list(range(0, n, step))[:max_frames]
```
**验证**: load_data 打印帧数应 = min(meta, hf 行数); 越界报错消失。坑: `len(ds)` 可信度
低于 `hf_dataset` 行数 — 训练数据出错先 `len(ds)` vs `len(ds._ensure_reader().hf_dataset)` 对比。

### 18. info.json 声明 ≠ 实际下载的数据 (metaworld_mt50 真相, 2026-08-07)
**症状**: 训练数据量小得离谱 (696 帧) 但 info.json 声称 25650 帧/206 episodes/49 任务。
**根因**: 数据集是**部分下载**——info.json/tasks.parquet 是完整数据集索引声明 (如 mt50:
2500 episodes/204806 帧/49 任务, chunk-{i:03d}/file-{i:03d}.parquet), 但本地只有
`chunk-000/` 的 2 个分片 (879 帧/10 episodes/**只有 task 0** = nut-on-peg)。
**探测实际**: 直接 `pd.read_parquet` 数行数/`df['task_id'].unique()`/`groupby('episode_index').size()` —
**别信 info.json 的 total_frames/total_episodes**。train.npz 的 696 帧 = `tools/ci/prepare_metaworld.py`
默认 `--max-files 2` 只读前 2 片转换 (图像缩到 128²)。
**success 标记认知**: metaworld parquet 的 `next.success` **只在 episode 最后一帧 =1**
(中间帧 0 = 任务进行中) → 1.1% 帧级成功率 ≠ 失败轨迹; 10/10 轨迹可能全成功。
**判别数据是否够学**: 插拔是长程任务, 10 episodes 不够; 要看 episode 数 × 每轨迹帧数,
不是 info.json 的声明数。

### 20. 下载数据任务不匹配 → 用官方专家策略生成任务专用数据 (2026-08-07 插销)
**症状**: 训练数据是 nut-on-peg (套环), 但评估/目标是 peg-insert-side (插销) — 老倪:
"不是插销的数据"。mt50 下载只含 task 0, 无插销轨迹。
**方案**: 用 metaworld 官方专家策略采样目标任务的成功轨迹 (distill_expert.py 已有范式):
```python
from metaworld.policies.sawyer_peg_insertion_side_v3_policy import SawyerPegInsertionSideV3Policy
mt = metaworld.MT1("peg-insert-side-v3", seed=0)
env = mt.train_classes["peg-insert-side-v3"](render_mode="rgb_array", camera_name="corner2")
# 每步: o=env._get_obs() (39D) → a=expert.get_action(o) → env.step(a)
# 只保留 inserted==True 轨迹 (peg抬升>0.05 + 距hole<0.05), 失败轨迹 150 步提前 break (渲染慢)
# 存 npz: observations (N,3,128,128) float32 + states 39D + actions 4D → train/val 8:2
```
- 实测: 30 成功 eps / 41 尝试 (73%, 官方 85% 接近), 5850 帧, ~8 分钟 (失败轨迹提前终止是关键提速)。
- **npz → lerobot 格式**: `tools/npz_to_lerobot.py --npz train.npz --out data/metaworld_peg_lerobot
  --task "..." --fps 10 --episode-frames 200` (每 parquet ≤1000 行, 生成 info.json+parquet)。
- **插拔成功检测** (评估, 别只看动作均值): rollout N 次, 每步 `env.data.site_xpos[site("pegGrasp").id]`
  抬升>0.05 + 距 `site("hole")` <0.05 = 插入成功; 输出 ok/N。动作均值高 (0.56) ≠ 插入成功。
- **坑**: 训练 config 的 root 行是缩进的 (`  root: data/...`) — 任何 regex 探测要 `^\s*root:`。

### 22. gen_metaworld_data.py 多阶段专家阶段检测 3 个坑 (2026-08-08 长轨迹数据全丢弃/方向反排查)**症状**: 多阶段专家生成数据"完成(抓取成功 +0.105m)"但 parquet 里 peg 从未被抓起; 或手直接往 hole 方向走 (跳过抓取)。
1. **⚠️ lifted 判断用手高度 = 永远 True**: `lifted = ee[2] > target_hole[2] - 0.01` — 手初始 z≈0.155 已 > 孔高 0.121 → **一开始就"已抬起" → 跳过 Phase 1-3 直接转移**。修复: `lifted = peg_now[2] > peg_z0 + 0.04` (peg 相对初始升高 4cm 才算抓起), peg_now 每步 `env.data.site_xpos[pid]` 现场取。
2. **⚠️ peg/grasp_pt 每步必须重新获取**: 循环外取一次 `peg = site_xpos[pid]` → 手追着**旧 peg 位置**跑 (peg 被抓走/移动后 grasp_pt 过期) → 动作饱和 [1,1,1,-1] (vel 方向全 1)。修复: 每步 `peg_cur = env.data.site_xpos[pid_use]; grasp_pt = [peg_cur[0], peg_cur[1], peg_cur[2]+0.03]`。
3. **多阶段专家 vs 官方专家选择 (--far / --grab-only 强制多阶段)**: 官方专家远起点/只抓不插 (grab-only) 时状态机失效 → `use_official = expert_mode and expert is not None and not far and not grab_only`。但**手写多阶段专家抓取成功率本身低** (接近加速 0.3 太快 → 20 条全丢弃; 0.18 也一般) — **分段数据 (--stop-after-grab) 用官方专家 (12/12 抓起) 而非 grab-only 多阶段专家**。
**教训**: 生成器"成功判定" (抓取成功打印) 与 parquet 实际动作可完全脱节 — 生成完必须**抽查 parquet 动作** (夹爪闭合占比/前30步夹爪应为 0.0 张开、中段 -0.8 闭合、peg z 抬升) 再训练, 别信打印的"完成"。
**坑1 — 系统 python3 无 pandas/pyarrow**: GUI 用 `/usr/bin/python3` (有 PyQt5/numpy/PIL, 无 pandas/pyarrow) — 查看器读 parquet 内嵌图像 (`observation.image` = dict `{"bytes": PNG, "path": str}`) 会 `No module named 'pandas'`。**修: 加 npz 路径** (numpy 直读 `data/metaworld_act/train.npz` 的 `observations` (N,3,128,128) float32): `rgb=(arr.transpose(1,2,0)*255).astype(uint8)` → QImage; 悬停 tooltip 带 task/state/action。parquet 路径保留给有 pandas 的环境, npz 优先。
**坑2 — 查看器用 exec_ 模态 (WSLg 弹窗零容忍)**: `viewer.exec_()` 在 WSLg 下窗口不显示/假死 → 老倪\"没看到图片\"。改 `viewer.show()` 非模态 (记忆铁律: exec_ 模态假死非模态也禁小窗口不许弹)。
**坑3 — _is_cached 只查 HF 缓存 → 本地数据\"未下载\"**: 本地实际数据在项目 `data/metaworld_mt50/data/*.parquet` (不是 `~/.cache/huggingface/hub`) → 缓存列/信息弹窗误报\"未下载\"。修: metaworld_mt50 特判查项目目录; 信息弹窗加\"📁 本地实际数据\"块 (实际 episodes/帧数/任务数, pandas 读 parquet 数行), 与 HF 云端声明 (2500/204806/50 任务) 明确区分 — **老倪要看到\"实际\" vs \"声明\"的差异**。DatasetViewer 加 `local_root`/`local_npz` 参数 (repo_id==metaworld_mt50 时 studio 传入)。
**通用认知**: GUI 数据集管理面板的\"任务数\"列是写死的 HF 条目声明 (DATASETS 里 tasks: 50), 不是本地实际 — 显示 `50 · 本地1` (加 local_tasks 字段)。

**坑4 — npz 翻帧慢 1.5s/帧 = NpzFile 数组访问 lazy 解压 (2026-08-07 老倪\"点击下一帧,为什么这么慢\")**: `np.load()` 压缩 npz 返回 NpzFile, **每次 `d[\"observations\"]` 都从磁盘重新解压该数组** (165MB 压缩 npz ≈ 943MB 原始) → 每帧 1.5s。缓存 NpzFile 不够。**修: 首次 load 时把数组提取到内存 ndarray 一次**:
```python
if self._npz_cache is None:
    self._npz_cache = np.load(self.local_npz)
    self._npz_obs = np.array(self._npz_cache["observations"])  # 关键: 提取!
    self._npz_st = self._npz_cache["states"] if "states" in self._npz_cache else None
obs = self._npz_obs
```
实测: 首次 2s (解压一次) → 翻帧 0-1ms (快 1500 倍)。验证: 计时首次 <3s + 翻帧均值 <10ms。

**坑5 — 数据集自带 mp4 是 AV1 编码 → cv2 解码失败 \"帧 0 超出范围\" (2026-08-07)**: 数据目录有 `videos/*.mp4` 时 `_load_video_frame` 优先走 cv2 视频解码 — **系统 cv2 不支持 AV1 硬件解码** (日志 `Failed to get pixel format`) → 读帧失败 → 显示\"帧 0 超出范围\"。**修: 有 local_npz 时 npz 绝对优先于视频文件** (numpy 可靠路径):
```python
if self.local_npz and os.path.exists(self.local_npz):
    self._load_npz_frame(); return
```
npz 路径是 numpy 直读, 不受解码器影响。HF 云端数据集 (pusht 等 mp4) 仍走 cv2。

**坑6 — orin 纯状态 json 采集包查看 (2026-08-07 老倪\"orin 加载不上\")**: orin_live 是 `auto_*.json` 采集包 (meta: source/frames/n_joint + frames: [{observation.state, action}], **无图像**) — 查看器只认 npz/parquet/mp4 → \"加载不上\"。**修: `_load_json_package()` 分支** (local_root 有 *.json 且无 parquet/video 时): 显示包 meta (源/帧数/关节维) + 当前帧 state/action 数值文本 + ep_slider 切包 (maximum=包数-1) + frame_slider 切帧。纯状态数据就用文本展示, 别硬找图像。

**坑7 — 帧 180° 旋转必须按数据源条件, 不能全局统一 (2026-08-07 老倪两次反转)**: peg_v2/peg_lerobot 是 corner2 相机采集 (与 rollout 视频同源, 需 rot90 k=2 与视频方向一致); **metaworld_act 是 MT50 官方数据 (方向本来就对, 无条件旋转把它转反了)** → 老倪\"图像反了,要旋转180度\"又\"套环也反了\"。**修: 按 local_npz 路径条件旋转**:
```python
if \"peg\" in (self.local_npz or \"\"):
    rgb = np.rot90(rgb, k=2)
```
**教训: 数据集来源不同 (自采 corner2 vs 官方下载) 方向基准不同 — 旋转/方向处理先确认数据源, 别假设全局一致。**

**坑8 — 数据集管理重复行删减原则 (2026-08-07 老倪连删)**: ①同一批数据两种格式 (peg_v2 npz 源 / peg_lerobot lerobot 训练格式) 显示两行 → 老倪\"这俩有啥区别\" → **只留训练用的那行** (peg_lerobot), npz 中间产物不显示 ②本地 metaworld_mt50 行与 HF 云端条目重复 → 删本地行留 HF ③4 个 orin 子目录 (同一台 Orin 分阶段) → 老倪\"就一个orin,不都一样么\" → **合并一行** ④数据集管理\"任务数\"列误填帧数 (4800/696) → 本地单任务数据任务数列填 \"—\"。**原则: 一数据源/一任务只显示一行, 中间产物/旧版本不显示; 名称两行 = 中文名(上)+官方任务名(下)** (如 `📁 插销插拔\\npeg-insert-side-v3`)。

### 26. --tactile/--rel-vec 生成路径: 丢轨迹后三处元数据不重编号 (2026-08-09 触觉49D数据 Invalid key: 44 out of 44)
**症状**: `gen_metaworld_data.py --eps 50 --tactile` 生成"4500帧/30轨迹"后, VLA-Touch/AWE 训练
秒退 `IndexError: Invalid key: 44 is out of bounds for size 44` (idx 每次不同: 44/49/6864→44)。
**根因** (三处错位叠加, 单视频合并 + 丢失败轨迹路径特有):
1. **data parquet 的 episode_index 没随丢轨迹重编号**: 50 条尝试 → 44 条成功, 但 parquet 的
   `episode_index` 仍到 49 (有跳号), 而 episodes meta 只列 0-43 → reader 位置索引错位。
2. **episodes meta 的 `dataset_from_index` 全为 0-179** (生成器写死 `episode_index*steps` 未按
   实际成功轨迹累加) → 每 ep 帧区间全指同一段。
3. **info.json `total_frames` 用 50×180=9000, 实际 parquet 7920 行** (44×180) → `len(ds)` 按 meta
   9000, hf 表 7920, 采样索引 ≥7920 越界 (与 #17 同族但根因是 meta 没同步)。
4. **视频 frame_index**: 单视频全局合并时, 每 ep 的 `videos/.../frame_index` 必须是**全局段末帧号**
   (ep i → `i*180+179`), 不是 `length-1` (所有 ep 都是 179 = 指向同一帧)。
**修复**: 生成后必须抽查并修正——`pd.read_parquet` 数实际行数 → 重写 info.json total_frames/
total_episodes; episodes meta 按实际成功轨迹重排 (dataset_from_index 累加、frame_index 全局段末);
**⚠️ info.json features 的 state shape 也必须同步** (2026-08-10 实测): 49D 数据若 info 里还是
`features.observation.state.shape=[39]` → LeRobotDataset 加载报
`TypeError: Couldn't cast array of type ... to ...` → `DatasetGenerationError` (不是 IndexError,
别只查索引)。`shape=[49]` + `names.motors` 扩到 49 (39基础+6 rel+4 tac 名) + **stats.json 的
observation.state mean/std 也必须是 49 维** (否则归一化广播错位)。修完必须
`rm -rf ~/.cache/huggingface/datasets` 清 schema 缓存再验证。
**教训: 只要生成器有"丢弃失败轨迹"路径, data parquet + episodes meta + info.json 三处必须用同一个
成功轨迹列表同步重建** — 别信生成器打印的"完成 N 帧", 训练前 `len(ds)` vs `len(ds._ensure_reader().hf_dataset)`
对比 (不一致 = meta 未同步)。
**数据内容验证 (49D 触觉)**: 结构 = [0:39] 基础39D (hand/peg/hole 位置姿态) + [39:45] 相对向量
(hand→peg, peg→hole) + [45:49] 触觉 (3D 关节差分速度×10 + 1D 力=速度范数×25)。接触时刻特征:
接近移动时 force↑ (0.24), 接触减速时 force↓ (0.006) — 抽查 parquet 确认触觉段有动态, 别全 0。
**⚠️ gen_state_ctx 必须初始化 (2026-08-10 实测)**: `--tactile` 的触觉段依赖 `gen_state_ctx.prev_ee`
追踪上一帧末端位置 — 若 main() 开头没 `global gen_state_ctx; gen_state_ctx = type("Ctx",(),{})()`,
每帧 prev_ee 都 fallback 当前值 → 差分恒 0 → 触觉段全 0 (模型学不到接触时刻)。生成后抽查
tac 段非全 0 是必做验证 (全 0 = ctx 没初始化或没追踪)。

### 27. --w2cot 结构化标注 (49D→58D, 2026-08-10 W2-VLA 论文整合)
`gen_metaworld_data.py --w2cot` 在 49D 后追加 **9D W2-CoT 标注** (对标 W2-VLA 的 W2-CoT:
操作进度+物理转换线索+腕部证据, 供辅助监督塑造 latent 接口):
- [49:53] 阶段 onehot 4D (0接近 1抓取 2抬起 3插入) — 判定: `peg_z-peg_z0>0.02` 算抬起,
  抬起后 `d_ph<0.15` 算插入, 未抬起 `d_hp<0.08` 算抓取
- [53:56] 物理线索: contact(d_hp<0.05) / sliding(接触中peg_z变>0.01) / seated(d_ph<0.05且z稳)
- [56:58] 腕部证据: [d(hand,peg), d(peg,hole)]
实现 `tools/w2cot.py` 的 `w2cot_annotate()`; **坑同触觉**: contact/sliding 依赖跨帧状态
(prev_contact/prev_peg_z/peg_z0), 必须存 gen_state_ctx 模块级容器, 局部变量每帧重置 → 线索全 0。
**info.json 必须同步**: shape=[58] + names.motors 扩到 58 (39+6rel+4tac+9cot 名) + stats.json 58D —
漏 shape 报 `TypeError: Couldn't cast` (同 #26 的 49D 教训)。**验证**: 多帧抽查 phase onehot
切换 + contact 从 0→1 (接近到位) — 实测帧60 contact=1、帧120 插入 d_ph=0.009, 标注正确才算通。
**结论**: CoT 58D 对 BC 评估无提升 (0/8 与 45D/49D 相同) — 价值在给世界模型/RL 当决策标签,
不是 BC 输入维度; 详见 zmax-policy-training-eval "离散时序决策改造"。

### 28. LeRobot v3.0 新格式 + 数据集"加列改造" (2026-08-12, 39D→43D 触觉)
**v3.0 分块格式** (metaworld_peg 实测, codebase_version: "v3.0"): `meta/episodes/` 下是
`chunk-000`(**不是**每集一个 json), `data/chunk-000/file-*.parquet`(每文件 1000 行) —
dataset_check/遍历脚本要 glob `data/chunk-*/file-*.parquet`, 别按旧版 `meta/episodes/*.json` 数集数。
**已有数据集加列改造** (给 metaworld_peg 加 observation.tactile 4D → metaworld_peg_tac):
```python
import pyarrow.parquet as pq, pyarrow as pa
for f in sorted(glob.glob(src/"data/chunk-*/*.parquet")):
    t = pq.read_table(f)
    states = np.asarray(t.column("observation.state").to_pylist(), dtype=np.float32)
    tac = synth_tactile(states)                      # (N,4) float32
    t = t.append_column("observation.tactile", pa.array(tac.tolist(), type=pa.list_(pa.float32())))
    pq.write_table(t, dst)                            # 输出路径保持 chunk-*/file-* 结构
```
三处 meta 同步 (缺一训练报错): ① `meta/info.json` 的 `features["observation.tactile"] =
{"dtype":"float32","shape":[4]}`; ② `meta/stats.json` 加该列 mean/std/min/max (训练归一化用,
**读输出 parquet 而非源文件** — 源文件没有新列会 ArrowInvalid No match); ③ `videos/` 软链到源数据集
(磁盘铁律, 别复制): `os.symlink(abspath(src/videos), out/videos)`。
**39D 合成触觉 4D 启发式** (metaworld 无 GelSight, 从 state 推导): t0=1-gripper(夹持力),
t1=1/(1+5d)(接触力, d=|peg−hole|), t2/t3=(peg−hole) 方向 x/z。产物: data/metaworld_peg_tac
(24 集 4800 帧, state 39+4=43D); 画布 State Adapter in/out 43D, obs 节点改名 43D。
**教训**: 加列改造后验证用 pyarrow 读输出 parquet 断言列存在 + info/stats 同步; 别信脚本 print。

## 验证流程 (构建后必做)
```python
from lerobot.datasets.lerobot_dataset import LeRobotDataset
ds = LeRobotDataset(repo_id, root='data/xxx')
assert ds.num_frames == parquet行数
for i in [0, num_frames//2, num_frames-1]:  # 首/中/尾帧必须能读
    ds[i]
```
末尾帧读不了 = 视频帧数 < parquet 帧数 (检查 #4)。
中途报超界 = timestamp 非相对 (检查 #1) 或视频帧数不符。

**动作值域检查 (2026-08-06 新增)**: 构建后必查动作分布, 否则可能训练出"不动"模型:
```python
import numpy as np
acts = np.stack([ds[i]['action'] for i in range(min(300, len(ds)))])
print(acts.std(), abs(acts).max())   # 专家数据应 std>0.3, |max|>0.5; <0.1 = 被压扁 (#13)
```

## 缓存清理 (训练失败秒退时)
```
rm -rf ~/.cache/huggingface ~/.cache/datasets
```
datasets 库按 parquet 内容 hash 缓存 schema, 数据重建后旧缓存会导致 index 超界。

## 常见错误速查
| 错误 | 根因 | 修复 |
|---|---|---|
| IndexError frame=1388 > 755 | timestamp 全局+from_timestamp 双重偏移 | timestamp 改相对 (#1) |
| Invalid key: 22 > 22 | episode_index 不连续 | 独立计数器重编号 (#3) |
| str/str 除法 | glob str / 路径 str | Path(c) 转换 (#9) |
| length=2 schema 冲突 | hub 覆盖 info.json | 本地 info.json 跳过下载 (#6) |
| IsADirectoryError 视频 | 视频路径/文件名不匹配 | 检查 file-000.mp4 存在+帧数一致 |
| 训练中途 Invalid key | 并发重建数据集 | 训练锁 (#8) |
| CastError "column names don't match" | parquet 列 (index/task_index) 未在 info 声明 | info features 补声明 (#14) |
| KeyError: 'names' | video/image feature 缺 names | observation.image 补 names (L153) (#11/#14) |
| 视频机械臂不动/动作全零 | 动作存派生量 (位移×30) 被压扁 | 存 clip(专家指令), 查 actions std (#13) |
| loss 降得快但夹爪不闭合 | episodes:[0] 只训 1 条轨迹 | 删 episodes 字段全量训练 (#15) |
| 重建后格式/动作异常 | 旧生成进程与重建竞争同目录 | 核对 info/视频/动作, 无残留再训 (#16) |
| Invalid key: 3608 > 3600 | len(ds) 按 meta 帧数, hf 表行数少 | 采样范围 min(len(ds), hf行数) (#17) |
| Invalid key: 1800 > 1015 | episodes parquet length 未随截断更新 | 重建 episodes + info splits (#23) |
| 长轨迹训完全模型 0% | 接近+插入方向相反 → BC 学平均=不动 | 分段数据/相对向量/夹爪辅助 (#24) |

### 23. 截断数据 (--stop-after-grab) 三处元数据必须同步 (2026-08-08 连踩 4 次 IndexError)
**症状**: 生成器 "完成" 但训练 `Invalid key: 1800 out of bounds for size 1015`。
**根因**: 截断后实际帧数 < 300, 但三处元数据仍是旧值 → reader 按 300 定位超界:
1. **meta/episodes/.../file-000.parquet** 的 `length` 列 — 生成器写死 `args.steps`; 修复:
   `actual_len = len([f for f in all_frames if f["episode_index"]==ep])` 再 append。
2. **meta/info.json** 的 `total_frames`/`total_episodes`/`splits` (train: 0:N) —
   生成器不更新 → 手动 `pd.read_parquet` 数实际行数改写。
3. **丢弃轨迹后 episode_index 重编号** (0..N-1 连续) + 数据 parquet 同步重编号。
4. **episodes parquet 需 15 字段** (LeRobotDataset 硬读): `episode_index/length/tasks/
   videos/observation.image/chunk_index|file_index|chunk-000/index|from_frame|file_index/
   data/chunk_index|file_index|chunk-000/index|from_frame|file_index/
   meta/episodes/chunk_index|file_index`。缺 `videos/.../file_index` 报 KeyError。
5. **45D state 数据** (39D+6D 相对向量): info.json `features.observation.state.shape=[45]`
   必须同步, 否则 CastError。
6. 改完必须 `rm -rf ~/.cache/huggingface/datasets` 再验证加载 (datasets 缓存旧 schema)。

**截断不生效的 4 个附加坑 (2026-08-08 同场踩完, "轨迹还是 300 帧"排查)**:
1. **官方专家路径有自己的 append+continue, 截断检测必须写进该路径内**: use_official 分支
   (gen 里 ~L135-166) 单独 `env.step` + `all_frames.append` + `continue` — 循环开头的
   `grabbed_frames >= 30: break` 被 continue 跳过 → 截断永不触发。修: 官方专家路径内
   也写截断检测 (锁存+每帧+1), **append 后、continue 前** 加 break 检查。
2. **主 env 必须 camera_name="corner2"** (不只是验证 env): 无 corner2 官方专家时序乱
   (抓取轨迹不同, 截断点对不上)。`env = mt.train_classes[task](render_mode="rgb_array",
   camera_name="corner2")`。
3. **抓取阈值 +0.04 太高**: 实测 peg 抓起瞬间只升 +0.035 (peg_z 0.065 vs 阈值 0.07) →
   永不触发。用 `peg_z_now > peg_z0 + 0.03`。
4. **锁存后每帧必须无条件 +1**: `grabbed = max(grabbed, 1)` 只在 peg 升高时执行, peg
   持续被抓住时每帧走该分支 → grabbed 永远是 1 不增长。修: 锁存 if 后**另起一个
   `if grabbed >= 1: grabbed += 1`** (两个独立 if, 不是 elif)。

### 24. 长轨迹数据 → 行为克隆平均化 (2026-08-08 全模型 0% 根因, 最重要教训)
**症状**: ACT/SmolVLA/LEW/VLA-Touch/AWE 用 300 步完整轨迹 (接近→抓取→转移→插入) 训练后
评估全 0% — 连接近都不会 (距 peg 反而增大 = 后退), 输出恒定"平均动作"。
**根因**: BC 回归目标 = 每步动作的期望; 轨迹里"接近(朝peg)"与"插入(朝hole)"方向相反,
各 150 步 → 平均 ≈ 0/后退 → 模型学到"不动"。
**免疫者**: MLP 蒸馏 (39D 坐标→动作直接映射, 每步独立决策, 不受时序平均化影响) — 唯一成功。
**解法组合** (全做才有效):
1. **分段数据**: 只保留"接近+抓取"段 (官方专家 + `--stop-after-grab` 抓起后 30 帧即停),
   方向一致 → 模型学到明确方向。
2. **相对向量 (目标条件化)**: state 加 6D = [peg-hand, hole-peg] (45D), 模型每步知道目标
   相对位置 — 这是 MLP 成功的关键, 喂给视觉大模型补足图像 3D 定位不足。
3. **夹爪辅助 grip_assist**: 评估/推理时接近 <8cm 规则闭合夹爪 (位置 RL 学, 夹爪规则触发)。
   夹爪是离散决策 (只有 -1/0.6 两档), 回归学不会 → 真实机器人就是"位置伺服+力控夹爪"混合。
**教训**: 纯 RL (PPO) 学稀疏抓取也失败 (奖励 -9.9 卡住, warm-start 后仍 0) — 稀疏离散奖励
是 RL 的死穴, 规则夹爪 + 连续位置 RL 才是出路。视频方向: 用户确认原版不旋转; 若用户说
"反了" → `ffmpeg -vf "transpose=2,transpose=2"` 整体转 180 (画面+框一起)。

### 25. 评估管道 4 大坑 (2026-08-08 全模型假 0% 排查, eval_insert.py)
模型评估 0% 先查这 4 个, 全是"模型没动"假象的根源:
1. **归一化 stats 必须按模型加载**: 每模型 checkpoint preprocessor 的 mean/std 不同
   (逐维 39/45D vs ACT 旧标量广播)。`_load_stats(policy_name)` 按模型映射 ckpt 路径;
   标量→广播, 逐维→直接用; VLA-Touch/AWE ckpt 无 preprocessor → 直接用数据 stats.json。
2. **图像尺寸按模型**: SmolVLA 视觉输入 64×64 (siglip_image_size=64), ACT 128×128。
   喂错尺寸 → 视觉编码全错 → 输出乱。
3. **diffusion 模型 (AWE/VLA-Touch) 输出是归一化空间**: 必须 `act*std+mean` 反归一化再
   env.step; ACT/SmolVLA 的 select_action 同样返回归一化动作。漏反归一化 → 动作全错。
4. **45D state 评估补相对向量**: st_dim==45 时现场算 [peg-hand, hole-peg] 拼到 39D 后,
   不能只切 39 (形状 (1,39) vs 权重 45 报 mat1/mat2 错)。
**验证**: 单步打印模型输出 real 动作 — 恒定值 = 学成平均动作 (查数据 #24);
变化但方向错 = 反归一化/归一化错位 (#25)。
