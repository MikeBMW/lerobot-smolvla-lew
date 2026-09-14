# PyQt5 Timer SIGSEGV 崩溃调试 (2026-08-18 Z-MAX 控制台实锤)

用户"怎么老崩溃/打开就崩溃"多轮排查的完整方法链。症状 → 证据 → 根因 → 修复。

## 症状特征
- **间歇性**段错误: 同一份代码时崩时不崩（GC 竞态）; 隔离环境（offscreen/单独实例化 SimulinkModule）不崩, 完整 studio 组合才崩
- stderr 常伴: `QObject::killTimer: Timers cannot be stopped from another thread` + `QObject::~QObject: Timers cannot be stopped from another thread`
- faulthandler（`faulthandler.enable()` + dump_traceback_later）只给 Python 栈: 主线程停在 `app.exec_()` — C 层崩溃点看不到
- 崩溃栈（gdb）: 主线程 `QCoreApplication::notifyInternal2(QObject*, QEvent*) ← QTimerInfoList::activateTimers() ← timerSourceDispatch()` — 事件循环里 timer 激活, 事件分发给**已销毁/悬挂对象**

## 排查步骤（按序, 两步定案）

### ① gdb 抓 C 栈（faulthandler 不够, 必须看 C 层）
```bash
gdb -batch -ex run -ex "thread apply all bt" --args /path/to/python studio.py > /tmp/gdb_studio.log 2>&1
```
- 后台跑（GUI 照常显示, gdb 透明）, 崩溃自动 dump 全部线程 C 栈
- `grep -A 25 "Thread 1 (Thread"` 看主线程完整链
- 注意: 崩溃后还要看**崩溃的是哪个线程** — 本案例崩溃在 Thread 1 主线程
- 陷阱: Qt 库无调试符号, `p ((QObject*)$rdi)->metaObject()->className()` 报 `No symbol "QObject"` — 此路不通, 用 ②

### ② TimerEvent 追踪器（定位凶手 timer 的决定性工具）
崩溃 = timer 激活分发, 所以在**每次 TimerEvent 分发前**记录接收者 — eventFilter 先于 notifyInternal2 执行, **崩溃前最后一行 = 凶手**:

```python
# studio.py 启动处（QApplication 创建后）
try:
    from PyQt5.QtCore import QObject, QEvent

    class _TimerTrace(QObject):
        def eventFilter(self, obj, ev):
            try:
                if ev.type() == QEvent.Timer:
                    chain = []
                    o = obj
                    while o is not None:
                        try:
                            chain.append(f"{o.metaObject().className()}[{o.objectName()}]")
                        except Exception:
                            chain.append("<?>")
                        o = o.parent()
                    with open("/tmp/timer_trace.log", "a") as f:
                        f.write(f"{hex(id(obj))} {' > '.join(chain)}\n")
            except Exception:
                pass
            return False

    _TIMER_TRACE = _TimerTrace()
except Exception:
    _TIMER_TRACE = None
# main(): app = QApplication(sys.argv); app.installEventFilter(_TIMER_TRACE)
```
- 崩溃后 `tail -5 /tmp/timer_trace.log` — 最后一行 className[objectName] > parent 链 = 凶手
- 本案例: 锁定 `QTimer[] > MonitorModule[] > QStackedWidget[] > ... > StudioMainWindow[]`

## 根因与修复
- 根因: `self._live_timer = QTimer()` **无 parent** — 宿主 MonitorModule 页销毁/重建后 C++ timer 仍激活, timeout 信号接收者（宿主）已销毁 → notifyInternal2 崩
- 修复: 全仓库 `grep -n "QTimer()"` 逐一改 `QTimer(self)` 挂宿主（宿主销毁级联销毁 timer）
  - 宿主是 QGraphicsObject（QObject 子类）也可挂 parent（如 CICDLinkItem/SimLinkItem）
  - 宿主若是纯 QGraphicsItem（非 QObject）则不能挂 — 需换方案
- 本案例共 8 处: studio.py 6 处 + simulink_module.py 2 处

## 同类"看起来像崩溃"的假象（先排除再查 timer）
1. **主线程 subprocess.run 阻塞 GUI 假死**: ffmpeg 抽帧 250 帧 PNG 阻塞主线程数秒 → 事件循环不响应, 测试 QTimer 链全停 → 误判"崩溃"（结果文件没写）。修复: 抽帧移后台线程 + `pyqtSignal`（类级声明）回主线程槽 + 帧目录缓存秒开
2. **窗口弹到副屏/屏幕外**: `QDialog(parent)` 居中父窗口, 父窗口被拖到扩展屏 → 弹窗 x 坐标超主屏（`DISPLAY=... xwininfo -root -tree` 看 `+3750+187`）→ 用户"没看到视频/窗口"。修复: `QApplication.primaryScreen().availableGeometry()` 中心 move
3. **QMediaPlayer 无 parent**: 播放窗关闭后 player 内部 QTimer 仍激活 → 事件给已销毁 QVideoWidget → 崩。修复: `QMediaPlayer(win)` 挂窗口
4. **QPainter/QImage 工作线程渲染**: 视频导出线程用 Qt 绘图 = SIGSEGV（`QObject::killTimer` 警告先行）。修复: 渲染改纯 Python Pillow（线程安全）
5. **旧进程残留**: 用户看到的崩溃/黑窗口可能是旧代码进程 — 每次改完必须重启控制台（kill 旧 session → background 起新 → xwininfo 验窗口）

## 验证
- 修复后: 完整 GUI 流程（加载画布→运行→播放→关窗→切页）X 环境连跑 3 次无崩 + 用户实测 55 分钟进程存活
- 隔离测试（单独实例化 SimulinkModule）**不崩不代表修复** — 完整 studio 组合才触发竞态
