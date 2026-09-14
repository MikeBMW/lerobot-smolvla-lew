# PyQt5 Python 子类 + QSS 警告 / 行号编辑器 (2026-08-18 实测)

## 坑: Python QObject 子类 + setStyleSheet = "Could not parse stylesheet"

- 症状: 给 PyQt5 **Python 子类**（`class _CodeEditor(QPlainTextEdit)`）调 setStyleSheet 时, stderr 刷
  `Could not parse stylesheet of object _CodeEditor(...)`（每次设置/polish 各一次, 烦人但不崩）。
- 根因: PyQt 为 Python 子类注册**动态 metaObject**（`w.metaObject().className()` 返回 `_CodeEditor`
  而非 `QPlainTextEdit`）→ Qt QSS 解析器不认这个类名 → 解析失败警告。
  同款 QSS 放在标准类 QPlainTextEdit 上无警告 = 铁证是子类问题。
- 修复: **编程式样式绕开 QSS**:
  ```python
  f = QFont("DejaVu Sans Mono", 12); f.setStyleHint(QFont.Monospace)
  w.setFont(f)
  pal = w.palette()
  pal.setColor(QPalette.Base, QColor(_BG))
  pal.setColor(QPalette.Text, QColor(_TEXT))
  pal.setColor(QPalette.Highlight, QColor(_GOLD))
  pal.setColor(QPalette.HighlightedText, QColor("#000000"))
  w.setPalette(pal)
  w.setFrameShape(QFrame.StyledPanel)
  w.setStyleSheet("")   # 清继承样式
  ```
  必须用 QSS 时: 标准类包一层（QFrame 容器设边框 QSS, 内部子类 widget 无 QSS）。

## 行号编辑器模式 (SourceViewDialog 2026-08-18)

`_CodeEditor(QPlainTextEdit)` 持有行号区 QWidget 子 widget:

- `resizeEvent` 同步几何:
  `ln_area.setGeometry(cr.left(), cr.top(), ln_area.sizeHint().width(), cr.height())`
- 行号区 `paintEvent`: 遍历 `firstVisibleBlock()`, 每个 block 用
  `blockBoundingGeometry(block).translated(contentOffset()).top()` 算 top, 画 `blockNumber()+1`
- 行号区宽度: `10 + fontMetrics().horizontalAdvance("9") * len(str(blockCount()))`
- 触发刷新: `blockCountChanged` / `updateRequest` / `cursorPositionChanged` → `ln.update()`

## 相关: 容器环境功能链路自适应 (zmax-console open_node_source 2026-08-18)

纯 Docker Desktop 容器（无 /mnt/c、无 explorer.exe、无 WSL interop）下, 凡依赖 Windows 通道的
功能必挂。右键「打开源代码」老链路（复制到 /mnt/c/zmax_src_view + explorer.exe 打开）实测失败,
已改环境自适应:

```python
if os.path.isdir("/mnt/c") and shutil.which("explorer.exe"):
    # WSL 老家: 老链路 (复制 + explorer.exe)
else:
    # 容器: SourceViewDialog 弹窗 (绝对路径 + 行号 + 📋复制路径按钮 + 只读源码)
```

新功能若要走 Windows 侧（explorer / 浏览器 / 盘符路径）, 先探测 /mnt/c 与 explorer.exe,
容器环境给容器内回落方案, 别假设 WSL 通道存在。
