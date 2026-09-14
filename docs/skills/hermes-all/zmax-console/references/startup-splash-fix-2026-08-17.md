# 启动黑影/闪烁 根治 — 无边框 QWidget 占位 + 主题持久化 (2026-08-17 晚 三次回炉)

老倪: "还是闪烁。先是一个黑色背景的窗口, 伴随着左上角黑色阴影闪烁, 你这个问题还是没有解决"

## 时间线 (每次回炉的教训)

| 时间 | 方案 | 结果 |
| :--- | :--- | :--- |
| 08-15 | 延迟 show 2000ms | 窗口首次映射瞬间仍闪 (VcXsrv 网络合成) |
| 08-16 | QSplashScreen 1x1 纯色 | 左上角黑色横条阴影, 闪烁 ~10s |
| 08-17 上午 (cc36ea99) | QSplashScreen 同尺寸同位 + 提前到 win 构建前 | **仍闪**: "黑色背景窗口 + 左上角黑影" |
| 08-17 晚 (根治) | 普通无边框 QWidget 占位 + 主题持久化 | 待用户确认 |

**结论: QSplashScreen 本身在 VcXsrv 下有渲染缺陷** — 1x1 和同尺寸都是它画的左上角黑影,
不是尺寸/时机问题。换普通 QWidget 才绕开。

## 三个根因

1. splash 硬编码填 `C_BG=#0d1117` 深色 → 用户浅色主题下启动先弹 1400x900 大黑窗 = "黑色背景窗口"
2. QSplashScreen 在 VcXsrv 网络合成下有缺陷 (左上角黑影)
3. 主题从不持久化 (`CUR_UI_THEME="dark"` 硬编码, 无 save/load) → 重启丢浅色

## 根治代码 (studio.py 入口)

```python
# ① 主题持久化函数 (模块级, 放在 apply_ui_theme 前)
_UI_THEME_FILE = os.path.expanduser("~/.zmax_ui.json")

def save_ui_theme(theme):
    """💾 主题持久化 — 存 ~/.zmax_ui.json, 重启恢复"""
    try:
        import json as _j
        with open(_UI_THEME_FILE, "w", encoding="utf-8") as _f:
            _j.dump({"theme": theme}, _f)
    except Exception:
        pass

def load_ui_theme():
    """📖 读持久化主题 (默认 dark); 失败静默回退"""
    try:
        import json as _j
        if os.path.exists(_UI_THEME_FILE):
            with open(_UI_THEME_FILE, "r", encoding="utf-8") as _f:
                _t = _j.load(_f).get("theme", "dark")
            if _t in ("dark", "light"):
                return _t
    except Exception:
        pass
    return "dark"

# apply_ui_theme 内 CUR_UI_THEME = theme 之后立即 save_ui_theme(theme)

# ② splash 换普通无边框 QWidget (不是 QSplashScreen!):
#    _QW2 = QWidget, _QT2 = Qt, _QA2 = QApplication, _QGA2 = QGuiApplication
_splash = _QW2()
_splash.setWindowFlags(_QT2.FramelessWindowHint)
_splash.setStyleSheet("background:%s;" % _bg0)  # _bg0 = L_BG if load_ui_theme()=="light" else C_BG
_splash.setGeometry(_gx, _gy, _gw, _gh)         # 同主窗口 60,40,1400,900
_splash.show()
_QA2.processEvents()

# ③ win 构建后恢复持久化主题 (apply_ui_theme 深色快照已建 → 幂等切换):
win = StudioMainWindow()
if load_ui_theme() != "dark":
    apply_ui_theme(win, load_ui_theme())

# ④ _show_ready 里 _splash.close() — QWidget 无 finish 方法 (QSplashScreen.finish 已弃用)
```

## 坑 (必须注意)

- **QTimer import 丢失**: 换掉 QSplashScreen 时, 原 splash 块的
  `from PyQt5.QtCore import QTimer as _QTM2` 会一并删掉, 但 _show_ready 还在用
  `_QTM2.singleShot(2000, ...)` → NameError。必须把 QTimer import 补到 _show_ready
  所在 try 块局部。
- 改完 `ast.parse` 验证语法 (gui-venv 无 pip, 用 `/root/gui-venv/bin/python -c "import ast; ast.parse(...)"`)
- 重启后 xwininfo 确认 1400x900@60,40 正常 + 无 Traceback
- 排查顺序 (不重蹈): 先排除运行时闪 (连线动画已惰性化 08-15 / hover轮询鼠标不动保护 /
  _flow_clock 仅运行时 / CICD脉冲仅对话框) → 确认"启动前" → 锁定窗口映射瞬间
