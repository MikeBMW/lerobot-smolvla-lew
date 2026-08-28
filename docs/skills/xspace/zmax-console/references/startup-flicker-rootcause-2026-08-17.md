# 启动黑影闪动 — 终版根治 (2026-08-17)

老倪连续 3 轮反馈: "启动前黑影闪动" → "左上角黑色横条阴影, 闪烁10秒" → "还是闪烁: 黑色背景的窗口+左上角黑影".

## 完整演变 (踩过的坑)

| 方案 | 结果 |
|:---|:---|
| 延迟 show 2000ms (08-15) | 窗口首次映射瞬间仍闪 |
| QSplashScreen 1x1 纯色 (08-16) | VcXsrv -multiwindow 下左上角渲染成黑条阴影闪 ~10s |
| QSplashScreen 同尺寸同位 + 提前到 win 构建前 (08-17 上午) | **仍闪** — 根因是 QSplashScreen 本身 |
| **普通无边框 QWidget 纯色占位 (08-17 终版)** | ✅ 根治 |

## 终版方案 (studio.py 入口, ~10606 行)

```python
_splash = None
try:
    from PyQt5.QtWidgets import QWidget as _QW2
    from PyQt5.QtCore import Qt as _QT2
    from PyQt5.QtWidgets import QApplication as _QA2
    from PyQt5.QtGui import QGuiApplication as _QGA2
    _gx, _gy, _gw, _gh = 60, 40, 1400, 900
    try:
        _scr = _QGA2.primaryScreen()
        if _scr:
            _ag = _scr.availableGeometry()
            _gx = max(0, min(60, _ag.width() - 300))
            _gy = max(0, min(40, _ag.height() - 200))
            _gw = min(1400, _ag.width())
            _gh = min(900, _ag.height())
    except Exception:
        pass
    _theme0 = load_ui_theme()                       # 读 ~/.zmax_ui.json
    _bg0 = L_BG if _theme0 == "light" else C_BG     # 颜色跟随主题!
    _splash = _QW2()
    _splash.setWindowFlags(_QT2.FramelessWindowHint)
    _splash.setStyleSheet("background:%s;" % _bg0)
    _splash.setGeometry(_gx, _gy, _gw, _gh)
    _splash.show()
    _QA2.processEvents()
except Exception:
    _splash = None
```

移交: `_show_ready()` 里 `_splash.close()` (QWidget 没有 finish 方法), 不要 `_splash.finish(win)`。

## 关键坑

1. **QSplashScreen 在 VcXsrv 下有渲染缺陷** (左上角黑影残留) — 同尺寸也闪, 换普通 QWidget。
2. **splash 颜色必须跟随主题** — 硬编码 C_BG(深色)在浅色主题下 = 启动先弹深色大窗,
   老倪说这就是"黑色背景的窗口"。用 `L_BG if light else C_BG`。
3. **主窗口位置可能错位** — 实测 splash 在 60,40 而主窗口在 3200,23 (VcXsrv 多屏/窗口管理器),
   截图 (QScreen.grabWindow) 验证主窗口真实位置; "黑色屏幕外边有黑条" 常见于位置错位。
4. 诊断工具: 容器无 xwd → 用 PyQt5 `QGuiApplication.primaryScreen().grabWindow(0).toImage()`
   保存 png + pixelColor 采样; `xwininfo -root -tree` 看窗口树。

## 主题持久化 + 铁律

- `save_ui_theme/load_ui_theme` 读写 `~/.zmax_ui.json`; `apply_ui_theme` 里 save;
  启动时 win 构建后 `if load_ui_theme() != "dark": apply_ui_theme(win, t0)`。
- **⚠️ 老倪纠正 "你不能自己改成浅色调"**: 默认启动 = 暗夜, agent 不得预设浅色主题。
  只有用户手动切主题才写 ~/.zmax_ui.json; 删掉文件 = 回默认暗夜。
