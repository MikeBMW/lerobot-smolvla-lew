# 全局 UI 主题切换 (2026-08-16) — 编辑菜单: UI风格 + 字体大小

老倪需求: 菜单栏"编辑"菜单 → 🎨 UI风格(🌙暗夜/☀️浅色Simulink简约) + 🔤字体大小(小/标准/大/特大), 全局即时生效。
用户浅色偏好(明确纠正): **背景纯白 #ffffff**(不要灰蒙蒙 #f6f8fa/#eef1f5) + **字体纯黑 #000000** + **按钮去彩色化**(15种彩色按钮背景统一中性浅灰 #e9edf2, 白字转黑)。

## 实现位置 (studio.py)

- 模块级: `L_*` 浅色调色板常量、`THEME_PAIRS`(C_*↔L_* 15对)、`THEME_PAIRS_EXTRA`(硬编码深色→浅, 17对)、`THEME_PAIRS_BTN`(彩色按钮→#e9edf2, 含 `("#fff","#000000")` 短格式白字)
- `apply_ui_theme(window, theme)`: 全局主题切换
- `apply_ui_font(window, delta)`: 全局字体缩放 (delta: -2小/0标准/+2大/+4特大)
- `_build_global_qss()`: 全局 QSS (滚动条/对话框/ToolTip) 提取成函数, main() 和主题切换共用, 用当前 C_* 常量实时生成
- 菜单: `m_edit = mb.addMenu("编辑(&E)")` 放在 视图 之后; QAction setCheckable + triggered → `_menu_set_style`/`_menu_set_font`; Simulink 延迟创建后补挂当前主题 (CUR_UI_THEME/CUR_FONT_DELTA)

## 核心机制: 深色快照 + 正向生成 (关键设计!)

**绝不能用"双向字符串替换"** (light时 A→B, dark时 B→A): 多个替换对颜色有交集时 (如 #0d1117→#ffffff 后 #ffffff 又被 #fff→#000000 命中), 会产生**替换链污染** — 切一圈回来 QSS 面目全非 (实测 271/1310 控件漂移, 菜单栏恢复不了深色)。

正确做法:
1. 首次调用时给每个控件快照**深色原始 QSS** (`window._dark_qss_map[id(wdg)] = cur`)
2. 切 light: 从深色快照**正向**跑全部 pairs (THEME_PAIRS + EXTRA + BTN)
3. 切 dark: **直接恢复快照** (完美还原, 实测 1310/1310 一致)
4. `apply_ui_font` 同样基于深色快照: 先套当前主题色, 再正则缩放 `font-size:(\d+)px`, 两者互不干扰

## 坑 (全部实测踩过)

1. **QMenuBar 不在 findChildren(QWidget) 返回里** (QMainWindow 特殊子控件) — 必须显式 `window.menuBar()` 加入 widgets 列表, 否则菜单栏不换肤
2. **#fff vs #ffffff 陷阱**: 按钮文字是 `color:#fff`(短格式), 卡片/节点背景是 #ffffff(长格式)。BTN 对只映射短格式 #fff→#000000; 长格式 #ffffff 留给 EXTRA 当背景/节点色。若把 #ffffff→#000000 加进 BTN, 白底卡片全变黑
3. **simulink.switch_theme 独立机制**: simulink_module 有自己的 THEMES light/dark 调色板 (画布节点/连线/Scope), apply_ui_theme 第3步调 `sim.switch_theme(theme)` 同步; 它的 light 调色板也要同步改成白底黑字 (THEMES["light"]: canvas/bg=#ffffff, text/title=#000000, hover=#e9edf2)
4. **验证必须离屏跑**: `QT_QPA_PLATFORM=offscreen timeout 90 python -c "..."` 实例化 StudioMainWindow → apply_ui_theme('light')→('dark') → 断言与初始快照一致 (1310/1310); 检查残留: 灰底 #f6f8fa / 彩色按钮 / color:#fff 白字 全为 0。输出过滤 `grep -v "Unknown property"` (PyQt5 样式表噪音)

## 用户浅色偏好检查清单

- 背景: 纯白 #ffffff (L_BG/L_BG2/#0d1117/#161b22→#ffffff/#f6f8fa)
- 字体: 纯黑 #000000 (L_WHITE/#e6edf3/#c9d1d9→#000000), 次级 #333333
- 按钮: 15种彩色 → #e9edf2 中性浅灰, 白字 #fff → #000000
- 菜单栏: 浅灰 #e9edf2 区分带 (Simulink 风格, 可保留, 不算"灰蒙蒙")
