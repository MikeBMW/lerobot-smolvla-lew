# Qt/Mutter 原生 GNOME 窗口不显示 (IsUnMapped/Iconic) — 2026-09-06 实测

环境: 原生 Ubuntu 24.04 + GNOME 46 (Mutter X11), Qt 5.15 (PyQt5). 控制台主窗口**启动即不显示**:
X 层 `xwininfo Map State: IsUnMapped` / `xprop WM_STATE: Iconic`, 但 Qt 层 `isVisible()=True isMinimized()=False state=2` — **Qt 与 WM 状态完全脱节**。

## 症状判定
- 用户"看到黑影/窗口没出来/只有壁纸" → 先查 `DISPLAY=:0 xwininfo -root -children | grep -i XSpace` + `xwininfo -id <wid> | grep Map State` + `xprop -id <wid> WM_STATE`
- 窗口存在但 IsUnMapped/Iconic = Qt map 失败, **不是崩溃** (进程活着, 主线程在 app.exec_())

## 外部恢复全无效 (都试过)
- `xdotool windowmap/windowactivate/windowstate --remove MINIMIZED` — Qt 属主窗口, X 层请求被忽略
- `wmctrl -i -a <xid>` — GNOME 46 对 Iconic 窗口的 _NET_ACTIVE_WINDOW 请求忽略
- 切 workspace 再切回、点击任务栏 dock 图标 — 无效
- ctypes 直发 `XMapWindow`/`XRaiseWindow` — WM 层拦截
- **判定: 这是 Qt show 时序与 Mutter 冲突, 不是环境/网络/崩溃问题**

## 根因 (按确证顺序)
1. **`setWindowState(WindowMaximized)` 在 show() 之前调用** (studio.py 构造里) → Qt 先 map (WM 状态未定) → Mutter 给 Iconic → 再请求 Maximized 被忽略 = 矛盾状态. XCB 日志特征: MAP→CLIENT_MESSAGE→UNMAP.
2. **setGeometry 精确铺满 availableGeometry (3068x1936) + show** → Mutter 把"铺满非最大化窗口"最小化 → Qt 实测 `state=1 WindowMinimized`. 最小 QMainWindow 同尺寸正常 → 是 studio 特有的 setGeometry+setWindowState 组合.
3. **`win.isMinimized()` 不可靠**: 窗口被 WM 锁 Iconic 但 Qt 认为 visible → isMinimized 返回 False → 恢复循环永不触发; 而**无条件** show/raise 恢复 (不加 isMinimized 判断) 反而对正常窗口触发 XCB_UNMAP_NOTIFY (日志 `rfbProcessClientProtocolVersion: client gone` 类断连).
4. faulthandler `dump_traceback_later(20)` 显示主线程在 app.exec_() — 排除卡死.

## 可靠取证: QWidget.grab() 不受 X map 影响
窗口 IsUnMapped 时 `scrot` 全屏截图只截到桌面壁纸 → **误导**。正确做法:
```python
pm = win.grab()                      # 主窗口整个渲染
pm = canvas.viewport().grab()        # QGraphicsView 画布
pm = w3.grab()                       # 3D GL 窗口 (pyqtgraph)
```
QWidget.grab() 从 Qt 渲染层直接抓, 不经 X map → **窗口不显示也能出真实控件图**。
auto_test_suite.py 的 `_shot_widget(widget, name)` 全靠这个, 窗口 IsUnMapped 时 12/12 用例照样出图 (TC01 90KB / TC08 阶段图 241-257KB).

## 自动测试在窗口不显示时也能跑
- 套件不依赖窗口 map: `QTimer` 链式驱动 + QWidget.grab 截图 + 断言
- 启动带 `ZMAX_AUTO_TEST=1` → 5s 后自动跑; `ZMAX_AUTO_TEST_ONLY=TC01` 可单用例
- TC08 阶段截图原用 xwd (`xwd -id <winId>`) — 本机无 xwd 且窗口不 map → 0KB; 改 `_shot_widget(w3)` 后 8 阶段全出图

## 用户偏好 (取证展示)
- 老倪要"控制台的截屏" = **控件/窗口内截 (QWidget.grab)**, 不是全屏桌面 scrot — 全屏图他直接说"你没发/桌面壁纸没有控制台"
- 老倪要"实际操作控制台" = 真实点击/驱动, 截图只是证据
- 多张截图一次发齐 + 表格说明每张对应哪个操作/断言
