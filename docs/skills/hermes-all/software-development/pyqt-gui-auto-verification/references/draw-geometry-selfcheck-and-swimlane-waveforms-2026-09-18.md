# 自绘窗口的布局自检 (字太小 / 文字重叠) + 多泳道波形模式

来源: 2026-09-18 Z-MAX 旁路实时可视化窗 (`tools/gui/ss_bypass_view.py`)。
老倪原话: 「增加光模块插入的反馈力大小 + 实时 x y z 位置的值, 要用波形显示; 你来调整字体大小,
这个窗口描述的字体太小了, 看不清; 而且波形的名称、描述的字体有重叠, 修改优化一下 UI」。

## 1. 这类抱怨的正确处理顺序 (先结构, 后字号)
旧版把「通道名 + 当前值 + 量程刻度」**都画在同一 x 位置**, 且沿用 10~13px 系统默认小字 →
重叠与"看不清"是必然, 不是偶然。只调字号治不了重叠。

正解 (已验证 0 重叠):
1. **每通道一条独立泳道** (band), 通道数 = 泳道数, 而不是把多条曲线挤进一张图。
2. 文字三处物理分离:
   - 左栏: 第 1 行 = 通道名 (12pt 粗, 灰) / 第 2 行 = 当前值 (16pt, 用该通道颜色)
   - 右栏: 本泳道量程上限 (顶端右对齐) / 下限 (底端右对齐)
   - 绘图区: 只画曲线 + 3 条网格线 + 边框
   左栏 x ∈ [6, gutter], 右栏 x ∈ [x1+5, W-8], `gutter = max(名宽)+20`, `x1 = max(gutter+60, W-右栏宽-8)`
   → 三处 x 区间不相交, 结构上不可能重叠。
3. **字号显式指定, 不吃系统默认** (Noto Sans CJK SC 实测像素高):
   | 用途 | pt | 字高 |
   |---|---|---|
   | 通道名 (Bold) | 12 | 25px |
   | 当前值 (DemiBold) | 16 | 33px |
   | 量程刻度 / 脚注 | 11 | 23px |
   | 组件标题 (DemiBold) | 14 | 29px |
   | 面板标签 | 14 | 29px |
   | 面板数值 | 19 | 39px |
   ⇒ 别再按"12px 就够"写 CSS; 监视类窗口的数值面板 19pt、标签 14pt 是本用户认可的底线。
4. 泳道高下限 = `fm_t.height() + fm_v.height() + 16`, 布局里用 `max(该下限, 均分高度)` 兜底,
   这样窗口被压小时也不会压线。实测: 值行底部 y0+68, 泳道高 99 → 余量 31px。

## 2. 几何自检: paintEvent 与断言共用同一套矩形
关键技巧: 让组件暴露 `layout()`, `paintEvent` 调它取坐标, 自检也调它 —— **断言的就是真实绘制位置**,
不是测试脚本里重抄一遍的公式 (重抄等于没测)。

