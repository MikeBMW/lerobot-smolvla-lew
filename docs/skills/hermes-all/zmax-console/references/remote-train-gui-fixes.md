# 远程训练 GUI 侧修复（2026-08-09 实测：Model Zoo 队列误判 + 子线程日志丢消息）

模型引擎远程容器训练（`--runtime nvidia --gpus all` + `remote_train_entry.py`）联动 GUI 时踩的两个大坑。完整远程链路见 `mlops/docker-gpu-training/references/remote-model-pullback-render.md`。

## 1. Model Zoo 队列误判"完成"循环刷屏

**症状**：日志每 15 秒重复 `🏁 Model Zoo 完整训练完成` + `📤 自动交付: 生成 rollout 视频 + PDF 报告 → 飞书…`（老倪"你都显示自动交付了，怎么回事"）。

**根因**：`_zoo_next` 用 `pgrep -f lerobot_train` 判训练是否完成——**远程容器训练时本地无 lerobot_train 进程** → 每 15s 轮询都走"队列空/训练完成"分支 → 无限触发自动交付。

**修复三件套**（studio.py `_zoo_next` + 提交处）：
1. **防重复交付标志** `_zoo_finalized`：完成分支开头 `if getattr(self, "_zoo_finalized", False): return`（已交付过不再重复），首次置 True
2. **远程等待** `_zoo_remote_wait`：`on_train` 返回 `(True, "xxx 容器化远程提交")` 时设 `self._zoo_remote_wait = pol`；`_zoo_next` 开头若该标志存在 → SSH 查远程 `docker ps -q --filter name=zmax_train`，容器在跑则 `return`（等下一轮），容器没了才置 None 推进队列
3. **新一轮重置**：提交前 `self._zoo_finalized = False`

**规则：远程容器训练模式下，队列推进判定查远程 docker 容器，不靠本地 pgrep**。

## 2. 子线程日志丢消息 — 队列 + flush（推翻 singleShot 方案）

**症状**：点「容器同步」只见 `🐳 容器同步开始…` 再无下文（老倪"没反应"），线程里后续日志全丢。

**根因**：`_log` 非主线程分支用 `QTimer.singleShot(0, lambda t=text: self._append_log(t))`（或 `QMetaObject.invokeMethod`）跨线程调度——**PyQt5 实测会丢消息**（offscreen 复现：monkeypatch `_log` 直接 append 全出，原始 singleShot 路径只出第一条）。

**修复——队列 + 主线程定时 flush**：
```python
def _log(self, message):
    ...
    if _th.current_thread() is _th.main_thread():
        self._append_log(text)
    else:
        self._log_queue.append(text)   # 非主线程只入队

# __init__（log_text 创建处）:
self._log_queue = []
self._log_flush_timer = QTimer(self)
self._log_flush_timer.timeout.connect(self._flush_log_queue)
self._log_flush_timer.start(200)

def _flush_log_queue(self):
    q = self._log_queue
    if q:
        self._log_queue = []
        for t in q:
            try: self._append_log(t)
            except Exception: pass
```

**验证**：offscreen 实例化 TrainingModule + **零 monkeypatch `_log`**（只包 `_append_log` 记录）+ 8s 事件循环 → 断言子线程日志全部出现（开始→检测远程→✅可达→查询镜像→🎉无需上传）。

## 3. 远程训练完自动拉回模型（GUI 侧入口）

- 触发：`_poll_remote_log` 容器退出分支调 `_pull_remote_model()`
- **注意：控制台 QTimer 拉流线程可能没在跑**（训练由看护脚本/其他窗口提交）→ 拉回不自动触发 → 手动执行同一套逻辑（scp + 写 `reports/train_curve_<policy>.json` + 注册 `models/saved/registry.json` + 回填 `ckpt_edit`）
- **`train_curve_<policy>.json` 的 ckpt 字段必须含 `/checkpoints` 层**（rollout 拼 `base/last/pretrained_model`），否则 rollout 报 `FileNotFoundError: checkpoint 不存在`
- **DatasetModule 启动崩溃**：拉回目录 checkpoints 下只有 `last/`（无数字目录）→ `max([])` 崩 → 空列表回退 0 + try/except（`_refresh_train_results` 1418 行附近）
