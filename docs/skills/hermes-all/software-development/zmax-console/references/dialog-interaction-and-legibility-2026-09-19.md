# 工具对话框的交互与可读性铁律 + 判读面板 (2026-09-19 老倪三条返工)

背景: 新增「🧿 DeepSeek-V4-Flash 视觉语言判读」窗口 (`tools/gui/vlm_panel.py`)，用户连报三条:
「最大化的按钮不好使 … 含义里面有很多字, 你给省略了, 窗口还无法拖动。调整显示区域」+「右面显示的字体和背景都是黑色, 看不清啊。字体改成白色」。

## 1. 新建 QDialog 的四条硬要求 (缺一条就被返工)

1. **最大化/拖动**: `QDialog` 默认 flags **不含最大化按钮**，且以主窗为 parent 会被 WM 当瞬时窗口、标题栏拖不动 →
   `setWindowFlags(Qt.Window | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint | Qt.WindowSystemMenuHint)` +
   `setWindowModality(Qt.NonModal)` + `setMinimumSize(880, 560)`（防拖太小把表压扁）。
2. **深色底 + 白字必须显式设**: 对话框**不继承**主窗 QSS，深色主题下就成了**黑字黑底**。复用工程既有配色 `_DARK`
   （见 `tools/gui/calibration_dialog.py`：底 `#0d1117` / 字 `#e6edf3` / 表底 `#161b22` / 表头 `#21262d` / 选中 `#1f6feb`），
   并且要覆盖 `QTableWidget::item`、`QHeaderView::section`、`QTextEdit`、`QScrollBar`、`QToolTip`。
3. **不许省略文本**: `QTableWidget.setWordWrap(True)` + `setTextElideMode(Qt.ElideNone)` + 有长文案的列设 `Interactive`
   并给足宽度(实测 360px) + `verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)`，填表后 `resizeRowsToContents()`。
4. **显示区可自己分配**: 左右栏用 `QSplitter`（`setStretchFactor`/`setSizes`），并在 `resizeEvent` 里**立刻**重排
   （画面按新尺寸缩放、表格重算行高）——不要靠定时轮询；窗口几何存盘（`~/zmax_data/<panel>_geom.txt`）下次照旧。
   顺手删掉残留的中间层 QHBoxLayout，否则控制台刷 `QWidget::setLayout: ... already has a parent` 告警。

## 2. 自己看不见的 UI，用像素统计自审（不要靠猜）

```python
img = dlg.grab().toImage().convertToFormat(QImage.Format_RGB32)   # offscreen 也能渲染
# 采样统计: 亮字(lum>170) / 深底(lum<60) 占比
```
判据: 整屏以深底为主 + 亮字占几个百分点；**表格区域若亮字接近 0 = 还是黑字黑底**（本次修复后实测判读表区域
深底 90.3% / 亮字 9.69%）。其余可同样程序化断言: 最大化后尺寸 ≈ 屏幕、`QFontMetrics(...).boundingRect(colw, TextWordWrap, text)`
证明最长文案换行后不被截断、`splitter.count()==2` 证明显示区可拖分配。

## 3. 面板数据只准来自落盘记录

每次模型调用**落盘一条** `~/zmax_data/vlm_calls.jsonl`(ts/mode/耗时/来源/json/why/帧)，面板只读它；
没有记录就写"暂无判读记录"，**面板禁假值**。字段表三列 `字段 | 含义(物理/工程) | 模型判读`（把模型 JSON 的键翻成人话，
例如"在夹爪上吗 → 是否已在夹爪内(夹持态才可做手眼标定)"）。底部固定一行**人机在环红线**：模型只出"判读+建议"，
机械臂动作一律等操作员确认后下发。

## 4. 控制台重启纪律 (本会话反复用到)

改 `tools/gui/*.py` 后**必须重启控制台**才生效：`pgrep -f "gui-venv311/bin/python studio[.]py"` 拿到真实 python 进程
（**别用 `pgrep -f "studio.py"`，会连 bash 包装一起数**）→ `kill -9 <pid>` → 用
`DISPLAY=:0 XDG_RUNTIME_DIR=/run/user/1000 XDG_SESSION_TYPE=x11` 后台启动 → `sleep 25` 后 `pgrep` 确认**恰好 1 个**实例；
报告里要提醒用户"画布需重新加载/点「状态空间」按钮"（重启会清空画布，无自动恢复）。
