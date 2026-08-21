# Segfault 诊断记录 — 2026-08-21

## 现象
「收起左侧栏」+「打开状态空间」→ 规律性 SIGSEGV（100% 复现）。

## 崩溃回溯（faulthandler，/tmp/studio.log）
```
Fatal Python error: Segmentation fault

Thread 0x00007dfc60d626c0 (most recent call first):   # WS 线程（背景，非崩溃线程）
  ssl.py:1180 read → websocket recv → relay_middleware.py:209 _run

Current thread 0x00007dfcd71ad740 (most recent call first):  # 崩溃线程 = 主线程
  studio.py:10984 main → 10989 <module>     # app.exec_() C++ 事件循环内
```

## 根因
`faulthandler.dump_traceback_later(20, repeat=True)` 用 **SIGALRM 信号定时器**（`signal.setitimer(ITIMER_REAL)`）
每 20 秒 dump 所有线程 Python 栈。

SIGALRM 是异步信号，在 Qt 事件循环的 C++ 代码（killTimer / activateTimers /
对象析构）执行中途打断进程 → faulthandler 信号 handler 遍历线程状态 → 与 Qt 内部
状态冲突 → `killTimer cross-thread SIGSEGV`。

「收左面 + 打开状态空间」会密集创建/销毁 Qt 对象与 timer（_oneshot 300ms hint、
连线 _anim_timer、气泡关闭 timer、clear() 场景重建），正好撞上 20 秒 dump 周期，
所以崩溃"很规律"。网络恢复只是巧合（WS 线程 recv 超时减少，竞态窗口变窄），
不是根因。

## 修复（studio.py main()）
```python
import faulthandler
faulthandler.enable()                        # 保留：崩溃时 dump（被动，安全）
if os.environ.get("ZMAX_FAULTHANDLER") == "1":
    faulthandler.dump_traceback_later(20, repeat=True, file=sys.stderr)  # 默认关闭
```
排查卡死时才 `ZMAX_FAULTHANDLER=1` 开启周期 dump。

## 教训
1. `faulthandler.dump_traceback_later()` 是信号驱动（SIGALRM），与 Qt/PyQt5 事件循环
   不兼容，会引入 killTimer cross-thread SIGSEGV。GUI 程序**默认禁用**，只在排查
   卡死时临时开。
2. 崩溃回溯里"Current thread 栈只有 main→<module>" = 崩在 C++ 事件循环深处，
   凶手是异步信号/孤儿 QObject，不是普通 Python 逻辑错误。
3. 诊断日志归档：/tmp/studio.log(崩溃回溯) /tmp/closeEvent.log /tmp/orphan_timers.log。
