# PyQt5 NULL Receiver 崩溃 — 后续根因与验证 (2026-08-18 第三轮)

在 QPixmapCache/singleShot 修复后仍崩, 追加实锤的根因与观察方法。配合 `pyqt5-null-receiver-deep-dive.md` 使用。

## 追加根因
1. **QToolTip 全局隐藏 timer** (孤儿 log 实锤): 悬停节点触发 QToolTip → 内部 10s 周期隐藏 timer（无 parent 的全局单例对象, 孤儿 log 里周期性 `QObject[]` 无 parent 链, 每 ~10s 一次）→ activateTimers 批处理碰撞候选
   - 修复: 启动处 `QToolTip.setDuration(0)` 禁用 tooltip（VcXsrv 下 tooltip 渲染本来就是缺陷源）
2. **高频 timer 降频**: hover 150→300ms, log_flush 200→500ms — 减批处理碰撞窗口（每个高频 timer 都是候选碰撞源）

## 验证观察 (修复组合的逐轮收益)
- 进程存活时长: 60-70s（初始）→ 173s（QPixmapCache+singleShot 后）→ 未崩 75s+（QToolTip 后）— **每个根因消除都有可测收益, 用存活时长当验证指标**
- **孤儿 timer 追踪是持续监控手段**: eventFilter 记录 parent 链, `parent 链 ≤1` 的行写单独 log（/tmp/orphan_timers.log）— 崩溃后看最近孤儿类型: QTimer[]=我们的 singleShot 残留, QPMCache[]=QPixmapCache, QObject[] 周期=QToolTip/内部
- **崩溃时间规律 = 周期 timer 业务逻辑诊断**: 崩溃全在启动后 45s+ → 查 15s 周期 timer（Model Zoo 轮询误触发自动交付 → 无训练时直接 return, 见 deep-dive 同文件）

## 工具链要点 (可复用)
- gdb 监控: `gdb -batch -ex run -ex "thread apply all bt" --args python studio.py` 后台跑, 崩溃自动落 /tmp/gdb_studio.log
- gdb 寄存器: 崩溃时 `info registers rdi` — **rdi=0x0 = notifyInternal2 收到 NULL receiver = Qt timer 表残留**（不是悬挂对象, 是表内空条目）
- TimerEvent 追踪器 (eventFilter + sip.unwrapinstance C++ 指针 + 时间戳 + parent 链) 全代码见 `pyqt5-timer-sigsegv-debugging.md`
- **sip API 坑**: `from PyQt5 import sip`（不是 import sip）; `sip.unwrapinstance`（小写 i）; 写错 → 追踪器静默失效（trace 文件 0 字节）— 调试工具写完必须实测一次
