# dataset_viewer.py 查看器支持矩阵 (2026-08-07)

GUI 用**系统 python3**（有 PyQt5/numpy/PIL/cv2 5.0.0；**无 pandas/pyarrow**）→ 查看器数据源优先级：
`npz (numpy 直读) > json 采集包 (文本) > parquet (需 pandas, 系统缺 → 报错) > mp4 (cv2, AV1 解不了)`

## 加载分支顺序 (_load_video_frame)
1. `local_npz` 存在 → `_load_npz_frame`（**优先** — 绕开 AV1 视频解码失败 + parquet 无 pandas）
2. local_root 有 `*.json` 且无 parquet/video → `_load_json_package`（orin 采集包）
3. 有 parquet 无 video → `_load_parquet_frame`（系统 python3 会因无 pandas 报错 → 有 npz 就不走这）
4. cv2 mp4 解码（AV1 硬件解码不支持 → 失败 → 已被分支 1 拦截）

## 关键坑与修法
- **NpzFile lazy 解压**：`np.load(压缩npz)` 后 `d["observations"]` **每次访问重新解压** → 翻帧 1.5s/帧！
  修：首次 load 时 `self._npz_obs = np.array(d["observations"])` 提取到内存 → 翻帧 1ms。
- **AV1 mp4 解码失败**（metaworld_act 的 videos 是 AV1）→ "帧 0 超出范围" → 有 npz 时 npz 优先。
- **180° 旋转按数据集区分**：插销数据（路径含 "peg"）与视频同源需 `rot90(k=2)`；metaworld_act（MT50 官方数据）原始方向正确**不转** → 条件 `if "peg" in local_npz`。
- **打开即自动加载第一帧**：`QTimer.singleShot(0, self._load_video_frame)` — 否则 frame_slider maximum=0，"下一帧点不了"。
- **json 采集包**（orin_live: auto_*.json，meta{frames:150,n_joint:6} + frames[{observation.state, action}]，**无图像**）：`_load_json_package` 显示包名/meta/当前帧 state/action 文本；ep_slider 切包、frame_slider 切帧。

## 数据集管理列语义 (studio.py DatasetModule._local_datasets)
- **任务数列**：本地数据集是单一任务演示集 → 填 `"—"`（别填帧数！老倪抓过 "4800个" 错误）。
- **机器人列**：metaworld 数据 = `Sawyer (metaworld)`；orin = `Orin (真机)`。
- **描述列**：中文类型 + 帧数/演示数；orin json 包探测 `frames=f"{njson} 采集包"`（desc 拼接时避免 "包 帧" 叠字）。
- **去重**：peg_v2(npz源) 与 peg_lerobot(训练用) 同数据只留一个；orin 4 子目录(live/real_v1/archive/closed_loop) 合并一行。
- **MT50 HF 行 desc** 要写明"本地仅下载 task0 套环"（防误以为本地有 50 任务）。
- `_is_cached` metaworld_mt50 用**递归 glob**（parquet 在 chunk-000/ 子目录，`data/*.parquet` 匹配不到）。

## 环境依赖（GUI 系统 python3）
PyQt5/numpy/PIL/**cv2**（opencv-python 曾漏装，老倪: "怎么不提前安装"）— 一次装齐：
`python3 -m pip install opencv-python --break-system-packages`
