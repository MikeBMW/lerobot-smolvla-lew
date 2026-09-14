# PyQt5 NULL Receiver 崩溃深挖 (2026-08-18 Z-MAX 控制台第二阶段)

在第一阶段（无 parent QTimer 悬挂）修复后仍崩，深挖出的 Qt 层机制与最终修复组合。

## 决定性证据链
1. gdb 崩溃寄存器: `info registers rdi` = **0x0** — `notifyInternal2(QObject*, QEvent*)` 的 receiver 是 **NULL 指针**（不是悬挂对象，是 Qt timer 表里的残留条目）
2. TimerEvent 追踪器升级版（带 **C++ 指针 + 时间戳 + parent 链**）:
   ```python
   from PyQt5 import sip   # 🐛 不是 import sip!
   cp = hex(sip.unwrapinstance(obj)) if sip.isdeleted(obj) is False else "DEL"
   # 孤儿 timer (parent 链 ≤1) 单独写 /tmp/orphan_timers.log
   ```
3. 孤儿 log 抓到 **QPMCache[]** — QPixmapCache 的内部清理 timer（无 parent 的 Qt 内部单例）

## 机制: Qt5.15 activateTimers 批处理碰撞
- `activateTimers()` 一次激活**一批** timer; 批次中某个 timer 的槽执行时**修改了 timer 表**（创建/删除 timer 或 QPixmap 缓存操作触发 QPMCache）→ 批次继续分发时拿到 **NULL/已删 receiver** → `notifyInternal2(NULL)` → SIGSEGV
- 间歇性根因: 批处理碰撞取决于 timer 相位（为什么"同一代码时崩时不崩"）
- eventFilter 记录语义: filter 在 `obj->event()` 之前执行; obj 已删时 **filter 前就崩（不记录）** → 崩溃 timer 本身没记录, 最后一行是**前一个** — 孤儿 timer 单独追踪弥补了这一点

## 修复组合 (全部实锤)
1. **QPixmapCache.setCacheLimit(0)** — 禁用 pixmap 缓存 → QPMCache timer 不再激活（播放器帧轮播每 66ms 创建/销毁 QPixmap 是主要触发源）
2. **QTimer.singleShot 全部实例化** (14 处) — `QTimer.singleShot(ms, fn)` 内部 QSingleShotTimer 无 parent（PyQt5 5.15.14 + Py3.12 wrapper GC 竞态点）→ 模块级 `_oneshot(parent, ms, fn)`（QTimer(parent)+setSingleShot+connect+start），studio.py 和 simulink_module.py 各定义一份（QTimer import 注意位置）
3. 之前已修: 8 处无 parent QTimer 挂 parent / hover 悬挂 item sip.isdeleted 保护 / QMediaPlayer(win) 挂 parent / 工作线程不碰 Qt

## PyQt5.sip API 坑 (保护代码静默失效的元凶)
- **`import sip` 在 PyQt5 5.15.14 失败** (ModuleNotFoundError) — 模块是 **`PyQt5.sip`**
- API 是 **`unwrapinstance`**（小写 i，无 `unwrap_instance`）— 写错 → eventFilter 里异常被 try/except 吞 → **追踪器静默失效**（trace 文件一个字节都没有）
- `isdeleted` / `setdeleted` / `delete` 存在
- 教训: 依赖 sip 的保护/追踪代码写完后必须**实测**（跑最小脚本调 dir(PyQt5.sip) + eventFilter 触发一次），别假设 API 正确 — 静默失效的调试工具等于没有

## 业务层周期 timer 误触发 (崩溃时间规律)
- **崩溃时间全在启动后 45s+** → 15s 轮询 timer × 3 窗口 → 查周期 timer 的业务逻辑
- Model Zoo `_zoo_next`（15s 轮询训练队列）: 用户从未训练时 `_zoo_queue` 空 → 误判"训练完成" → 触发 `_auto_finalize()`（rollout 生成线程 + PDF + 飞书）→ 与 simulink 操作并发 → timer 竞态
- 修复: 无 `_zoo_start_ts`（从未训练）→ 直接 return 不触发交付

## offscreen/xcb 最小复现的局限
- 纯 QTimer churn 压力测试（offscreen 30s / xcb 30s）**都不崩** — 批处理碰撞需要完整应用的 timer 组合与相位
- 结论: 最小复现不崩 ≠ 修复; 崩溃修复的验证只能靠 (a) 完整 studio 实测存活时长 (b) 孤儿 timer 追踪确认崩溃源消失