```python
class CurveWidget(QtWidgets.QWidget):
    def _fonts(self):
        fam = self.font().family()
        return (QtGui.QFont(fam, 12, QtGui.QFont.Bold),      # 通道名
                QtGui.QFont(fam, 16, QtGui.QFont.DemiBold),  # 当前值
                QtGui.QFont(fam, 11),                        # 量程刻度/脚注
                QtGui.QFont(fam, 14, QtGui.QFont.DemiBold))  # 组件标题

    def layout(self):
        """绘制几何 — paintEvent 与自检共用 (自检断言的就是真实绘制矩形)"""
        f_t, f_v, f_a, _ = self._fonts()
        fm_t, fm_v, fm_a = (QtGui.QFontMetrics(f) for f in (f_t, f_v, f_a))
        W, H = self.width(), self.height()
        n = max(1, len(self.bands))
        head, foot, gap = (30 if self.title else 6), 24, 10
        band_h = max(fm_t.height() + fm_v.height() + 16,
                     (H - head - foot - gap * (n - 1)) // n)
        gutter = max(fm_t.horizontalAdvance(b["title"]) for b in self.bands) + 20
        right_w = fm_a.horizontalAdvance("-100.0") + 16
        x0, x1 = gutter, max(gutter + 60, W - right_w - 8)
        info = {"x0": x0, "x1": x1, "band_h": band_h, "gutter": gutter, "right_w": right_w,
                "fm_t": fm_t, "fm_v": fm_v, "fm_a": fm_a, "bands": []}
        for i, b in enumerate(self.bands):
            y0 = head + i * (band_h + gap)
            tb = y0 + fm_t.ascent() + 4                          # 名基线
            vb = tb + fm_t.descent() + 6 + fm_v.ascent()         # 值基线 (在名下, 不叠)
            info["bands"].append({
                "y0": y0, "title_baseline": tb, "value_baseline": vb,
                "title_rect": QtCore.QRect(6, tb - fm_t.ascent(),
                                           fm_t.horizontalAdvance(b["title"]), fm_t.height()),
                "value_rect": QtCore.QRect(6, vb - fm_v.ascent(), 0, fm_v.height()),
                "hi_rect": QtCore.QRect(x1 + 5, y0 + 2, right_w - 8, fm_a.height()),
                "lo_rect": QtCore.QRect(x1 + 5, y0 + band_h - fm_a.height() - 2,
                                        right_w - 8, fm_a.height()),
            })
        return info
```
自检 (offscreen) 断言, 每个通道 4 类两两不相交:
```python
for i, b in enumerate(cw.bands):
    gi = cw.layout()["bands"][i]
    v_rect = QtCore.QRect(gi["value_rect"].x(), gi["value_rect"].y(),
                          fm_v.horizontalAdvance(txt), fm_v.height())   # 宽度要用真实文本量
    left = gi["title_rect"].united(v_rect)
    for a, c in ((gi["title_rect"], v_rect), (left, gi["hi_rect"]),
                 (left, gi["lo_rect"]), (gi["hi_rect"], gi["lo_rect"])):
        assert not a.intersects(c)          # 实测修复后 = 0 对重叠
    print("余量", gi["y0"] + band_h - (gi["value_baseline"] + fm_v.descent()))
```

## 3. 顺序: offscreen 几何自检 → 真 X 冒烟
自检脚本要**真构造窗口 → 真 refresh → `grab().save(png)`**, 并顺手打印"数据是否真进了通道"
(每通道点数 / 最新值), 免得"界面好了但通道全空"这种假通过埋着。
真 X 冒烟 (`DISPLAY=:0` 前台跑, 抓图后 `win.close()`): 验证真渲染路径 + 产出人可看的 PNG。
⚠️ `win.resize(a,b)` 之后实测尺寸常被**内容最小尺寸**顶大 → 用 `win.minimumSizeHint()` 复核,
放不进屏幕就压列数/缩预览图 (本次: 真机位姿面板 3 列→5 列、预览图 320x240→260x195, 高度 1726→1612)。
⚠️ 环境里可能没有 ImageMagick 的 `import`, 别依赖它截图; `QWidget.grab()` 足够且不依赖外部命令。

## 4. 波形数据侧的两个必备件
- **历史从哪来**: 别把整段日志 load 进内存。用模块级"增量尾读"缓存 (记 path + offset, 只读新增字节,
  按最后一个 `b"\n"` 截断消费; 换文件/被轮转则重开) —— 大 jsonl (本次 370MB, 每行 ~5KB) 也能 2Hz 刷新。
  字节级定位用 `raw.rfind(b"\n")` 后再 decode, 不要用"解码后字符长度"去加 offset (多字节字符会错位)。
- **不让噪声变假波动**: 静止通道 (位姿 ±1e-7 m) 若按 min/max 自适应放大, 看着像在抖。
  给每个通道一个 `min_span` 地板 (位姿 1e-4 m / 力 0.1 N), 量程 = `max(实测跨度, min_span)`。
- **量程标注要跟数据同源**: 只在有数据时算 lo/hi, 空数据显示"等待数据…", 缺通道**留空不填 0**
  (本用户的硬要求: 面板禁假值)。
