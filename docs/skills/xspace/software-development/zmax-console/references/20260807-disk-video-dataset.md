# 磁盘铁律 + 视频/数据集管理修复 (2026-08-07 实测)

## 磁盘铁律 (老倪: "当前磁盘空间, 绝对不允许增加")
- **smolvla 系列 checkpoint 巨大**: 每 ckpt ~1.4GB, 4000 步训练存 ~25 个 = **35GB/模型** (smolvla_ft 35G、smolvla_lew_ft 37G 实测爆盘 133G/14%)。
- **每次训练后立即清中间 ckpt, 每目录只留最后**: `last=$(ls ck | grep -E '^[0-9]+$' | sort -n | tail -1); for c in ...; do [ "$c" != "$last" ] && rm -rf; done; rm -f last; ln -s $last last`。rollout 加载 glob 最新 + last 软链, 留最后不影响。
- 训练脚本 (resume_insert 等) 落盘前/后主动清理; 生成/采样临时输出用 /tmp 并跑完即删。
- 磁盘基线: 清理后 35-39G (5%); 一旦 >60G 立即排查 outputs/train 大目录。

## pkill -f 自匹配自杀 (反复踩)
`pkill -f 'studio.py'` 的命令行自身含 "studio.py" → **pkill 匹配自己 exit -15**, 可能没杀到目标。
- 用 `pkill -f 'studio.py'` 后必须 `ps aux | grep '[s]tudio.py'` 确认; 更稳: 先 `pgrep -af` 拿 PID 再 `kill <pid>`。
- 杀 GUI 想保训练 (续训链): 用 `kill -9 <gui_pid>` 跳过 closeEvent (closeEvent 会 pkill lerobot_train/cicd_pipeline, 把独立后台训练链也杀了)。

## 曲线 ts 与 _check_newer_ckpt 白屏链 (视频"闪一下/重新生成/白屏")
InferenceVideoDialog 打开时 `_check_newer_ckpt()`: 任一 train_curve json 的 ts 比视频帧 mtime 新 60s+ → 判定"新 checkpoint" → 自动 `_run_rollouts` 重新生成 → 生成中视频区空白/白屏。
- **坑**: 重写曲线 json 时 ts 写当前时间 → 误判 → 每次打开视频都触发重生成 (7 模型 ~15 分钟, 体验=白屏)。
- **修**: 曲线 ts 必须写**真实训练完成时间**; `_check_newer_ckpt` 加完整性保护 `if len(d.get("curve") or []) < 100: continue` (训练中断残留的 0-50 点曲线不算新 checkpoint)。
- 彻底解法: 训练/重 rollout 后帧 mtime 更新 → 不再触发。

## 视频对比对话框修复
- **标题水印**: 模型名标签原本在视频框上方 (视觉飘到上面窗口) → QGridLayout 同 cell 叠加 (`stack.addWidget(lab,0,0)` + `stack.addWidget(cap,0,0,Qt.AlignLeft|Qt.AlignBottom)`), cap 半透明底 `background:rgba(13,17,23,140)` + `WA_TransparentForMouseEvents`。
- **白屏**: `_tick` 里 `lab.size()`=0 (对话框未显示) 时 `scaled(0,0)` → 空白; 尺寸有效才 scaled, 否则 setPixmap 原图。
- **on_infer_video 的 have 检查必须含 expert 目录映射**: expert_mlp→rollout_mlp、expert_policy→rollout_expert_full (对话框 _load_frames 有 _dir_map 但触发前检查漏了 → 误判无帧 → 重新生成失败 → "视频没了")。

## 数据集管理 (studio.py DatasetModule) 修复
- **系统 python3 无 pandas/pyarrow** (GUI 必须系统 python3 因 PyQt5): parquet 内嵌图像读不了 → viewer 加 **npz 路径** (`numpy` 直读 `observations/states/actions`), `local_npz` 参数; 图像 CHW float(0-1) → HWC uint8 → QImage。
- **WSLg 弹窗零容忍**: `viewer.exec_()` → `viewer.show()` 非模态 (exec_ 假死)。
- **翻帧**: `_on_frame_changed` 只改 label 不加载图 → 加 `self._load_video_frame()` 触发; npz 用 `self._npz_cache` 缓存 (避免拖动每次 np.load 28MB)。
- **本地状态"未下载"错误**: metaworld_mt50 数据在项目 `data/` 不在 HF 缓存 → `_is_cached` 加 repo 特判; 信息弹窗加"📁 本地实际数据"块 (从 parquet 探测真实 episodes/帧数/任务, 与云端声明区分)。
- **当前训练数据集卡片**: `_current_dataset_html()` 从最近 config_*.yaml 的 `^\s*root:\s*(data/\S+)` (注意 **2 空格缩进**, 必须 `^\s*root:`) 探测 → 显示路径 + 插销/套环标签 + 帧数。

## 数据源与任务语义 (nut-on-peg vs peg-insert)
- `data/metaworld_act` (696 帧) = MT50 task 0 **nut-on-peg 套环** (非插销!); `data/metaworld_mt50` 只下载了 chunk-000 2 片 (879 帧/10 ep/1 任务, success 帧在 episode 尾部 0.99 = 全部成功轨迹, 不是 1.1% 失败)。
- 插销任务数据: `data/metaworld_peg_v2` (30 成功 eps/5850 帧含图) + `data/metaworld_peg_lerobot` (npz_to_lerobot 转换)。
- GUI 训练 placeholder 硬编码 data/metaworld_act — 要切插销数据需改 `_ensure_training_data` 或数据源切换。
