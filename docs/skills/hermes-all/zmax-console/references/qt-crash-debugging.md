# PyQt5 跨线程 SIGSEGV 崩溃 — 根因与调试 (2026-08-18 实测)

控制台反复崩溃, 全是 Qt 跨线程/悬挂对象。三类已实锤根因 + 调试三件套。

## 三类根因 (全部实测复现+修复)

### 1. 工作线程用 QPainter/QImage 渲染 → SIGSEGV
- 症状: `QObject::killTimer: Timers cannot be stopped from another thread` +
  `QObject::~QObject: Timers cannot be stopped from another thread` → exit -11
- 场景: threading.Thread 里 make_video → QPainter 画帧
- 修复: 渲染改纯 Pillow (线程安全, 零 Qt 依赖), 中文字体 wqy-microhei:
  `/usr/share/fonts/truetype/wqy/wqy-microhei.ttc`

### 2. 工作线程首次 import 含 PyQt5 的模块 → SIGSEGV (真实 X 环境)
- offscreen 测试不崩 (无 X 连接), 真实 VcXsrv 下工作线程 import PyQt5 模块
  触碰 Qt 全局初始化 → 崩
- 修复: 主线程预加载 (`import gen_state_space_video` 在起线程前), 线程内走
  sys.modules 缓存

### 3. QMediaPlayer 无 parent → 窗口关闭后内部 QTimer 激活 → SIGSEGV
- gdb C 栈实锤: `QTimerInfoList::activateTimers → QCoreApplication::notifyInternal2`
  → 事件分发给已销毁对象
- 场景: 播放窗口 (QDialog+QVideoWidget) 关闭, vw 销毁, player 还活着,
  内部 timer 继续激活 → 崩
- 修复: `player = QMediaPlayer(win)` 父子挂接, 窗口销毁级联销毁 player
- 铁律: **任何 QObject 必须挂 parent 或用 self.xxx 保引用**, 否则窗口关闭后
  内部 timer/事件 = 定时炸弹

## 调试三件套 (按序使用)

### A. faulthandler 留证 (studio.py 常驻)
```python
import faulthandler; faulthandler.enable()   # SIGSEGV 时 dump Python 栈
```
崩溃后看: Python 栈 + Extension modules 列表 (能判断哪些 C 扩展已加载,
例: 无 _imaging = 视频线程从未跑到 Pillow 渲染 → 崩溃与视频线程无关)。

### B. gdb 抓 C 栈 (确定 Qt 层崩点)
```bash
apt-get install -y gdb
DISPLAY=host.docker.internal:0 gdb -batch -ex run -ex "thread apply all bt" \
  --args /root/gui-venv/bin/python studio.py > /tmp/gdb_studio.log 2>&1
```
判读: `notifyInternal2` 前帧是 `activateTimers` = QTimer 分发事件给已销毁对象;
`QEventDispatcherGlib` = 事件循环内; 看 Thread 1 完整栈。

### C. TimerEvent 追踪器 (崩溃前最后一行 = 凶手 timer 接收者)
studio.py 启动时 (QApplication 创建后):
```python
from PyQt5.QtCore import QObject, QEvent
class _TimerTrace(QObject):
    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Timer:
            with open("/tmp/timer_trace.log", "a") as f:
                f.write(f"{obj.metaObject().className()} | {obj.objectName()}\n")
        return False
app.installEventFilter(_TimerTrace())
```
崩溃后 `tail /tmp/timer_trace.log` — 最后一行即凶手。

## 隔离复现 (区分"完整 studio 组合" vs "单组件")
- 单组件 X 环境测试: 实例化 SimulinkModule → show → 事件循环 15s,
  不崩 = 问题在 studio 组合/特定交互, 不在组件本身
- 注意: 管道 print 可能丢失, 用写文件方式收结果

## 相关已知坑 (记忆验证)
- exit134/关窗崩: closeEvent 停全部 QTimer + pkill (漏 timer → SIGSEGV); nice 10
- QDialog close 只是 hide 不销毁 — 对象活着 timer 活着; 销毁才断连接
