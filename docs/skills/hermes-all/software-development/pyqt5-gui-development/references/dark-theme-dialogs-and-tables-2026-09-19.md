# 深色主题下的对话框/面板 + 表格可读性 (2026-09-19 老倪三轮反馈实录)

场景: 新建的判读面板 (`tools/gui/vlm_panel.py`) 上线后老倪连发三条:
①「右面显示的字体和背景都是黑色, 看不清啊。字体改成白色」
②「最大化的按钮不好使 … 含义里面有很多字, 你给省略了, 窗口还无法拖动」
③「调整显示区域」

根因都不是"审美", 而是 **Qt 默认行为在深色主窗口下没人管**。按下面这份清单做, 一次就能过。

## 0) 铁律: 新建 QDialog/QWidget 面板**必须显式 setStyleSheet**

深色主窗口 (`app.setStyleSheet(_build_global_qss())`) **不会**自动把颜色带给 `QDialog` 里那些
用系统默认 palette 画的控件 → 黑字黑底。别指望继承, 显式设。

**抄工程既有配色, 别自己发明** (老倪会看出来不一致):
```python
# tools/gui/calibration_dialog.py 里的 _DARK 就是本工程规范
_DARK = ("QDialog { background:#0d1117; color:#e6edf3; } "
         "QLabel { color:#e6edf3; background:transparent; } "
         "QTableWidget { background:#161b22; color:#e6edf3; border:1px solid #30363d; "
         "gridline-color:#30363d; alternate-background-color:#0d1117; } "
         "QTableWidget::item { color:#e6edf3; padding:3px; } "
         "QTableWidget::item:selected { background:#1f6feb; color:#ffffff; } "
         "QHeaderView::section { background:#21262d; color:#e6edf3; border:none; padding:5px; } "
         "QTextEdit { background:#161b22; color:#e6edf3; border:1px solid #30363d; } "
         "QPushButton { background:#21262d; color:#e6edf3; border:1px solid #30363d; "
         "border-radius:5px; padding:7px 14px; font-size:13px; } "
         "QPushButton:hover { background:#1f6feb; color:#ffffff; } "
         "QScrollBar { background:#0d1117; } "
         "QToolTip { background:#161b22; color:#e6edf3; border:1px solid #30363d; }")
...
self.setStyleSheet(_DARK)
```
新控件别忘了单独配: 自绘/占位 QLabel (`background:#161b22; color:#8b949e`)、提示行 (=加框+琥珀字
`#f0c674` 更醒目, 老倪对"红线/闸门"类文字接受加框)。

## 1) QDialog 默认没有最大化按钮, 传了 parent 还会"拖不动"

症状: 用户点最大化没反应 / 标题栏拖不动窗口。两个原因叠一起:
- `QDialog` 默认 window flags **不含** `WindowMinMaxButtonsHint`
- 以画布为 `parent` 构造 → 被当瞬时窗口 (transient), 在部分 WM 下标题栏拖动/最大化被禁

```python
self.setWindowFlags(Qt.Window | Qt.WindowMinMaxButtonsHint
                    | Qt.WindowCloseButtonHint | Qt.WindowSystemMenuHint)
self.setWindowModality(Qt.NonModal)
self.setMinimumSize(880, 560)          # 别只给 resize(), 否则用户能拖成一条缝
self._restore_geom()                   # 见 §4
```
验收断言 (offscreen 也能测): `bool(int(p.windowFlags()) & int(Qt.WindowMinMaxButtonsHint))`,
`p.isWindow()`, `p.showMaximized()` 后 `p.width() >= 屏宽*0.95`.

## 2) 表格文字被省略号截掉 → 换行 + 关省略 + 行高自适应

症状: 长文本列"后面那截没了"。默认 `QTableView` 单行 + 省略号, 列宽固定就更糟。

```python
tbl.setWordWrap(True)
tbl.setTextElideMode(Qt.ElideNone)                 # ← 关键: 不省略
hh = tbl.horizontalHeader()
hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)   # 短列: 按内容
hh.setSectionResizeMode(1, QHeaderView.Interactive)        # 长文本列: 给足宽 + 用户可拖
hh.setSectionResizeMode(2, QHeaderView.Stretch)            # 主内容列: 吃掉剩余
tbl.setColumnWidth(1, 360)
tbl.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)  # 行高随换行涨
tbl.verticalHeader().setVisible(False)
# 每次填完表:
tbl.resizeRowsToContents()
```
**自检 (无视觉, 用字体度量代替眼睛)**:
```python
fm = QFontMetrics(tbl.font())
need = fm.boundingRect(0, 0, colw - 10, 2000, Qt.TextWordWrap, longest_text)
lines = max(1, (need.height() + fm.height() - 1) // fm.height())   # 实测 28 字 → 3 行, 完整显示
```

## 3) "调整显示区域" → QSplitter, 不是固定布局

中部两块 (图 / 表) 用 `QSplitter(Qt.Horizontal)` + `setStretchFactor(0,4); setStretchFactor(1,5)`
+ `setSizes([560, 660])` → 分隔条可拖动, 用户自己分配。
再补 `resizeEvent` **即时**重排 (别等 5s 轮询): 重设 QPixmap 缩放 + `resizeRowsToContents()`。

⚠️ 坑: 若把布局先 `mid.addLayout(left)` 又 `_lw.setLayout(left)` → 控制台刷
`QWidget::setLayout: Attempting to set QLayout ... when the QLayout already has a parent`。
交给 QSplitter 承载就别再往中间层 addLayout。

## 4) 窗口几何记忆 (用户拖动/最大化后下次照旧)

```python
GEOM = os.path.expanduser("~/zmax_data/<panel>_geom.txt")

def _restore_geom(self):
    try:
        x, y, w, h = (int(v) for v in open(self.GEOM).read().split()[:4])
        self.setGeometry(x, y, max(w, 880), max(h, 560))
    except Exception:
        self.resize(1240, 780)

def closeEvent(self, e):
    g = self.geometry()
    open(self.GEOM, "w").write(f"{g.x()} {g.y()} {g.width()} {g.height()}")
    super().closeEvent(e)
```

## 5) 面板自审清单 (交付前逐条打勾)

| 检查 | 手段 |
|---|---|
| 白字深底 | 渲染后数像素: 深底占比 >70% 且亮字 >3%; **分区再看**关键表格区 (实测 90.3% 深 / 9.69% 亮) |
| 最大化可用 | flags 断言 + `showMaximized()` 尺寸跟随屏幕 |
| 长文本完整 | 字体度量算行数 (或断言 `ElideNone` + 列宽 ≥ 300) |
| 显示区可调 | `splitter.count()==2` + `sizes()` 合理 |
| 无告警 | 运行日志没有 `setLayout ... already has a parent` / `propagateSizeHints` 之外的异常 |
