# 远程训练拉回模型 + 无头渲染 + 监控看护（2026-08-09 实测）

Z-MAX 远程 GPU 训练全链路收尾：训练完自动拉回模型 → 模型引擎可见可编辑路径 → Simulink 推理/报告/仿真视频。本文是 `docker-gpu-training` 的补充细节。

## 1. 远程训练完成自动拉回（_pull_remote_model）

**触发点**：`_poll_remote_log` 检测到容器退出（`docker ps -q` 空）→ 自动调用 `_pull_remote_model()`。
但注意：控制台窗口的 QTimer 拉流线程可能没在跑（训练由看护脚本/其他窗口提交时）→ 拉回不自动触发。
此时手动执行同一套逻辑即可（scp + 写 json + 注册），无需重启控制台。

**链路三件套**（本地目标结构必须匹配 rollout 查找逻辑）：

1. **scp 拉回 checkpoint**：
   - 远程找最新输出目录：`ls -dt ~/lerobot-smolvla-lew/outputs/train/<cfg_full>_* | head -1`（注意 cfg_full 带 `config_` 前缀，因为 output_dir sed 用的是完整 cfg 名 → `config_act_metaworld_<ts>`）
   - 远程找 checkpoint：`ls -d <rdir>/checkpoints/*/pretrained_model | sort | tail -1`（优先 last，或数字步数）
   - scp 到本地：`outputs/train/<name>_<ts>/checkpoints/last/pretrained_model`（`name` 是去 config_ 前缀的）
2. **写 `reports/train_curve_<policy>.json`**：
   - **ckpt 字段必须指向 `outputs/train/<name>_<ts>/checkpoints`（含 checkpoints 层）**！
   - rollout_video.py 逻辑：`base_dir = ROOT + ckpt` → `cands = [base/last/pretrained_model, base/000150/...]` → `os.path.isdir(pm)` 判存在
   - 若 ckpt 只写顶层目录（`.../<name>_<ts>`），容器内 `os.path.isdir(base/last/pretrained_model)` = False → `FileNotFoundError: checkpoint 不存在`
   - policy 名映射：ACT→act、SmolVLA→smolvla、SmolVLA+LEW→smolvla_lew、VLA-Touch→vla_touch、AWE→awe_zflow、MLP蒸馏→expert_mlp、官方专家→expert_policy
3. **注册 `models/saved/registry.json` + 回填模型引擎 `ckpt_edit`**：
   - registry 项：`{"name", "policy", "ts", "path": <本地 base>, "remote": "<host>:<远程 ckpt>"}`
   - `ckpt_edit.setText(pm)` + `_refresh_saved_models()` → 用户在下拉可见、路径可编辑

**DatasetModule `max([])` 启动崩溃**：拉回目录 checkpoints 下只有 `last/`（无数字步数目录）→
`max([int(b) for b in os.listdir(ck) if b.isdigit()])` 空列表 ValueError → 控制台启动即崩。
修复：空列表回退 0 + try/except：
```python
try:
    _nums = [int(b) for b in os.listdir(ck) if b.isdigit()]
    steps = max(_nums) if _nums else 0
except Exception:
    steps = 0
```

## 2. rollout 容器无头渲染（xvfb/EGL）

`rollout_video.py` 渲染 metaworld 视频需要显示环境，容器里两个坑：

- `MUJOCO_GL=glfw`（历史默认）需 X11 → 容器无显示报 `GLFWError: (65550) X11: Failed to open display :0`
- `MUJOCO_GL=egl` 需系统 `libegl1` → 否则 `AttributeError: 'NoneType' object has no attribute 'eglQueryString'`（PyOpenGL EGL 绑定加载失败）
- 改默认值：`os.environ.setdefault("MUJOCO_GL", "egl")`（代码里 glfw→egl）

**Debian 13 (trixie) 容器装渲染依赖**（zmax-std 基于 Debian）：
```bash
apt-get update && apt-get install -y libglfw3 libegl1 xvfb
# 然后 xvfb-run 无头渲染:
xvfb-run -a -s '-screen 0 1280x1024x24' python /app/tools/rollout_video.py --policy act ...
```

**`docker commit` 固化依赖的坑**：
- apt 安装是异步的，`which Xvfb` 成功 ≠ 全部装完（xvfb-run 可能还没落盘）——commit 前容器内确认 `which Xvfb xvfb-run` 都在
- commit 出 tag（如 `zmax-std:render`）后**用新 tag 起干净容器重新验证**（跑 xvfb-run 冒烟），别信原容器内验证
- 装依赖的容器如果 `docker run` 卡住超时（apt 慢），容器还在 Up → 直接 `docker exec` 确认后再 commit，别急着删

