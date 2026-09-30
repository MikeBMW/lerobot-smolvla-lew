# PyQt5 + VcXsrv 深坑 (2026-08-18 实锤, 全部 gdb/实测验证)

## 1. PyQt5 5.15 sip 枚举错位 (ViewportUpdateMode) — 设错 = 行为完全相反
实测枚举值:
```
PyQt5 枚举             值   → C++ 收到
NoViewportUpdate        3   → BoundingRectViewportUpdate
MinimalViewportUpdate   1   → MinimalViewportUpdate (唯一一致)
FullViewportUpdate      0   → NoViewportUpdate   ← 设"全量重绘"实际是"不重绘"!
BoundingRect            4   → SmartViewportUpdate
SmartViewportUpdate     2   → FullViewportUpdate  ← 要 C++ FullViewportUpdate 传 2
```
教训: `setViewportUpdateMode(QGraphicsView.FullViewportUpdate)` 实际生效 NoViewportUpdate
(滚动不重绘, 只位块移动 → 内容残影)。要 C++ FullViewportUpdate 直接 `setViewportUpdateMode(2)`。
**任何 PyQt5 枚举传参后行为诡异, 先打印 `int(枚举)` 核对 C++ 值**。

## 2. QDialog/QGraphicsItem 事件重写里 Python 异常 = qFatal = abort
PyQt5 虚函数重写 (resizeEvent/paintEvent/mouseDoubleClickEvent/showEvent/closeEvent) 里
抛 Python 异常 → sip 调用链 → `pyqt5_err_print → QMessageLogger::fatal → abort()` —
**进程直接死, stderr 显示 "Fatal Python error: Segmentation fault/Aborted"**,
与 NULL receiver 崩溃外观相同但根因完全不同。
gdb 判定: 栈里出现 `sipQDialog::resizeEvent → sip_api_call_error_handler → pyqt5_err_print`
= 事件重写异常; 栈在 `QTimerInfoList::activateTimers → notifyInternal2` = NULL receiver 竞态。
**铁律: 所有事件重写方法体必须 try/except 包裹** (本会话 MLPRolloutDialog.resizeEvent
黑屏级崩溃、StateSpaceScopeDialog.paintEvent 同款)。

## 3. QPixmap 没有 mirrored() 方法 — 黑屏元凶
`QPixmap.mirrored()` 不存在 (AttributeError, 那是 QImage 的) — 若被 try 吞掉则**静默黑屏**
(窗口正常、标题卡"加载中"、pixmap 为 null)。正确写法:
```python
pm = QPixmap.fromImage(pm.toImage().mirrored(True, True))   # 180°旋转 (快速位图)
pm = QPixmap.fromImage(pm.toImage().mirrored(True, False))  # 水平镜像
pm = QPixmap.fromImage(pm.toImage().mirrored(False, True))  # 垂直镜像
```
排查黑屏: 先离屏/X 下实例化组件, 检查 `label.pixmap()` 是否 null + 标题是否更新,
再怀疑显示层。本会话黑屏 = 此 bug, 非 VcXsrv。

## 4. QDialog 关闭后 C++ 对象删除, Python 引用悬垂 → RuntimeError → qFatal
窗口关掉后 `self._xxx_dlg.isVisible()` → `RuntimeError: wrapped C/C++ object has been deleted`
→ 冒泡到 QGraphicsItem 虚函数 → qFatal abort (本会话完整栈:
mouseDoubleClickEvent → play_mlp_rollout → dlg.isVisible() → RuntimeError → Aborted)。
**铁律: 持有 dialog 引用的地方必须 sip.isdeleted 检查**:
```python
from PyQt5 import sip
if dlg is not None:
    if not sip.isdeleted(dlg) and dlg.isVisible(): ... return
    self._mlp_dlg = None   # 悬垂自动清
```

## 5. VcXsrv (HC-Consult 1.20.14) 渲染 bug: 大 XPutImage 只画顶部
xdpyinfo 验证: VcXsrv 支持 BIG-REQUESTS (max request 16MB), **无 MIT-SHM** (Qt 走 XPutImage)。
Qt 单块 XPutImage 上传整个窗口 (~5MB) → **VcXsrv 只画请求开头一点/一半** → "上半部分动,
下半部分不动" / "只有上边一小部分动"。窗口移动 (服务器端挪像素) 正常 = 增量上传路径坏。
- `QT_XCB_NO_XDAMAGE=1`: 禁用部分上传 → **所有大窗口 (弹窗/视频窗) 全量上传 → 整个窗口黑屏!**
- 权衡: **不要设 QT_XCB_NO_XDAMAGE** (弹窗全黑); 滚动残影 (XCopyArea 半移动) 是 VcXsrv
  老版本 bug, 根治 = 升级 VcXsrv 或换 Xvfb+VNC 显示, Qt 代码侧无解。
- MinimalViewportUpdate (默认, 传 1) 是滚动最优: XCopyArea 位块移动 + 小条重绘。
- xdotool 注入在 VcXsrv 下无效 (XTEST core 事件, Qt xcb 用 XInput2 收不到) — 别用它模拟 GUI。

## 6. 卡死排查: faulthandler.dump_traceback_later
主线程卡死/崩溃时抓 Python 栈:
```python
import faulthandler; faulthandler.enable()
faulthandler.dump_traceback_later(20, repeat=True, file=sys.stderr)
```
信号定时器, 事件循环卡死也能触发 — 每 20s dump 全部线程 Python 栈到 stderr。
本会话用它证明"卡死"其实是主线程正常在 exec_() (显示层问题), 排除死锁。

## 7. 渲染/重活移子进程 (Pillow 持 GIL 卡主线程)
Pillow 渲染 240 帧持 GIL 数秒 → 主线程事件循环饿死 (点运行后拖滚动条卡死/崩溃)。
**渲染移子进程**: `subprocess.run([sys.executable, "gen_xxx.py", out], cwd=...)` —
子进程独立 GIL, 主线程零阻塞。线程内 import PyQt5/PIL 首载也有 SIGSEGV 风险, 子进程化一并规避。

## 8. 视频方向调试 (metaworld rollout)
- rot180 伪装副本: 文件名不带 rot 但内容已旋转 (如 发送_MLP插拔成功.mp4 ==
  mlp_insert_success_rot180.mp4 字节数完全相同) — 选片时按字节去重/黑名单。
- HUD 文字方向 ≠ 画面方向 (生成端渲染 bug) 时, 旋转/镜像组合无法两全 — 需生成端重渲。
- 旋转按钮做 90° 循环 (0→90→180→270) + 左右/上下翻转按钮, 让用户现场调出正确组合。
