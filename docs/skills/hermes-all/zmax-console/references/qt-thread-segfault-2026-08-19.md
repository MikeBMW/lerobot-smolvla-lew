# Qt 线程 Segfault 根治: QTimer/singleShot 跨线程 (2026-08-19)

## 根因链 (gdb 日志实锤, 08-18 崩过 2 次同源)
```
QObject::killTimer: Timers cannot be stopped from another thread
QObject::~QObject: Timers cannot be stopped from another thread
Fatal Python error: Segmentation fault
```
= QTimer 在子线程创建 (无 parent 的 QTimer.singleShot / 跨线程 parent),
子线程退出/GC 销毁 timer → Qt 跨线程 killTimer → SIGSEGV。表面: GUI 卡死/闪退。

## 高危模式: 子线程回调里 QTimer.singleShot(0, lambda) 回主线程
singleShot 内部 timer 无 parent、归属调用线程, 线程退出即崩。本会话抓到:
- `_on_ws_status` (WSClient on_status 在 WS 线程回调 → singleShot)
- `_cam_apply_later` (摄像头探测/轮询子线程 → singleShot)
- 训练完成回调 singleShot(800/5000) (主线程但统一改 _oneshot)

## 修复: _oneshot 跨线程桥接 (studio.py 顶部)
```python
def _oneshot(parent, ms, fn):
    if QThread.currentThread() is parent.thread():
        t = _QTimerS(parent); t.setSingleShot(True)
        t.timeout.connect(fn); t.start(ms); return t
    _oneshot_bridge.sig.emit(parent, ms, fn)   # 子线程 → 桥接信号
    return None
```
桥接: 模块级 `_OneshotBridge(QObject)` + `sig = pyqtSignal(object, int, object)`,
import 时创建 (主线程), connect 到 _oneshot。子线程 emit → 自动 QueuedConnection
→ 主线程执行 → 主线程创建挂 parent timer ✓ (创建/销毁/回调全在主线程)。

⚠️ PyQt5 `QMetaObject.invokeMethod` 不接受 Python callable (只收 str 方法名),
跨线程派发必须用桥接信号。

## 排查清单 (Segfault 复现时)
1. 日志找 killTimer / "Cannot create children for a parent that is in a different
   thread" (后者=子线程创建 QTimer(parent=主线程对象), 是前兆警告)
2. 搜所有子线程 (threading.Thread / QThread.run) 里的 QTimer/singleShot/_tq
3. 统一改 _oneshot; 主线程 singleShot 也改 _oneshot (挂 parent 防 GC 竞态)
4. faulthandler.dump_traceback_later(20, repeat=True) 已启用 — 崩溃全线程栈
   注意: 每 20s 的 "Timeout (0:00:20)!" + 线程栈是 faulthandler 正常诊断输出,
   不是崩溃; 崩溃特征行是 killTimer/~QObject/Fatal。

## 其他本会话 GUI 铁律 (2026-08-19)
- 导出/上传 (sshpass scp 最长 60s) 跑主线程 = 按钮假死 (gdb: selectors.py select)
  → threading.Thread + pyqtSignal 回主线程, 按钮置灰防重入
- QLabel 链接不可选: setTextInteractionFlags(TextSelectableByMouse |
  TextBrowserInteraction) + setOpenExternalLinks(True) + <a href> HTML
- VcXsrv XCopyArea 半移会复现 (会话状态相关): 滚动下半部残留 →
  scrollContentsBy 分块 repaint (400px/块; update 合并 region 失效, 必须 repaint)
- 状态空间画布增量修改铁律 (用户"不要改变已有框架"): flows/state_space_obs.json
  只追加节点/连线/端口, 画布 JSON 与模块库同源 (_load_state_space_library_group)
- 环境补装: torch CPU (download.pytorch.org/whl/cpu) + ultralytics 进 gui-venv311;
  torchvision 必须匹配 torch 版本 (--reinstall 强制), 否则
  "operator torchvision::nms does not exist"; websocket-client 供 relay WS
