# GUI 渲染与线程修复 (2026-08-19)

## 1. VcXsrv XCopyArea 半移 bug 复现 → 画布滚动分块重绘

症状: 状态空间画布滚动时"上变动, 下面不动" (下半部残留)
根因: VcXsrv 会话状态变化后 XCopyArea 位块搬运也坏 (08-18 时正常, 08-19 复现)。
08-18 的 MinimalViewportUpdate 方案 (枚举值传 1 = C++ Minimal) 只解决"露出小条重绘",
XCopyArea 搬运区不刷新。
修复 (simulink_module.py SimCanvas.scrollContentsBy):
```python
def scrollContentsBy(self, dx, dy):
    super().scrollContentsBy(dx, dy)
    vp = self.viewport()
    w, h = vp.width(), vp.height()
    if w > 20 and h > 20:
        for y in range(0, h, 400):          # 400px 一块
            vp.repaint(0, y, w, min(400, h - y))  # 同步绘制不合并 region
```
原理: 分块 repaint 每块 = 小 XPutImage, 绕开 VcXsrv 大图只画顶的 bug;
repaint 同步绘制不合并 dirty region (update() 会合并成大矩形 → 大 XPutImage)。
Feature List 的 QTextBrowser 滚动修复同源 (scrollContentsBy → viewport().update()).

## 2. _oneshot 跨线程创建 QTimer — Segfault 隐患根治 (重要)

症状: 控制台日志刷屏 "QObject: Cannot create children for a parent that is in a
different thread (Parent is MonitorModule)" + "QObject::startTimer: Timers can only
be used with threads started with QThread"。这是 08-18 "QObject::killTimer from
another thread" Segfault 的同源问题。
根因: MonitorModule._refresh_orin_status 后台线程 (每 5s 轮询 ECS) 成功后调
_oneshot(self, 0, fn) — QTimer(parent=MonitorModule) 在 worker 线程创建,
parent 在主线程 → Qt 严格模式报错。
修复 (studio.py _oneshot 跨线程派发桥):
```python
class _OneshotBridge(QObject):
    sig = pyqtSignal(object, int, object)
_oneshot_bridge = _OneshotBridge()
_oneshot_bridge.sig.connect(lambda p, m, f: _oneshot(p, m, f))

def _oneshot(parent, ms, fn):
    if QThread.currentThread() is parent.thread():
        t = QTimer(parent); t.setSingleShot(True); t.timeout.connect(fn); t.start(ms)
        return t
    _oneshot_bridge.sig.emit(parent, ms, fn)  # 信号跨线程自动 QueuedConnection
    return None
```
要点: PyQt5 QMetaObject.invokeMethod 不接受 Python callable (只收 str 方法名),
所以用 pyqtSignal 桥 (QueuedConnection 自动排队到接收者线程)。
桥接对象必须在主线程 import 时创建; pyqtSignal 要提前 import (studio.py 118 行
之后才 import — 需在桥类前单独 import)。
验证: 主线程 + worker 线程各调 _oneshot, 回调都正常, 无警告。

## 3. GUI 主线程禁长 subprocess (导出/导入按钮)

导出 Excel 上传 (sshpass scp) 在主线程跑 = 按钮假死 60s (gdb: selectors select)。
修复模式: threading.Thread + pyqtSignal(str) 回主线程更新提示 + 按钮置灰。
ModelTreeDock: export_done = pyqtSignal(str); 完成后若 "导入成功" 则 self.refresh()。

## 4. QLabel 链接可选中可点击

导出提示 URL 在 QLabel 默认不可选。修复:
setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextBrowserInteraction)
+ setOpenExternalLinks(True) + 文本用 <a href> 蓝色渲染。

## 5. faulthandler 每 20s dump 是正常诊断

studio.py main 尾部 faulthandler.dump_traceback_later(20, repeat=True) —
每 20s 打印全线程 Python 栈到 stderr (08-18 加的卡死诊断)。不是崩溃!
线程栈显示 relay recv 阻塞在 ssl read 是正常等待 WS 数据。watch_patterns
配 "Traceback" 时注意区分 dump ("Thread ... most recent call first")
与真实 Traceback ("Traceback (most recent call last):")。

## 6. websocket-client 缺失

relay_middleware.py zmax-ws-client 线程 import websocket 失败 →
"Exception in thread zmax-ws-client: ModuleNotFoundError"。装 websocket-client。
