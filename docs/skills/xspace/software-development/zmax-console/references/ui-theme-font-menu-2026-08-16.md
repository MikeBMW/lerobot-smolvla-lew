# 全局 UI 主题 / 字体菜单 (2026-08-16 老倪: 编辑菜单 → UI风格 + 字体大小)

## 需求
菜单栏新增「编辑(&E)」菜单，全局生效:
- 🎨 UI 风格: 🌙 暗夜风格(原版) / ☀️ 浅色 · Simulink 简约(白底/白卡/深字/浅灰边框)
- 🔤 字体大小: 小(-2) / 标准(0) / 大(+2) / 特大(+4)，相对原始 11px 的 delta

## 实现架构 (studio.py)
1. 浅色调色板 `L_*` 常量 (与 simulink_module.THEMES["light"] 对齐) + `THEME_PAIRS = [(dark色, light色), ...]` + `THEME_PAIRS_EXTRA`(画布/节点/日志 QSS 里写死的深色硬编码值)
2. `apply_ui_theme(window, theme)`:
   - 遍历 `[window] + window.findChildren(QWidget)`，**并显式 append `window.menuBar()`** — QMenuBar 是 QMainWindow 特殊子控件，不在 findChildren 返回里
   - 每控件: `for dc, lc in pairs: ss.replace(dc, lc) if light else ss.replace(lc, dc)` — 元组顺序是 (dark, light)!
   - `global C_*` 同步模块级常量 (后续 f-string 新建控件用新色) + SYS0-2_COLOR 同步
   - `sim.switch_theme(theme)` (画布节点/连线/Scope)
   - `app.setStyleSheet(_build_global_qss())` — 全局 QSS 提取成独立函数，用当前 C_* 实时生成
3. `apply_ui_font(window, delta)` — **基于原始 QSS 快照重建，防反复切换漂移**:
   - `window._orig_qss_map[id(wdg)] = 首次读到的 QSS`；之后每次从 base 重新 `re.sub(r"font-size:(\d+)px", +delta)`
   - `app.setFont(QFont("Arial", 10 + delta))`
4. 菜单动作 `_menu_set_style/_menu_set_font` → 调 apply 函数 + 同步菜单勾选 (`_style_acts/_font_acts` dict)

## 关键坑 (全部实测踩过)
1. **pairs 解包方向**: 元组 (dark, light)，变量必须 `dc, lc`。写反 (`lc, dc`) 导致替换方向全反 — light 切换没变、dark 反而变浅。症状极隐蔽。
2. **QMenuBar 漏换**: 不在 findChildren(QWidget) → 主题切换菜单栏不变色。必须显式加。
3. **Simulink 延迟创建** (400ms singleShot): 用户提前切主题时 `self.simulink` 还是 None → 画布创建后补挂: `_init_simulink` 里 `if CUR_UI_THEME != "dark": sim.switch_theme(CUR_UI_THEME)` + `if CUR_FONT_DELTA: apply_ui_font(self, CUR_FONT_DELTA)` (QTimer.singleShot(0, ...))
4. **EXTRA 对必须严格 (dark, light) 一一对应**: 不要放自反/两浅色对 (如 ("#24292f","#57606a")) — 会误替换正确控件色。
5. **字体防漂移**: 直接对当前 QSS 加减 delta 会累积漂移; 必须存原始快照再重建。
6. 全局 QSS 里 `QScrollBar::handle` 背景原来是硬编码 `#484f58` → 改用 `{C_DIM}` 才能跟主题走。

## 验证 (无显示环境, 离屏实测)
```bash
cd ~/lerobot-smolvla-lew/tools/gui
QT_QPA_PLATFORM=offscreen DISPLAY= timeout 90 /root/gui-venv/bin/python -c "
import sys
from PyQt5.QtWidgets import QApplication as QA
app = QA(sys.argv)
import studio
win = studio.StudioMainWindow()
mb = win.menuBar()
assert '#161b22' in mb.styleSheet()          # 初始深色
studio.apply_ui_theme(win, 'light')
assert '#eef1f5' in mb.styleSheet() and '#161b22' not in mb.styleSheet()
studio.apply_ui_theme(win, 'dark')
assert '#161b22' in mb.styleSheet() and '#eef1f5' not in mb.styleSheet()
studio.apply_ui_font(win, 2); studio.apply_ui_font(win, 0)   # 往返不漂移
print('OK')
"
```
全量覆盖断言: 切 light 后 `findChildren` 中含深色 QSS 的控件数应为 0 (132 个全清 = 覆盖完整)。

## 改动文件
- studio.py: L_* 调色板 + THEME_PAIRS(+EXTRA) + CUR_UI_THEME/CUR_FONT_DELTA + apply_ui_theme/apply_ui_font + _build_global_qss() + 编辑菜单(视图后) + _menu_set_style/_menu_set_font + _init_simulink 补挂
