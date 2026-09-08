# 状态空间仿真操作视频导出 (gen_state_space_video.py)

2026-08-22 修复完整依赖链: PIL 缺失 + 中文字体路径失效 + ffmpeg 缺失。三件套缺一不可。

## 运行机制
- 由 `simulink_module.py::_start_video_export` 在 worker 线程里
  `subprocess.run([sys.executable, "gen_state_space_video.py", out])` 启动子进程。
- `sys.executable` = 当前 GUI 解释器 = **gui-venv311** (Py3.11), 不是系统 python3。
  → 依赖必须装在 gui-venv311, 不是系统 python3 (系统 python3 无 numpy 且无 PyQt5)。
- 输出 `reports/state_space_sim.mp4`, 上传 ECS datadrive.world 用 sshpass scp
  (密码 Nix19789 已失效 → 上传失败只打日志, 本地 mp4 仍在, 有兜底, 不影响使用)。

## 依赖链 (三件套)
1. **Pillow (PIL)** — 渲染帧。gui-venv311 默认只装 PyQt5+numpy+grpcio+protobuf, 没 Pillow。
   报错: `ModuleNotFoundError: No module named 'PIL'`。
   装: `~/.hermes/bin/uv pip install --python /home/ubuntu/lerobot-smolvla-lew/gui-venv311/bin/python Pillow`
2. **numpy** — 已在 gui-venv311 (2.4.x), 无需装。
3. **ffmpeg** — 合成 mp4。`sudo apt-get install -y ffmpeg` (6.1.1)。缺失时报
   `RuntimeError: ffmpeg 失败 rc=...` 或 ffmpeg not found。

## 中文字体路径坑 (已 patch, 勿再硬编码)
- 脚本原硬编码 `_FONT = "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"`,
  但 U盘 live 环境 **没有 wqy** (只有 NotoSansCJK)。`ImageFont.load_default()` 回退不支持中文 → 渲染成方块。
- 已改为候选列表 + `os.path.isfile` 探测, 顺序: wqy-microhei → wqy-zenhei →
  NotoSansCJK-Regular → NotoSansCJK-Bold → DroidSansFallbackFull → uming。
- **通用铁律**: 任何渲染中文字体的脚本 (视频/图), 字体路径必须
  `next((f for f in CANDIDATES if os.path.isfile(f)), CANDIDATES[0])` 探测, 不能硬编码单路径。
  (例外: PDF/reportlab 走 wqy-microhei, 见 SKILL 报告节 — 那是另一条渲染链)

## 验证
- 端到端: `gui-venv311/bin/python gen_state_space_video.py /tmp/test.mp4` → 成功
  h264 960x640, 300帧 12s, 仿真 7.86s 插入完成。
- 校验产物: `ffprobe -v error -show_entries stream=codec_name,width,height,nb_frames <mp4>`
