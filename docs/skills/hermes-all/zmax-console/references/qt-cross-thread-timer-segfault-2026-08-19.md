# 跨线程 QTimer Segfault 根治 (2026-08-19)

## 症状
```
QObject::killTimer: Timers cannot be stopped from another thread
QObject::~QObject: Timers cannot be stopped from another thread
Fatal Python error: Segmentation fault
```
崩溃特征: 运行 ~10 分钟后崩; faulthandler dump 里 main 线程在 app.exec_()、无 Python 栈
(崩在 Qt C++ 层)。此崩溃 08-18 崩 2 次、08-19 崩 3 次 — 同源反复。

## 根因
**QTimer.singleShot(0, lambda) 从子线程调用**: singleShot 内部 timer 无 parent,
在**调用线程**创建 → 子线程退出/GC 时销毁 → Qt 跨线程 killTimer → SIGSEGV。
本会话实锤两处:
- `studio.py _on_ws_status` (WSClient on_status 回调, WS 线程) → singleShot 回主线程
- `studio.py _cam_apply_later` (摄像头探测/轮询子线程) → singleShot 回主线程

另一变体: `_oneshot(parent,...)` 从子线程调用 → QTimer(parent) 跨线程**创建** →
`Cannot create children for a parent that is in a different thread` 刷屏
(MonitorModule._refresh_orin_status 的后台线程调 _oneshot)。

## 修复: _oneshot 桥 (studio.py 顶部, 模块级)
```python
from PyQt5.QtCore import QObject as _QObjectS, pyqtSignal as _pyqtSignalS

class _OneshotBridge(_QObjectS):
    sig = _pyqtSignalS(object, int, object)

_oneshot_bridge = _OneshotBridge()
_oneshot_bridge.sig.connect(lambda p, m, f: _oneshot(p, m, f))

def _oneshot(parent, ms, fn):
    if QThread.currentThread() is parent.thread():
        t = _QTimerS(parent); t.setSingleShot(True)
        t.timeout.connect(fn); t.start(ms); return t
    _oneshot_bridge.sig.emit(parent, ms, fn)  # QueuedConnection 自动 → 主线程创建
    return None
```
要点:
- 子线程调 _oneshot → 信号 QueuedConnection 自动派发回 **parent 所在线程**创建
- timer 挂 parent → 主线程创建/销毁, 从根上杜绝 killTimer 跨线程
- 主线程调 _oneshot 走原路径 (零开销)
- 注意: PyQt5 的 QMetaObject.invokeMethod **不接受 Python callable** (实测 TypeError)
  → 桥接信号是正解

## 排查路径 (下次复现直接用)
1. faulthandler 只给 Python 栈; C 层崩溃 → 用 gdb:
   `bash tools/gui/studio_gdb.sh` (gdb -batch -ex run -ex "thread apply all bt full"
   --args python studio.py) → /tmp/studio_gdb_<时间>.log
2. 全仓搜从子线程调用 singleShot/_tq/_oneshot 的路径:
   `grep -n "singleShot" tools/gui/*.py`, 逐个判断调用线程 (WS 回调/轮询线程/worker)
3. 崩溃后画面损坏 (连线"消失"/残留)  ≠ 数据问题 — 离屏验证:
   `QT_QPA_PLATFORM=offscreen` 加载画布 JSON, 数 `_link_items` 与 links 是否一致

## 同类坑
- `faulthandler.dump_traceback_later(20, repeat=True)` 每 20s 的
  "Timeout (0:00:20)!" + 线程栈 = **正常诊断输出, 不是崩溃**, 勿误判
- `_QT.singleShot(800/5000, ...)` (训练完成回调) 已全部改 _oneshot 挂 parent
- relay_middleware 纯 Python 线程 (无 QObject) 是安全的, 别误改
