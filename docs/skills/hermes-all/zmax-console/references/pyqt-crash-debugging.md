# PyQt5 SIGSEGV 崩溃排查方法论 (2026-08-18 实战沉淀)

> 来源: 状态空间仿真 + 操作视频播放器开发中连续 8 次崩溃的完整排查。
> 症状统一: `Fatal Python error: Segmentation fault` / `QObject::killTimer: Timers cannot be stopped from another thread` / `QCoreApplication::notifyInternal2` 崩溃。
> offscreen 测不出 (无 X 连接时 C 层时序不同), 必须在真实 DISPLAY 下复现。

## 调试工具链 (按顺序上)

### 1. faulthandler (Python 栈留证)
```python
import faulthandler
faulthandler.enable()   # SIGSEGV 时 dump Python 栈到 stderr
```
崩溃栈能看到主线程在哪 (`studio.py line X in main` = exec_ 事件循环 = C 层崩, 不是 Python 代码崩)。

### 2. gdb (C 栈)
```bash
gdb -batch -ex run -ex "thread apply all bt" --args /root/gui-venv/bin/python studio.py > /tmp/gdb_studio.log 2>&1
```
关键栈: `QTimerInfoList::activateTimers → timerSourceDispatch → QCoreApplication::notifyInternal2` = **QTimer 激活时事件分发给已销毁对象**。
`notifyInternal2(QObject*, QEvent*)` 的 receiver 在 rdi 寄存器:
```bash
# gdb 命令文件 /tmp/gdb_cmds.txt:
run
info registers rdi
thread apply all bt
```
**rdi=0x0 = NULL receiver** → Qt timer 表残留 = 对象删除时 timer 条目没清 → 批次内 use-after-free 或并发轮询触发。

### 3. TimerEvent 追踪器 (锁定凶手 timer)
在 app 上装 eventFilter, 记录每次 TimerEvent 的接收者 parent 链 + 时间戳 + C++ 指针:
```python
class _TimerTrace(QObject):
    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Timer:
            chain = []
            o = obj
            while o is not None:
                chain.append(f"{o.metaObject().className()}[{o.objectName()}]")
                o = o.parent()
            from PyQt5 import sip
            cp = hex(sip.unwrapinstance(obj)) if sip.isdeleted(obj) is False else "DEL"
            open("/tmp/timer_trace.log", "a").write(f"{time.time():.1f} {cp} {' > '.join(chain)}\n")
        return False
app.installEventFilter(_TimerTrace())
```
崩溃前最后一行 parent 链 = 凶手 (如 `QTimer > TrainingModule > ...`)。
注意: 若 receiver 已删, eventFilter 在崩溃前可能记录不到 — trace 最后一行可能是崩溃 timer 的前一个。

### 4. rdi 指针 ↔ trace 对比
gdb 抓到的 rdi (C++ 指针) 与 trace 里 sip.unwrapinstance 记录的指针对比, 直接点名崩溃对象。

## 已知崩溃模式 (全部实战命中)

### A. 工作线程碰 Qt 对象 → SIGSEGV
- QPainter/QImage 在工作线程渲染 → `QObject::killTimer` + SIGSEGV (线程退出时 Qt 对象析构跨线程)
- 修复: 渲染改纯 Python (Pillow), 线程安全; 或主线程预加载 PyQt5 模块 (工作线程首次 import PyQt5 有风险)
- offscreen 测不出此问题!

### B. QMediaPlayer 无 parent → 关窗后崩
`QMediaPlayer()` 无 parent, 窗口 (QVideoWidget) 关闭销毁后 player 内部 QTimer 仍激活 → 事件分发给已销毁 vw → activateTimers → notifyInternal2 SIGSEGV。
修复: `QMediaPlayer(win)` 挂窗口父级, 窗口销毁级联销毁 player。
另: 容器无 PulseAudio → gstreamer 播放跳跃/黑屏 → 改用 ffmpeg 抽帧 + QTimer 轮播 QLabel (InferenceVideoDialog 同款)。

