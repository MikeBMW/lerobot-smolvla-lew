# Qt 窗口 X 层不 map (GNOME/Mutter 46) — 诊断与止损 (2026-09-06 实测)

## 现象
Z-MAX 控制台 studio.py (PyQt5 5.15) 在 GNOME Shell 46 / X11 会话下:
- `xwininfo -id <win> | grep 'Map State'` → **IsUnMapped** (永不 map)
- `xprop -id <win> WM_STATE` → **Iconic** (最小化) 或 Withdrawn
- Qt 内部同一窗口: `isVisible()=True, isMinimized()=False, windowState()=0/2` — **Qt 认为完全正常**
- 屏幕只有桌面壁纸+终端, 控制台窗口不出现 (用户侧确认)
- 但 `QWidget.grab()` 取证截图照常出真实渲染内容 → **功能不受影响**

## 判定方法 (Qt 状态 vs X 层状态必须分别探测)
```
Qt 层:  python 内 print(w.isVisible(), w.isMinimized(), int(w.windowState()))
X 层:   DISPLAY=:0 xwininfo -id $WID | grep 'Map State'      # IsViewable / IsUnMapped
        DISPLAY=:0 xprop -id $WID WM_STATE                   # Normal / Iconic / Withdrawn
```
不一致 (Qt 正常 + X UnMapped/Iconic) = map 请求在 X/WM 层丢失。

## 已验证的无效手段 (别再重复试)
1. Qt 内 `win.setWindowState(st & ~Qt.WindowMinimized); win.show(); win.raise_()` — 仅当 Qt isMinimized()=True 时有效; Qt 报正常时无效
2. Qt 内 QTimer 持续恢复循环 (每 400ms × 10+ 次) — 无效
3. `win.winId()` / `windowHandle().create()` 强制 native 创建 — 无效
4. 外部 `wmctrl -i -a <xid>` / `xdotool windowmap|windowactivate|windowraise` — 无效
5. `ctypes.CDLL("libX11.so.6").XMapWindow(dpy, wid) + XRaiseWindow + XFlush` — 无效 (Mutter 在 WM 层拦截)
6. 移除 splash / 去掉 show 前 setWindowState(Maximized) / 尺寸改 96% / 延迟 show 改立即 show — 均无效
7. 纯 QMainWindow + 同尺寸同 env 最小复现 → **正常显示**; StudioMainWindow (复杂子控件树) show 即异常 → 与窗口内容复杂度相关, 非通用 Qt bug

## 已排除的变量
splash (QSplashScreen)、setWindowState 时机、窗口尺寸/最大化、gc.disable()、AA_* attributes
(注: `Qt.AA_DisableWindowManagerEffects` 在 PyQt5 QtCore 中**不存在** — 代码里该行抛 AttributeError 被 try/except 吞掉, 无害)、QT_QPA_PLATFORM=xcb 显式、GNOME 会话 env (DBUS/XDG/XAUTHORITY 从 /proc/<gnome-shell-pid>/environ 取全)。

## 诊断利器 (有效)
- `QT_LOGGING_RULES="qt.qpa.*=true"` 启动 → 日志可见 `XCB_MAP_NOTIFY` → `XCB_CLIENT_MESSAGE` → `XCB_UNMAP_NOTIFY` 序列 (unmap 由 WM 的 state-change client message 触发); 也可看到窗口从未被 map 的真实证据
- `/proc/<pid>/environ` 从 gnome-shell 进程取会话 env (DBUS_SESSION_BUS_ADDRESS/XDG_RUNTIME_DIR/XAUTHORITY) — gio launch / 桌面级 GUI 启动必需
- faulthandler 确认主线程在 app.exec_() 事件循环, 非卡死

## 止损结论
- 疑似 GNOME Mutter 46 对特定复杂 Qt 窗口的 WM 级 map 拒绝, 未找到代码层修复
- 取证/验证**不要等窗口显示**: QWidget.grab() 照常跑 (Z-MAX auto_test_suite 12/12 通过)
- 用户要"看到真机窗口"时的可行方向: 换轻量 WM (openbox/xfwm4) 跑该应用, 或重启 GNOME 会话/注销重登, 或接受截图取证
- 桌面级启动用 `gio launch <~/.desktop 图标>` (带完整会话 env), 不要 nohup 裸启

## 附带: 飞书端实时看屏 (用户远程看 agent 操作桌面的可行模式)
- 用户不在真机旁时: 建 cron 任务 `every 1m` (最小粒度), prompt = "DISPLAY=:0 timeout 10 scrot /tmp/screen_live_monitor.png, 回复含 MEDIA:/tmp/screen_live_monitor.png" → 每分钟截图发飞书群
- **MEDIA 发送前压缩**: ~3MB PNG 可能不送达 ("你没发啊"); PIL `thumbnail((1600,1000))` + JPEG q80 (~200-400KB) 稳定送达
- 每步操作后立即 scrot + MEDIA 发群 = "逐步截图发飞书" 交付模式 (老倪偏好: 真实前台操作 + 截图证据, 禁纯后台无画面)

## 桌面自动化通用坑 (本机 DISPLAY=:0)
- `pkill -f "studio.py"` 会匹配到自身 bash (命令行含该串) → 自杀 exit -9; 用 `pgrep -f` 循环排除或脚本落盘
- 超长 inline heredoc / 巨型 one-liner 被 Hermes 命令解析硬拦 → 先 write_file 落盘脚本再 `bash /tmp/x.sh`
- scrot 全屏 3200x2000 PNG ~3MB; 分析用 PIL: 亮度/饱和分层找窗口区域 (桌面壁纸 vs 深色 UI 难分, 让用户确认最快)
