# 字体渲染坑 (192 DPI 高分屏)

> 实测环境: 3200×2000 / 192 DPI, `QT_SCALE_FACTOR=1.25`, `DISPLAY=:0`。offscreen 默认 96 DPI 会误判字号, 必须在真实屏幕验证。

## QFont 第二参数是 pointSize 不是 px
- `QFont("Arial", 15)` 的 15 是 **pointSize(pt)**, 不是 px。
- 192DPI + QT_SCALE_FACTOR=1.25 下 1pt ≈ 4px（实测: 8pt=32px / 9pt=35px / 10pt=40px / 11pt=43px）。
- 历史 bug: 代码注释写 "15px 大字" 但 `QFont("Arial", 15)` 实为 15pt ≈ 50px → "背景字显示不全 / 字体挤不下"。改字号前先分清 pt/px。
- 目标字号区间 20-26px ≈ 6-7pt。节点标题 9pt≈36px。

## QFont 不接受 float pointSize
- `QFont("Arial", 6.5)` 报错（构造函数 pointSize 参数是 int，不接受 float）。要小数用 `QFont("Arial"); f.setPointSizeF(6.5)`，或直接用整数。
- QSS 可写小数（`font-size:7.5pt`），QFont 构造只能 int — 两条路径降档要分开处理，不能统一替换。

## 双重放大
- `_scale`（QGraphicsView 缩放）与 QSS px→pt 随 DPI 放大叠加 = 字体过大。`_scale=1.4` 曾与 pt 双重放大挤爆节点 → 回 1.0（Ctrl+滚轮仍可再调 0.2~3.0）。

## 节点灰色小字多路径
- 灰色小字 = `pal["label"]`（#8b949e 深色主题）在多处绘制: 类型标签块(~2680-2757) / 参数摘要(~2807-2814) / z700_internal 的 desc / CICD 环节节点类(1580 行那个类)。
- 用户要"删灰色小字/只留白色名称"时, 必须全局搜 `pal["label"]` 和 `#8b949e` 一并删, 不能只删一个类的 desc（上一轮只删了 CICD 节点类, 主画布 NodeItem 的灰色字全漏了, 用户两次反馈"没去掉"）。

## 渲染/遮挡调试
- 后台启动 GUI 时 stderr 重定向到文件: `... python studio.py 2>/tmp/studio_err.log`。
- paint 里 `print(..., file=sys.stderr, flush=True)` + 标志位 `if not getattr(self, "_row_dbg_done", False): self._row_dbg_done = True` 防刷屏（paint 每帧调用）。
- `fm.horizontalAdvance(name)` 返回物理 px, 与逻辑坐标宽度对比可定位"文字超框/被遮挡"。
- ⚠️ `self.mapToScene(QRectF(...))` 返回 **QPolygonF 不是 QRectF** (矩形经变换变多边形) → `.left()/.right()` 抛 AttributeError → paint 异常 → Qt Abort (Fatal Python error: Aborted)。调试代码别假设返回 QRectF, 用 `mapToScene(...).boundingRect()` 或只取顶点。

## 中文节点名按字符拆两行
- 中文名无空格, `.split()` 拆不动 → 整段塞进第一行超宽被 boundingRect 裁掉 = "显示不全"。
- 修: 按空格/·/括号拆词失败后, 按字符贪心拆两行 (`for ch in name: if advance(line1+ch)<=avail or not line1: line1+=ch else: line2+=ch`), 字号 9→8→7 循环兜底保证每行 ≤ avail。
- 节点 w≈160 放不下 7字中文 9pt(252px) → 拆两行每行 3-4 字, 降到 7pt(28px) 才完整。标题垂直居中 `QRectF(8,2,w-36,h-4)` 而非贴顶 y=4。
