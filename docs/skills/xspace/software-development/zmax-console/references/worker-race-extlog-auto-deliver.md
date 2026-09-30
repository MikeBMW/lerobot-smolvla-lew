# worker 竞态 / 跨线程崩溃 / 外部日志监视 (2026-08-06 实测, 五模型自动交付链路)

**触发**: 五模型自动流程 (ZMAX_AUTO_RUN=1: 启动自动加载五模型→▶运行→训练完自动
rollout+PDF+发飞书) 卡住 / GUI 崩溃 / 终端无输出时。

## 1. worker 终止竞态 → 五模型队列卡死
**症状**: 训练曲线停在某模型 (如 SmolVLA+LEW), 无任何训练子进程, 按钮停"运行中",
后续模型 (VLA-Touch) 永远不启动。
**根因**: `_done`(主线程, QueuedConnection) 触发 `_flow_next` 时, 上一个 CICDWorker
线程刚 emit 完 finished_ok 还在收尾, `isRunning()` 短暂 True → 防重入误拦截下一个
训练 → 队列 pop 了但任务没启动, 卡死。
**修复**: 4 处防重入 (`_start_canvas_flow` / `_start_worker` / `_run_full_flow` /
`_run_node_stage`) 统一改:
```python
w = getattr(self, "_worker", None)
if w is not None:
    if w.isRunning() and not w.wait(300):   # wait(300) 等正常收尾放行
        self._log(self._busy_hint())
        return
```
wait(300) 内正常终止的 worker 放行 (竞态解决), 真卡死才拦截。

## 2. threading.Thread 直接操作 Qt 控件 → GUI 静默崩溃
**症状**: GUI 进程退出, stdout 只有 Qt 警告 (Unknown property / stylesheet), **无
Traceback**。崩溃点在自动交付阶段 (训练完成后)。
**根因**: `_auto_finalize_work` / `_send_file_to_feishu_work` /
`_send_report_to_feishu_work` 在 `threading.Thread` 里直接 `self._log()`
(QTextEdit.append) — 跨线程操作 Qt 控件非法。
**修复**: 加 `_safe_log`, 后台线程方法内全部 `_log` → `_safe_log`:
```python
def _safe_log(self, msg):
    try:
        from PyQt5.QtCore import QMetaObject, Qt, Q_ARG
        QMetaObject.invokeMethod(self.log_box, "append", Qt.QueuedConnection, Q_ARG(str, msg))
        QMetaObject.invokeMethod(self.log_box.verticalScrollBar(), "setValue",
                                 Qt.QueuedConnection,
                                 Q_ARG(int, self.log_box.verticalScrollBar().maximum()))
    except Exception:
        pass
```
排查原则: GUI 静默退出且正在跑 threading.Thread 后台任务 → 先怀疑跨线程 Qt 访问。

## 3. 命令行后台训练日志不进 GUI 终端 (老倪: "我看着GUI界面呢, 终端得有东西啊")
**用户偏好: 训练/交付日志必须在 GUI 终端区可见, 不要只在后台跑**。命令行
`bash zmax_train*.sh` / `zmax_deliver*.sh` 的输出在日志文件, GUI log_box 看不到
→ 用户以为卡死。
**修复**: simulink_module.py `__init__` 末尾调 `_start_ext_log_watch()`:
```python
def _start_ext_log_watch(self):
    self._ext_log_pos = {p: 0 for p in ("/home/xspace/zmax_train4.log",
                                        "/home/xspace/zmax_deliver_latest.log")}
    if getattr(self, "_ext_log_timer", None) is None:
        from PyQt5.QtCore import QTimer as _QT
        self._ext_log_timer = _QT(self)
        self._ext_log_timer.timeout.connect(self._poll_ext_log)
    self._ext_log_timer.start(2000)

def _poll_ext_log(self):
    _keep = ("loss", "step=", "✅", "❌", "===", "完成", "📈", "训练",
             "epoch", "it/s", "step/s", "curve")
    for p, pos in list(getattr(self, "_ext_log_pos", {}).items()):
        if not os.path.exists(p): continue
        sz = os.path.getsize(p)
        if sz <= pos: continue
        with open(p, encoding="utf-8", errors="replace") as f:
            f.seek(pos); chunk = f.read()
        self._ext_log_pos[p] = sz
        for ln in chunk.splitlines():
            if not ln.strip() or ln.startswith("+ "): continue   # set -x 噪音
            if any(k in ln for k in _keep):
                self.log_box.append(ln.rstrip()[:200])
    self.log_box.verticalScrollBar().setValue(self.log_box.verticalScrollBar().maximum())
```

## 4. ZMAX_AUTO_RUN 自动交付链 (端到端)
- studio.py `__init__` 尾部: `if os.environ.get("ZMAX_AUTO_RUN") == "1": QTimer.singleShot(2500, self._auto_run_compare5)`
- `_auto_run_compare5`: 切 Simulink 页 → `_qmsg_yes` 自动点 → `open_compare5()` → `QTimer.singleShot(1200, start_sim)`
- `_flow_next` 队列空分支: `if ZMAX_AUTO_RUN==1 and not _auto_finalize_done: _auto_finalize()` (后台线程: rollout 5 模型→ffmpeg mp4→xstack 拼接→generate_report.py→发飞书)
- 飞书发送细节 (file_type=stream / chat_id / xstack 纯数字 layout) 见 zmax-model-compare-report 飞书 API 章节
- **训练步数多处联动**: simulink_module.py 模板 `"steps": N` (17 处) + node_logic.py 默认 + train_*.py argparse default + config yaml; `diffuse_steps` 是扩散采样步数不是训练步数, 批量替换别误伤
