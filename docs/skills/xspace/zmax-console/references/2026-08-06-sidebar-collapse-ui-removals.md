# 2026-08-06 左侧栏折叠 + UI 大精简 + 深色恢复

老倪连续迭代三轮的完整记录：折叠对象指代辨析、五个"没用就删"的按钮、主题色替换坑、深色恢复、删除控件后引用检查。

## 1. 指代辨析（最重要教训）：用户说"左侧栏"是哪个？

GUI 有两个"左侧栏"，本轮**改错对象浪费 3 轮**才定位：

| 用户说法 | 实际对象 | 位置 |
|---|---|---|
| "左侧列表/侧边栏/左侧栏" | **主窗口 SystemSidebar**（studio.py, 240px，含 XSpace Studio logo + System2/Sys-12 卡片） | studio.py 主窗口 `root.addWidget(self.sidebar)` |
| "模块库" | **SimulinkModule.LibraryPanel**（画布页左侧 220px 模块列表） | simulink_module.py QSplitter 第一部件 |

老倪原话演进："左侧列表要能隐藏" → 我改了 LibraryPanel（错）→ "还是没隐藏" → 加双入口（仍错）→ "XSpace Studio 这个列表栏" → 才定位到 SystemSidebar（对）。

**判定规则**：提到 "XSpace Studio" / "列表栏" / "侧边栏" = SystemSidebar；提到 "模块库" / "模块列表" = LibraryPanel。不确定时先 grep `class SystemSidebar` 和 `class LibraryPanel` 两个类再问。

## 2. SystemSidebar 折叠实现（studio.py）

```python
# SystemSidebar 加信号 + 标题行 ◀ 按钮
collapse_requested = pyqtSignal()
# 标题行: logo_row.addStretch() + btn_collapse = QPushButton("◀") → collapse_requested.emit

# StudioMainWindow._build:
self._sb_expand_bar = QPushButton("▶")  # 16px 窄条, 初始 setVisible(False)
self.sidebar.collapse_requested.connect(self._collapse_sidebar)
root.addWidget(self.sidebar); root.addWidget(self._sb_expand_bar)

def _collapse_sidebar(self): self.sidebar.setVisible(False); self._sb_expand_bar.setVisible(True)
def _expand_sidebar(self):   self.sidebar.setVisible(True);  self._sb_expand_bar.setVisible(False)
```

## 3. 本轮删除的五个 UI（老倪: "没用就删掉"）

| 删除项 | 理由 | 注意事项 |
|---|---|---|
| 参考应用条整行（`🗂 参考应用:` + 11 个白字模板按钮） | 与上方彩色工具栏按钮重复（三/五模型对比/VLA-Touch/AWE/总系统/ACT-Meta 都有彩色入口） | **REFERENCE_APPS 数据保留**（模块库完整条目/load_reference_app_by_name 仍用）；`_ref_btns` 无残留引用 |
| 工作流过滤行（① 访问·标注数据…⑥ 集成·测试 6 个白钮） | 没用占地方 | `_filter_library` 方法一并删（引用已删按钮会 AttributeError）；`LibraryPanel.set_filter` 保留供内部 |
| 「🪟 画布窗口」按钮 + show_canvas_win 方法 | 画布子窗口已不可最小化/关闭，恢复逻辑无存在必要 | 删前确认无其他引用（仅按钮一处） |
| 「时间 10.0s / dt 0.010」仿真参数 QDoubleSpinBox | 纯 UI 无逻辑价值 | **陷阱**：`start_sim` L3421-22 读取 `sp_dt.value()`/`sp_t_end.value()` → 删控件必须 grep 引用，改 `getattr(self, "_sim_dt", 0.01)` 兜底 |
| 工具栏「📚 模块库」按钮 + _toggle_lib_btn | 面板内已有 ◀ 收起，tl2 按钮冗余 | 保留 collapse_requested/_collapse_library/_expand_library |

**通用规则**：删任何 UI 控件前 `grep -rn "控件名" tools/gui/` 查全部引用（含 lambda/回调/其他方法）；删除按钮后还要查 `addWidget(self.btn_xxx)` 残留行。

## 4. switch_theme 主题色替换坑（深色/浅色切换）

`switch_theme` 遍历**所有** QWidget 的 styleSheet，把 light 色值替换成 dark 值（`pairs` 表）。坑：

- **按钮 `color:#ffffff`（白字）会被替换成深色** → 蓝底深字看不清（老倪反馈"找不到折叠按钮"）。修法：用 `background:#e9edf2; color:#1f6feb` 浅底蓝字，主题转换后 dark 下变成深底蓝字，两种主题都醒目。
- **面板硬编码浅色**（`#f6f8fa`/`#e9edf2`/`#d0d7de`）在 dark 主题下不协调。本轮把 CICDPanel + PipelinePanel 全量改深色：
  - 对话框背景 `#f6f8fa → #0d1117`
  - 卡片/状态栏 `#e9edf2/#d0d7de → #161b22/#1e2740`
  - 文字 `#1f2328/#24292f/#57606a → #c9d1d9/#8b949e`
  - 按钮 `#e9edf2 → #21262d`
  - **陷阱**：`_refresh` 里也有动态状态样式（else 分支）硬编码浅色，grep 时要用**精确类边界**切片（`awk '/^class X/,/^class Y/'`），否则模板数据/其他类的浅色会误报。

## 5. 验证方法（本仓库 GUI 无 canonical 测试）

`tools/gui/` 无 pytest 覆盖（pytest 面向 src/lerobot 训练框架）。GUI 改动验证 = offscreen 实例化 + 行为断言：

```bash
QT_QPA_PLATFORM=offscreen python3 /tmp/hermes-verify-*.py
```

要点：tempfile 生成脚本 → 实例化真实类（如 `SM.SimulinkModule()`/`studio.StudioMainWindow()`）→ `w.show(); app.processEvents()` → 断言 `isVisible/isHidden`/`_main_split.sizes()`/styleSheet 内容 → 跑完删除。滤镜掉 `Unknown property cursor`/`This plugin does not support` 噪音。
