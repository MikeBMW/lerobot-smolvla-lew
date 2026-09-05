# 2026-08-07 控制台 GUI 修复补充 (示波器配色/重启保训练/数据集管理规范)

## 训练中重启 GUI 必须 kill -9 (跳过 closeEvent)
- GUI closeEvent 会 pkill `lerobot.scripts.lerobot_train` → **正常关闭/重启会杀掉正在跑的训练**
- 训练中要重启 GUI: `kill -9 <GUI_PID>` (SIGKILL 不触发 closeEvent → 训练独立进程存活)
- 注意 `pkill -f 'studio.py'` 的 bash 命令行自身含 "studio.py" 字符串 → pkill 自杀 (exit -15), 且可能没杀到 GUI → 用精确 PID `kill -9`

## 示波器 7 模型颜色 (simulink_scope.py)
- 根因: `_load_data` 里 `color = "act" if policy=="act" else ("smolvla" if ... else "smolvla_lew")` — **所有非 act/smolvla 模型 (vla_touch/awe_zflow/expert_mlp/expert_policy) 全归 smolvla_lew 紫色** → "示波器那么多紫色分不清"
- 修复: `_CMAP` dict 7 模型各一色 (act蓝/smolvla橙/smolvla_lew紫/vla_touch绿/awe_zflow亮红/expert_mlp天蓝/expert_policy金) + COLORS dict 补对应色; gt 色改粉 (避免与 vla 绿撞)
- 教训: 多模型曲线配色必须全量映射, 别用 if-else 链默认值

## 数据集管理 (DatasetModule) 最终规范
- **本地行两行命名**: `name = f"📁 {中文名}\n{官方任务名}"` (上行插销插拔/下行 peg-insert-side-v3) — 老倪"命名两行, 上面中文名/下面官方任务名"
- **任务数列**: 本地单一任务演示集 → "—" (别填帧数! 老倪:"为什么显示任务数4800个"); HF 云端多任务才显示真实任务数
- **eps 语义**: episodes = 演示次数 (一次完整操作轨迹); 帧数 = 这些演示总图像数
- **本地 vs 云端**: 本地行恒 "✅ 本地", 不查 HF 缓存; 下载按钮: orin 本地行 → "📥 CICD" 打开 https://datadrive.world/cicd.html (真机数据网页采集下载, 不是 HF!); 其他本地行 → 禁用 "本地"; 仅 HF 云端行走 HF 下载
- **_is_cached 递归 glob**: metaworld_mt50 parquet 在 chunk-000/ 子目录 → `glob(..., recursive=True)` 否则缓存列恒 "—"
- **data/ 清理原则** (老倪"没用的都删掉"): 中间产物 (npz 源已转 lerobot) 删、旧版本目录 (peg_v2/v3...v7) 删、被曲线 ckpt 引用的保留 (glob 兜底最新 = ft 目录); orin/closed_loop 老倪手动删 → 同步清理代码引用 (候选列表/采集包统计/查看器特判)

## patch 误删事故 (大文件纪律延伸)
- patch 替换时删一行会连带周边: 删 `dl_btn.clicked.connect` 时误删了 `manual_btn = QPushButton("📥 手动")` 创建行 → GUI 启动 NameError (manual_btn not defined)
- 教训: patch 删除/替换后立即 `grep` 确认周边符号仍定义; 改动后跑 offscreen 完整启动验证 (StudioMainWindow 构造不崩)
- 大段字符串重建 (execute_code) 截断过 studio.py → 恢复 = `git checkout tools/gui/studio.py` + 重应用未提交改动 (git HEAD 15:52 提交含当天大部分改动)

## 数据集查看器 (dataset_viewer.py) 格式支持链
- 加载优先级: **npz (numpy 可靠) > json 采集包 (orin_live 状态文本) > parquet (需 pandas, 系统 python3 无) > mp4 (AV1 硬件解码失败坑)**
- metaworld_act 视频 AV1 编码 cv2 解不了 → "帧 0 超出范围" → 有 npz 时 npz 优先
- NpzFile (savez_compressed) 数组访问 lazy 解压 → 每帧 1.5s → `_np.array(npz["observations"])` 提取到内存一次 → 翻帧 1ms
- 打开查看器自动加载第一帧 (QTimer.singleShot(0, ...)) — 否则 frame_slider maximum=0 "下一帧点不了"
- 图像方向: 插销数据 (peg_v2/peg_lerobot, 与视频同源) 需 rot90 k=2; metaworld_act (MT50 官方) 方向本来正确不转 — 按路径含 "peg" 条件旋转
