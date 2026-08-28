# VcXsrv 置顶遮挡/像素残留/滚动残留修复 (2026-08-19 实测)

补充 vcxsrv-render-bugs.md。Feature List 弹窗三连坑，全部实测修复。

## 1. 滚动控件残留 — 子类重写 scrollContentsBy 全量重绘
用户报"Feature List 滚动条拖动只更新左侧窄条, 窗口右侧不动" = XCopyArea 半移 bug
在 QTextBrowser 上的表现。对内容小的滚动控件 (7KB HTML)，**滚动后强制全量重绘**有效:
```python
class _FLTextBrowser(QTextBrowser):
    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)   # 仍做搬运 (可留可不留)
        self.viewport().update()           # 全量重绘覆盖残留, 内容小则无感
```
适用: 任何 QAbstractScrollArea 子类 (QTextBrowser/QPlainTextEdit/QListWidget)。
内容大时慎用 (每帧全量重绘会卡) — 大文档走"升级 VcXsrv/Xvfb+VNC"根治。

## 2. 置顶窗口遮挡新弹窗 — 用户报"打开的是视频"
症状: 操作视频窗口 (WindowStaysOnTopHint + 100ms 播放刷 X 层) 开着时点菜单弹新窗，
新窗被置顶视频盖住 → 用户误以为菜单项打开了视频。
修复: 弹窗前检测置顶视频窗 → `setWindowFlags(flags & ~Qt.WindowStaysOnTopHint)` +
`lower()` (simulink 模块暴露 `_mlp_dlg_or_none()` 供主窗口查询)；
弹窗后延迟双 raise (60/250ms) 压过置顶窗 (VcXsrv z-order 首次 show 不稳)。

## 3. 像素残留污染新弹窗 — 用户报"左侧还是操作视频遗留的"
症状: 视频窗口关闭后其 X 像素残留，新弹窗部分区域显示旧画面。
修复: 弹窗后延迟多次 `viewport().repaint()` + `dlg.repaint()`
(100/400/800/1500ms，repaint 同步立即绘制，逐次覆盖残留区)。

## 4. 判据纪律 (别凭用户描述直接改内容代码)
先 `xwininfo -root -tree` 确认窗口并存/遮挡/隐藏 (IsUnMapped 窗口不算数)；
再 xwd 截图 → ffmpeg 转 png → tesseract OCR 验证内容是否真的渲染正常。
本会话靠这套流程证明 FeatureListDialog 内容其实一直正常，问题是窗口遮挡+残留。
工具: `apt-get install -y x11-apps tesseract-ocr tesseract-ocr-chi-sim` (xwd + OCR)。
