# 训练输出实时流式 + GUI 按钮操作 + Model Zoo 完整训练队列 (2026-08-08)

## 场景
老倪监控训练时要求：终端信息**详细不简化**（数据加载/模型加载/每步 loss 全打印）、**操作真实窗口按钮**（不能只在后台执行）、远程服务器**计时计费须快**。
两次报"卡住/怎么就一句话"的根因排查记录。

## 🐛 根因 1：python 子进程 stdout 块缓冲（非 tty）
Popen 管道模式下 python 进程 stdout 是**块缓冲（4K）**——输出攒满 4K 才 flush，日志区长时间无输出（看起来"卡住"）。
**修复：训练命令加 `-u`**（python 无缓冲）：
```python
["nice", "-n", "10", os.path.join(root, ".venv", "bin", "python"),
 "-u", "-m", "lerobot.scripts.lerobot_train", "--config_path", tmp_cfg]
```

## 🐛 根因 2：tqdm 用 `\r` 刷新不换行 → `for line in p.stdout` 永远等不到 `\n`
tqdm 进度条每帧 `\r` 结尾（无 `\n`），`for line in p.stdout` 卡住直到训练结束——监控者只看到启动日志后"又停止"。
**修复：块读 + 按 `\r`/`\n` 分行**（text=False 读 bytes，手动解码）：
```python
p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
buf = b""
while True:
    chunk = p.stdout.read(4096)
    if not chunk: break
    buf += chunk
    while b"\n" in buf or b"\r" in buf:
        if b"\n" in buf: line, buf = buf.split(b"\n", 1)
        elif b"\r" in buf: line, buf = buf.split(b"\r", 1)
        txt = line.decode("utf-8", "replace").rstrip("\r").strip()
        if not txt: continue
        log_signal.emit(txt[:600])   # 截 600 防超长，其余全量
        if line_hook: line_hook(txt)
```
验证（ad-hoc）：`bash -c "printf '1%%\\r2%%\\rDONE\\n'"` 应逐帧 emit（1% 和 2% 都在）。

## 老倪日志偏好（固化）
- 截断放宽：`txt[:600]`（原 200 被批"简化"）
- loss 行：`📈 {pname} {step}步 · loss {loss:.4f} · {原始行}`（原始行也带）
- 非 loss 行：原样完整打印（不 return 丢弃）
- 进度日志不再"每 10 步一行"——每帧都出

## Model Zoo 完整训练队列（训练按钮 → simulink on_train）
- 主窗口双向注入：`simulink.set_model_engine(model_engine)` + `model_engine.set_simulink(simulink)`
- `_start_training` 里 `if self._simulink is not None:` 优先走队列（**在 gpu_mode remote 分支之前**！否则远程分流永远不触发队列）
- 队列：`ZOO_POLICIES = ["act","smolvla","smolvla_lew","vla_touch","awe_zflow","expert_mlp","expert_policy"]`
- `_zoo_next()`：pgrep 轮询当前 lerobot_train 进程消失 → pop(0) 启动下一个；队列空 → `on_pdf_report()` + `on_infer_video()`（报告/视频对比，本地 reports/ + outputs/train/）
- 防重：`_zoo_queue` 非空时再点训练按钮 → 提示"队列已在进行中"
- 注意：on_train 用 `--config_path`（下划线）生成 config_act_runtime.yaml 等临时配置

## GUI 按钮操作（WSLg xdotool）
- WSLg 下 `DISPLAY=:0` 可用 xdotool（`sudo apt install xdotool`）
- 窗口定位：`xdotool search --onlyvisible ""` 遍历 getwindowname 找 "XSpace Studio — Z-MAX"
- 窗口标题带当前页名（如 `- [画布]`）——点导航/切换后标题会变，可作盲点迭代的判据
- 盲点风险：Qt 控件无窗口树，需坐标估算 + 迭代（点 → 查标题/日志 → 调整）
- 主窗口 = SystemSidebar（三层卡 layer_clicked→_on_nav）+ QStackedWidget

## 结果/数据同步铁律（老倪要求）
- 训练结果必须落本地控制台：outputs/train/<模型>_<ts>/ + reports/train_curve_<policy>.json + 视频
- 本地 4060 训练天然落本地；远程 V100 训练产物需回传/或确认输出目录挂载
- 磁盘红线严格监控：df 查本地（红线 80G；disk_redline.sh cron 每 2h 清，每目录只留最后 ckpt）
