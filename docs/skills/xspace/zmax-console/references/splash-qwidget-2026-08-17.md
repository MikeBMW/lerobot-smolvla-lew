# 启动黑影 2026-08-17 回炉 — QSplashScreen 弃用, 无边框 QWidget 占位

老倪实测三连 (08-16 ~ 08-17):
1. "控制台启动前, 屏幕有黑影闪动" → QSplashScreen 1x1 纯色占位
2. "左上角黑色横条阴影, 闪烁10秒" → splash 改主窗口同尺寸同位 + 提前到 win 构建前
3. "还是闪烁。先是一个黑色背景的窗口, 伴随左上角黑色阴影" + "打开后屏幕要卡住3秒左右"
   → **QSplashScreen 本身在 VcXsrv 下有渲染缺陷, 同尺寸仍闪左上角黑影 — 弃用**

## 终版方案 (2026-08-17 已落地 studio.py)

```python
_splash = QWidget()                      # 普通无边框 QWidget, 不用 QSplashScreen!
_splash.setWindowFlags(Qt.FramelessWindowHint)
_bg0 = L_BG if load_ui_theme() == "light" else C_BG   # 颜色跟随持久化主题!
_splash.setStyleSheet("background:%s;" % _bg0)
_splash.setGeometry(_gx, _gy, _gw, _gh)  # 同尺寸同位, 主窗口 show 时无缝覆盖
_splash.show(); QApplication.processEvents()
# win 构建后 _show_ready 里 _splash.close()  (QSplashScreen.finish 已弃用)
```

## 三条铁律 (本会话实测教训)

1. **splash 颜色必须跟随当前主题** (L_BG 浅色 / C_BG 深色), 不能硬编码 C_BG —
   浅色主题下深色 splash = "黑色背景的窗口", 用户一眼看出突兀。
2. **不得预设主题色** — 老倪明确纠正 "你不能自己改成浅色调, 默认打开是暗夜"。
   默认 CUR_UI_THEME="dark"; 只有用户手动在 编辑菜单→UI风格 切换才写持久化文件
   (~/.zmax_ui.json, save_ui_theme/load_ui_theme)。静静写文件预设 light = 越权。
3. **启动 2s 延迟 (QTimer.singleShot(2000)) 是历史遗留** — 老倪反馈"卡住3秒左右"。
   后续方向: 构建完立即 show (splash 已提前创建, 无需再等 2s)。

## 排查残留小窗口

- `DISPLAY=host.docker.internal:0 xwininfo -root -tree` 可见多余 224x54/303x28 小窗
  = splash 或 QToolTip 残留瞬态窗口 (非 bug, 稍后自动消失)
- 主窗口坐标异常 (如 3200,23 而非 60,40) = 多显示器/窗口管理器放偏,
  先查 xwininfo 位置再改代码; 截图采样用 Qt `QGuiApplication.primaryScreen().grabWindow(0)`
  (容器无 xwd/import, 用 gui-venv 的 PyQt5)
