# 2026-08-07 视频对话框 + 数据集查看器修复

## 视频对比对话框 (InferenceVideoDialog, simulink_scope.py)
- **模型名标题叠加视频框左下角**: 老倪连续 3 次纠正"文本偏上/飘到上面窗口"。
  根因: 标题 QLabel 放在 box 布局顶部 → 视觉归属上一行窗口。终版: QGridLayout 叠加
  (lab 在 (0,0), cap 也在 (0,0) 带 `Qt.AlignLeft | Qt.AlignBottom`), cap 半透明深底
  (`background:rgba(13,17,23,140)`) 像水印 + `WA_TransparentForMouseEvents` 不挡操作。
- **打开视频"闪一下再次打开"根因**: `_check_newer_ckpt()` 把训练中断残留的残缺曲线
  (如 act 50 点/0 点, ts 却是新的) 误判为"新 checkpoint" → 每次打开自动 `_run_rollouts`
  重新生成 → 覆盖帧 → 视觉闪烁。修复: 曲线 `len(curve) < 100` 直接 continue
  (非正常 1000 步训练不算新)。教训: **train_curve json 是训练启动时清空的**,
  训练链中断会留下 0 点/几十点 + 新 ts 的残缺文件。
- **on_infer_video 的帧检查 (simulink_module.py) 要含 expert 目录映射**:
  `_dm = {"expert_mlp": ("rollout_mlp",...), "expert_policy": ("rollout_expert_full",...)}`
  与 `_load_frames` 的 `_dir_map` 保持一致, 否则 MLP/专家误判无帧 → 触发重新生成
  (rollout_video.py choices 不支持 expert → 失败) → "视频没了"。
- **白屏根因**: `_tick` 里 `lab.size()` 为 0 (对话框未显示) → `scaled(0,0)` 空白。
  修复: 尺寸有效才 scaled, 否则先 setPixmap 原图 (QLabel 自适应)。

## 数据集管理/查看器 (DatasetManager studio.py + DatasetViewer dataset_viewer.py)
- **"50 任务数"是 HF 云端声明, 不是本地实际**: DATASETS 条目 tasks 写死; 本地实际
  用 `local_tasks` 字段 + 表格显示 "50 · 本地1"。信息弹窗加 "📁 本地实际数据" 块
  (实际 episodes/帧数/任务, 从本地 parquet 读, 勿信 meta/info.json)。
- **"本地状态: 未下载" 错误**: `_is_cached` 只查 HF 缓存目录; metaworld 实际数据在项目
  `data/` → 加 repo_id 特判检查 `data/metaworld_mt50/data/*.parquet`。
- **查看器 exec_ 模态 = WSLg 弹窗禁忌**: `viewer.exec_()` → `viewer.show()` 非模态。
- **系统 python3 (/usr/bin/python3, GUI 用) 无 pandas/pyarrow**: 只有 numpy+PIL。
  查看器读 parquet 内嵌图像 (dict {"bytes":...}) 会 `No module named 'pandas'`。
  修复: DatasetViewer 加 `local_npz` 参数 → `_load_npz_frame()` 用 numpy 读
  train.npz (observations (N,3,128,128) float32 → transpose(1,2,0)*255 → QImage),
  加 `_npz_cache` 防拖动滑块重复 np.load 28MB。parquet 路径保留 (有 pandas 的环境可用)。
- **查看器翻帧**: `_on_frame_changed` 只改 label 不加载图 → 老倪"点不了下一帧"。
  修复: valueChanged 里 `self._load_video_frame()` (它内部路由 video/parquet/npz)。
- **数据源候选列表** (simulink_module.py `_show_source_info` cands) 记得加新数据目录
  (如 "data/metaworld_peg_v2"), 否则 GUI 切不到。

## 进程管理
- `pkill -f 'studio.py'` **自匹配自杀** (命令行含 'studio.py' 字符串 → exit -15),
  但也能杀掉目标; 确认用 `ps aux | grep '[s]tudio.py'`。
- **关 GUI 保训练**: 正常 SIGTERM 触发 closeEvent → pkill lerobot_train/cicd_pipeline
  (会杀续训中的训练); 只要关窗口不杀训练 → `kill -9 <pid>` 跳过 closeEvent。
- GUI 重启后 `auto_run` 触发训练的 busy 保护: 有 lerobot_train 进程时跳过 start_sim
  只加载画布; `ZMAX_AUTO_TRAIN=1` 才自动训练 (老倪: 训练已完成过一轮, 重启别再重训)。

## 续训 (resume) 陷阱
- lerobot fork 的 `resume: true` 机制要求 config_path 目录结构 (draccus), 直接
  `--config_path xxx.yaml --resume` 报 "A config_path is expected when resuming"。
- **可靠续训 = 微调**: `--policy.path=<ckpt>/pretrained_model` + 新 output_dir + steps
  4000, loss 从断点继续降; 曲线合并时**新训练 step 偏移 +1000** (新从 0 开始),
  setdefault 保留旧步。
- lerobot 日志 "step:1K" (1000 步) 会被正则解析成 step=1 → 先 `re.sub(r"step:(\d+)K", ...)`
  展开再解析; 正则 step 后加 `\b` 防 "1K" 匹配。
