# 🖥 MDI 子窗口 + 🎨 风格切换 + ⛶ 浮动画布 + 独立流程窗口 (2026-08-05, 老倪 UI 演进)

老倪的 Simulink 操作区 UI 要求演进链: 深色铺画布 → 浮动画布(独立QDialog) → **MDI 子窗口(对标 MATLAB Simulink/CANoe)** → **浅色调(Simulink/CANoe 风格)** → **浅/深风格切换(入口放配置中心)** → ACT-Meta 引导独立窗口只放操作区。

## MDI 画布子窗口 (QMdiArea + QMdiSubWindow)
- _build 主体: QSplitter(LibraryPanel | QMdiArea); canvas 包进 QMdiSubWindow → setWidget(canvas) → addSubWindow → **showMaximized()** (老倪: "窗口应充满嵌入的原来空间, 不露灰色背景"; 可还原/拖边缩放)
- subwindow 属性: setWindowTitle("🖥 画布 · Simulink 模型"), setAttribute(Qt.WA_DeleteOnClose, False) (关闭=隐藏可恢复), resize(920,620)
- MDI QSS (深色标题栏可选): QMdiArea{} / QMdiSubWindow::title / ::close-button / ::minimize-button / ::maximize-button (深色主题下 QSS 生效)
- **恢复按钮**: 工具栏「🪟 画布窗口」→ show_canvas_win(): isMinimized→showNormal, isHidden→show, mdi.setActiveSubWindow
- **PyQt5 API 坑 (实测)**: ① QSplitter **没有** removeWidget/takeAt — 移除 widget 直接 `widget.setParent(新父)` (QWidget reparent 自动从旧 QSplitter 布局移除); ② QMdiArea **没有** indexOf — 用 `win in mdi.subWindowList()`; ③ QMdiSubWindow 无 isClosable/isMinimizable 方法 — 按钮能力用行为验证 (close→isHidden, showMaximized→isMaximized)

## ⛶ 浮动画布 (MDI 适配版)
- toggle_float_canvas: 若 _float_dlg 可见 → close 还原; 否则 mdi.removeSubWindow(win) + win.hide() → FloatingCanvasDialog(self, canvas) (构造时 lay.addWidget(canvas) 自动 reparent) → show() 非模态
- _restore_canvas (dlg.closeEvent 触发): 旧 subwindow deleteLater → 新建 QMdiSubWindow + setWidget(canvas) (自动 reparent 回) + addSubWindow + show + setActiveSubWindow
- FloatingCanvasDialog: QDialog + WindowMaximizeButtonHint|WindowMinimizeButtonHint, 深色 QDialog QSS, resize(1280,820)

## 独立流程窗口 _open_float_workflow (ACT-Meta 引导用)
- 老倪纠正: "actmeta按钮打开的是主要操作的子窗口, 不是又打开控制台" → 浮动窗口**只放 new_w._main_split (库+画布MDI) + new_w.log_box (设 maximumHeight 96)**, 不放整套 SimulinkModule (hero/导航/工具栏/状态栏)
- new_w = self.__class__() 独立实例 (不碰主画布), 构造后 new_w._acq_timer.stop() (浮动实例不轮询采集)
- dlg.finished.connect(_on_close): 停 timer + _close_bubble + deleteLater
- setup_fn(new_w) 在 show() 前调 (如 lambda w: w.open_act_meta())

## 🎨 风格切换 (light/dark) — THEMES 调色板机制
- 文件顶 THEMES = {"light": {...}, "dark": {...}} (key: node_top/node_bot/title/label/port_edge/inactive/canvas/bg/bg2/panel/input/border/border2/btn/text/text2/hover/scope_top/scope_bot/grid/grid_major) + 模块级 `_CUR_THEME = "light"`
- **paint 统一读 THEMES[_CUR_THEME]**: 每个 paint 开头注入 `pal = THEMES[_CUR_THEME]`, 颜色全用 pal[key] — 主题切换后 scene.update() 即重绘
- switch_theme(name): ① `global _CUR_THEME` 更新 ② 遍历 [self]+findChildren(QWidget) 对每个 styleSheet 做浅↔深色值替换 ③ canvas.setBackgroundBrush + viewport().update + scene.update ④ 同步 simulink_scope.CUR_THEME
- **QSS 替换坑 (实测)**: light 值去重 — 同色多 key (如 input/btn 都是 #e9edf2) 若不去重, 先被替换成第一个 dark 值 (#14181f) 后第二个 pair 匹配失败 → `seen.setdefault(light_k, dark_k)` 去重
- 类型标签文字在浅色下用 #57606a (深灰), 别用节点类型色 (浅蓝 #58a6ff 在白底看不清)
- 入口 (软件惯例): studio.py ConfigModule (配置中心页) 加「🎨 UI 风格」QGroupBox + QComboBox [浅色, 深色] → _on_style_changed → self.window().simulink.switch_theme(name)
- simulink_scope.py: CUR_THEME 模块级 + _SCOPE_THEMES dict + `_st()` 动态取色 (paint 里别用 import 时求值的模块常量) + `_qss(ss)` 深色映射辅助 (对话框 setStyleSheet 包一层)

## 浅色主题化批量替换 (一次脚本)
- 颜色映射 (GitHub Light 系): #0d1117→#f6f8fa, #0a0e14→#eef1f5, #0a0a0f→#f0f2f5, #161b22→#ffffff, #14181f→#e9edf2, #1e2740→#d0d7de, #21262d→#e9edf2, #30363d→#b6bdc7, #3a3f4b→#9aa4b2, #1a1f2b→#ffffff, #111318→#e8ebf0, #8b949e→#57606a, #c9d1d9→#24292f, #e6edf3→#1f2328, #ddd→#24292f, #666→#57606a; 白色文字 color:#fff → 深色
- 替换后 ast.parse 验证 + offscreen 渲染 (QColor.lightness()>200 断言画布浅色) + grep 残留深色常量清零
