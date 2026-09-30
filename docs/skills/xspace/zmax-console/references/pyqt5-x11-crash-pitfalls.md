# PyQt5 + X11/VcXsrv 崩溃与渲染坑 (2026-08-18 全部实测)

## 1. PyQt5 5.15 sip 枚举错位 (设 FullViewportUpdate 实际是 NoViewportUpdate!)
实测值: NoViewportUpdate=3, MinimalViewportUpdate=1, **FullViewportUpdate=0**,
BoundingRectViewportUpdate=4, SmartViewportUpdate=2
- `setViewportUpdateMode(QGraphicsView.FullViewportUpdate)` → C++ 收到 0 =
  **NoViewportUpdate** (滚动不自动重绘!) → 症状: 滚动条拖动只有新露出小条更新
- **要 C++ FullViewportUpdate(2) 必须传整数 2**: `setViewportUpdateMode(2)`
  (或 PyQt5.SmartViewportUpdate, 值恰为 2)
- MinimalViewportUpdate=1 是唯一 PyQt5/C++ 一致的枚举

## 2. 虚函数重写里 Python 异常 = qFatal abort (显示 "Segmentation fault")
QDialog/QGraphicsItem 的事件虚函数重写 (resizeEvent/paintEvent/mouseDoubleClickEvent/
showEvent/closeEvent) 里抛 Python 异常 → PyQt5 的 sip 回调 → QMessageLogger::fatal →
abort → 崩溃显示为 "Fatal Python error: Segmentation fault" (其实不是 SIGSEGV!)
- gdb 栈特征: `sipQDialog::resizeEvent → sip_api_call_error_handler → pyqt5_err_print →
  QMessageLogger::fatal → abort`
- **铁律: 所有事件虚函数重写必须 try/except 包裹** (resizeEvent 早期触发时属性可能
  未初始化 → AttributeError)
- 槽函数 (按钮 clicked 等) 异常不 qFatal (只打 traceback), 但事件重写必崩

## 3. QDialog 关闭后引用悬垂 → RuntimeError → qFatal
dialog 关窗后 C++ 对象删除, Python 引用还在 → 再次访问 (isVisible 等) →
`RuntimeError: wrapped C/C++ object ... has been deleted` → 若发生在事件重写里 →
qFatal abort
- **铁律: 访问可能已关闭的 dialog 前用 `from PyQt5 import sip; sip.isdeleted(dlg)` 检查**
- 存 dialog 引用的成员 (如 self._mlp_dlg) 在发现悬垂时置 None

## 4. 卡死诊断: faulthandler.dump_traceback_later (不用 gdb 抓卡死)
```python
import faulthandler
faulthandler.enable()
faulthandler.dump_traceback_later(20, repeat=True, file=sys.stderr)
```
- 信号定时器, **事件循环卡死也能触发** → 每 20s dump 全部线程 Python 栈到 stderr
- 卡死/崩溃后看 stderr 尾部即可定位主线程阻塞点
- 结论: 主线程在 exec_ 正常 = 不是死锁, 是显示层问题 (见 §5)

## 5. VcXsrv 渲染 bug 诊断 (HC-Consult 12014000, 2021 版)
症状: "屏幕上边动下边不动 / 只有上边一小部分动" — 增量更新只显示部分区域
- **窗口移动 (xdotool windowmove) 后显示完整** = 服务器端全量合成正常
- 增量更新两个 bug: XCopyArea 位块移动只移一半; 大 XPutImage 只画顶部一点
  (xdpyinfo: max request 16MB/BIG-REQUESTS → Qt 单块上传整个窗口 ~5MB → VcXsrv 只画顶部)
- Qt 侧已是最优: MinimalViewportUpdate (XCopyArea + 小条重绘), **任何全量重绘都踩 bug**
- **根治只能换显示**: 升级 VcXsrv / Xvfb+VNC / 换 X server。代码侧绕不开 resize 全量重绘
- 诊断工具: `xdpyinfo | grep -iE "max request|extension"` (容器有 xdpyinfo);
  ffmpeg x11grab 打不开 TCP X (host.docker.internal:0), 用
  `QApplication.primaryScreen().grabWindow(0)` 截图; **xdotool 的 XTEST 注入 Qt 收不到**
  (Qt 用 XInput2, xdotool 发 core 事件) — 模拟交互无效, 只能用户手动测

## 6. Pillow 渲染持 GIL → 卡主线程
后台线程 Pillow 渲染 (ImageDraw 绘制不释放 GIL) → 主线程事件循环饿 → 假死
- 修复: 渲染移**子进程** (subprocess 跑独立脚本, cwd=脚本目录), 主线程零阻塞
- `sys.executable` 在 GUI 里 = gui-venv311/bin/python (有 numpy+PIL)

## 7. 先确认用户拖的是哪个滚动条!
本次教训: 用户说"画布右侧滚动条"→ 修了 SimCanvas 多轮无效 → 实际是
**HomeWidget 的 QScrollArea 滚动条** (主界面) 或 **QMdiArea 滚动条**
- QGraphicsView (SimCanvas) / QScrollArea (HomeWidget/模块库) / QMdiArea /
  QSplitter 手柄 — 滚动条来源 4 种, 症状描述会混淆
- 排查前先 xwininfo/xdotool 或问清: 滚动的是页面内容还是画布内容
