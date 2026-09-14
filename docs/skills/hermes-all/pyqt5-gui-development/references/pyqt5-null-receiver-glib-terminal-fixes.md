# PyQt5 NULL receiver 崩溃 — 终局修复组合 (2026-08-18 第四轮: QT_NO_GLIB)

配合 `pyqt5-null-receiver-deep-dive.md` / `pyqt5-null-receiver-extra-fixes.md` 使用。前两轮修复后仍崩, 本文件是最后手段与负结果记录。

## 崩溃机制 (gdb 全栈定论)
- 崩溃栈恒为: `g_main_context_iteration` → `timerSourceDispatch` → `QTimerInfoList::activateTimers` → `QCoreApplication::notifyInternal2(QObject*, QEvent*)` SIGSEGV
- `info registers rdi` = **0x0** → notifyInternal2 收到 **NULL receiver** = Qt timer 表里**已删对象**的空条目（不是悬挂对象, 是表内残留）
- **宿主 = Qt 5.15.14 的 glib 事件循环集成**: activateTimers 由 glib 驱动, 一批 timer 同时激活时某个回调删了另一个 timer 的接收者, 批次继续分发 → NULL

## 终局修复: QT_NO_GLIB=1 (零成本, 直击宿主)
```python
# studio.py 顶部, QApplication 创建前 (PyQt5.QtCore import 之前即可)
import os as _os
_os.environ.setdefault("QT_NO_GLIB", "1")   # 强制 QEventDispatcherUNIX, 绕开 glib timer 批处理
```
- 之前已排环境变量: `QT_NO_DBUS=1` + `DBUS_SESSION_BUS_ADDRESS=/dev/null` — **无效 (负结果, 别重试)**: 10s 周期孤儿 QObject 依然在

## 10s 周期孤儿 QObject 的身份结论 (别再排查它)
- 深度识别法: eventFilter 孤儿分支加 `obj.metaObject().superClass().className()` + `obj.dynamicPropertyNames()` — **顶层 QObject 的 superClass() 返回 NULL, 对其调 .className() 抛异常 → 记录 super="?" 是正常现象, 不是对象损坏**
- **结论: 该孤儿活着、每 10s 激活自己的 timer 且不崩 → 不是崩溃源**。区分两种对象:
  - "活着激活的孤儿" (无害): 无 parent 的 Qt 内部单例, timer 正常触发
  - "已删对象的表残留" (崩溃源): rdi=0x0, 批次分发时拿到 NULL
- 崩溃时间规律提示业务逻辑 bug: 崩溃全在启动后 45s+ → 15s 周期 timer (Model Zoo 轮询) 误判"训练完成"触发自动交付线程 → 无训练时 `_zoo_start_ts` 守卫直接 return

## 修复链完整清单 (按投入顺序, 存活时长验证)
1. 所有 `QTimer()` → `QTimer(self)` 挂 parent (8 处)
2. 所有 `QTimer.singleShot` → 实例化 `_oneshot(self, ms, fn)` (17 处, 含 simulink_scope/dataset_viewer)
3. `QPixmapCache.setCacheLimit(0)` — QPMCache 内部清理 timer 孤儿
4. `QToolTip.setDuration(0)` — 10s 隐藏 timer 孤儿
5. 高频 timer 降频: hover 150→300ms, log_flush 200→500ms
6. `QT_NO_GLIB=1` (终局)
- 存活时长轨迹: 60-70s → 173s → 210s → (QT_NO_GLIB 待观察)。**每个修复用"崩溃前存活秒数"当验证指标**

## 监控工具链 (可复用)
- gdb 监控: `gdb -batch -x /tmp/gdb_cmds2.txt --args python studio.py` 后台跑; cmds2 含 `run` + `info registers rdi` + `x/8gx $rdi` + `thread apply all bt`
- TimerEvent 追踪器: app.installEventFilter, 每次 TimerEvent 记录 `时间戳 + C++指针(sip.unwrapinstance) + Python id + parent 链`; parent 链 ≤1 写 /tmp/orphan_timers.log
- sip API: `from PyQt5 import sip` (顶层 `import sip` 在 PyQt5 5.15.14 不存在); `sip.unwrapinstance` (小写 i, 无下划线 — `unwrap_instance` 不存在); **调试工具写完必须实测一次** (写错 → trace 0 字节静默失效)