**注意**：本地 WSL 跑 rollout 时 zmax-std:1.0（无渲染依赖）也会崩 → 用 zmax-std:render 或先装依赖；
`rollout_final_act.mp4` 等旧视频文件存在不代表本次成功（看时间戳）。

## 3. 远程训练监控看护脚本（后台轮询模式）

用户要求"你盯着，断了找原因自动再运行"时的模式（`/tmp/watch_remote_train.py`，后台 + notify_on_complete）：

```python
while True:
    status = ssh('docker ps --filter name=zmax_train --format {{.Status}}')
    if "Up" in status:
        step = ssh('docker logs zmax_train 2>&1 | grep -oE "[0-9]+/2000" | tail -1')
        # 6 分钟无进展 → 强制重启
        if stall_n >= 6: ssh('docker rm -f zmax_train; docker run -d ...')
    else:
        step = ssh('docker logs ... | grep -oE "[0-9]+/2000" | tail -1')
        if "2000/2000" in step or "100%|" in step:
            break  # ✅ 完成
        ssh('docker rm -f zmax_train; docker run -d ...')  # 崩溃自动重启
    time.sleep(60)
```

**判断"完成"以日志最终步数为准**（`2000/2000` / `100%|`），不是容器退出本身（崩溃也退出）。
看护脚本监控期间，控制台窗口的拉流 QTimer 可能没触发 → 训练完手动执行拉回（见 §1）。

## 4. Model Zoo 远程队列误判"完成"循环（GUI 侧）

`_zoo_next` 用 `pgrep -f lerobot_train` 判本地训练——**远程容器训练时本地无此进程 → 每 15s 轮询误判"🏁 完成"并重复触发自动交付**（生成视频/PDF/发飞书刷屏，用户看到"你都显示自动交付了"）。

修复三件套（studio.py `_zoo_next` + 提交处）：
1. `_zoo_finalized` 标志：完成分支 `if getattr(self, "_zoo_finalized", False): return`，首次设 True——防 15s 循环重复交付
2. `_zoo_remote_wait`：on_train 返回 `("容器化远程提交", ...)` 时设 `_zoo_remote_wait = pol`；`_zoo_next` 开头若有此标志 → 查远程 `docker ps -q --filter name=zmax_train`，在跑则 return（等），容器没了才推进队列
3. 新一轮训练重置 `_zoo_finalized = False`

**规则：远程容器训练模式下，队列推进判定不能靠本地 pgrep——要查远程 docker 容器**。

## 5. 子线程日志丢消息 — 队列 + flush（GUI 侧）

PyQt5 下非主线程调 `QTimer.singleShot(0, lambda: ...)` / `QMetaObject.invokeMethod` 跨线程调度**会丢消息**：
用户点上传只见"🐳 容器同步开始…"再无下文，线程里所有日志全丢（offscreen 实测：monkeypatch `_log` 直接 append 正常，原始 singleShot 路径只出第一条）。

可靠方案——**队列 + 主线程 QTimer flush**：
```python
def _log(self, message):
    ...
    if _th.current_thread() is _th.main_thread():
        self._append_log(text)
    else:
        self._log_queue.append(text)   # 非主线程只入队

# __init__:
self._log_queue = []
self._log_flush_timer = QTimer(self)
self._log_flush_timer.timeout.connect(self._flush_log_queue)
self._log_flush_timer.start(200)      # 200ms flush

def _flush_log_queue(self):
    q = self._log_queue
    if q:
        self._log_queue = []
        for t in q:
            self._append_log(t)
```

验证：offscreen 实例化 + **原始 `_log` 路径**（零 monkeypatch，只包 `_append_log` 记录）+ 8s 事件循环 → 断言子线程日志全部出现（开始→检测→✅可达→查询→🎉无需上传 6 条）。
注意：这条**推翻了早期"singleShot(0) 回主线程"的建议**——singleShot 在真实 PyQt5 跨线程下不可靠。

## 6. ssh 远程命令 f-string 转义（三连败教训）

远程命令拼 f-string 时 awk/引号转义极坑：
- `\\$3`（源码 2 反斜杠）→ 渲染 `\$3` → shell 双引号内 awk 收到 `$3` ✓
- `\\\\$3`（4 反斜杠）→ 渲染 `\\$3` → awk 报 `unexpected character '\'` ✗
- patch 工具改写含反斜杠的 f-string 极易双重转义搞坏语法（`\"` ↔ `\\\"` 来回错）

**改这类行用 Python 字节级替换**（显式 `chr(92)` 拼反斜杠），或 `git checkout` 恢复后精确重建；
改完必须 `ast.parse` + **eval 该 f-string 验证渲染结果**（`eval(l.strip().rstrip(","))` 看实际字符串），别只看语法过。