### C. 无 parent QTimer 悬挂 (系统性根因之一)
`self._x = QTimer()` 无 parent → 宿主对象销毁后 C++ timer 仍激活 → 信号发给已死接收者 → 崩。
修复: 全仓库 grep `QTimer()` → 全挂 `QTimer(self)`。宿主是 QGraphicsObject (QObject 子类) 也可以做 parent。
```bash
grep -rn "QTimer()" *.py | grep -v "QTimer(self)"
```

### D. 画布重建后悬挂 item wrapper
`clear()`/`load_flow_file` → `scene.clear()` 删 C++ item, 但 `_hover_items` 等集合里的 Python wrapper 悬挂 → 150ms hover timer 调 `it.scene()` 访问已删 C++ → C 层崩 (try/except 抓不住)。
修复: ① clear() 里清空集合 (`canvas._hover_items = set()`) ② 访问前 `from PyQt5 import sip; if sip.isdeleted(it): continue`。

### E. 后台轮询 timer 误触发重型流程 (终极根因)
Model Zoo `_zoo_next` 15s 轮询: 用户从未训练时队列空 → 误判"训练完成" → 触发 `_auto_finalize` (rollout 生成线程 + PDF + 飞书) → 与用户 simulink 操作并发 → timer 竞态 → **rdi=0x0 NULL receiver**。
**关键诊断线索**: 崩溃时间全在启动后 45s+ (15s 轮询 × 3 = 45s 训练窗口到期) — 周期性轮询 timer + 时间规律 = 必查轮询逻辑的误触发分支。
修复: 无启动时间戳 (`_zoo_start_ts` 为 0/未设置) → 直接 return 不触发交付。

## PyQt5 5.15.14 特定坑

- **sip 模块**: 是 `PyQt5.sip` 不是顶层 `sip`! `import sip` 直接 ImportError (被 except 吞 = 保护代码静默失效, 调试半天)。
- **API 大小写**: `sip.unwrapinstance(obj)` (小写 i), `sip.isdeleted(obj)`。`unwrap_instance` 不存在 → AttributeError 静默吞。
- 验证: `/root/gui-venv/bin/python -c "from PyQt5 import sip; print([a for a in dir(sip) if 'unwrap' in a or 'delet' in a])"` → `['delete','isdeleted','setdeleted','unwrapinstance']`。

## 其他实战坑

- **ffmpeg 抽帧阻塞主线程**: `subprocess.run(ffmpeg 250帧 PNG)` 2-5s → GUI 冻结, 测试误判"崩溃"。改后台线程 + pyqtSignal 回主线程刷新 + 缓存目录秒开。
- **渲染帧目录被 git 跟踪**: `reports/_mlp_cache_*/`、`reports/_ss_frames*/` 250 张 PNG 进 git → commit 超时/仓库膨胀。.gitignore 必须提前加。
- **多屏弹窗位置**: VcXsrv 多显示器下 `QApplication.primaryScreen()` 可能返回扩展屏; `self.window()` 可能是浮动画布 (副屏)。弹窗定位: 遍历 `topLevelWidgets()` 找主窗口 (标题含 "XSpace" 且排除 "[画布]") → `screenAt(主窗口中心)` → move 到该屏中心。
- **加载闪烁**: VcXsrv 逐节点增量渲染 = 一闪一闪。`canvas.setUpdatesEnabled(False)` 挂起 → 加载完 `setUpdatesEnabled(True)` + `scene.update()` 一次刷新。
- **gc.disable() 实验**: 曾怀疑 PyQt 包装被循环 GC 错误时序收集 (rdi=0x0), 实测禁用循环 GC 后仍崩 → 排除, 真凶是轮询误触发。引用计数仍工作, QObject 树无循环垃圾, 可作临时验证手段。
