# VcXsrv 渲染坑 — 2026-08-19 复现与新兜底 (补充 vcxsrv-render-bugs.md)

## 1. XCopyArea 半移复现 → 分块 repaint 兜底 (新技巧)
⚠️ **XCopyArea 位块移动不是永远可靠**! 08-18 时正常, 08-19 VcXsrv 会话状态变化后搬运也坏:
滚动时上半部(露出重绘)正常、下半部(搬运区)残留不动 → 用户报"屏幕又变成上动下不动"。
- 判定: 滚动后残留区 = 搬运区, 露出区正常 → XCopyArea 坏, 不是 Qt 逻辑问题
- ✅ 兜底修复 (SimCanvas.scrollContentsBy 重写):
  ```python
  def scrollContentsBy(self, dx, dy):
      super().scrollContentsBy(dx, dy)
      vp = self.viewport()
      w, h = vp.width(), vp.height()
      if w > 20 and h > 20:
          for _y in range(0, h, 400):
              vp.repaint(0, _y, w, min(400, h - _y))   # 分块同步重绘
  ```
  关键: **必须 repaint(rect) 同步且分块 (400px 高 = 小 XPutImage)**; 不能用 update() —
  update 合并 dirty region 成大矩形 → 又踩大 XPutImage 只画顶 bug。画布节点少时性能无感。
- QTextBrowser 等 Qt 内置滚动控件同病: 重写 scrollContentsBy, super() 后
  `self.viewport().update()` 全量重绘 (内容小, 代价无感) — Feature List 弹窗实测

## 2. 像素残留污染 (置顶窗口关闭后)
操作视频窗口(置顶, 播放中每帧刷 X 层)关闭后 VcXsrv 不清残留 → 新弹窗部分区域显示旧视频
画面 ("feature list 左侧是操作视频遗留")。修复:
- 弹窗 show 后延迟多次全量重绘 (100/400/800/1500ms repaint, 逐次覆盖残留区)
- 弹窗前把置顶视频窗口降置顶: `setWindowFlags(flags & ~Qt.WindowStaysOnTopHint)` + `lower()`
- ⚠️ 延迟回调访问窗口必须先 `sip.isdeleted(dlg)` 检查 — 窗口 deleteLater 后回调访问
  已删 C++ 对象 → Segfault (2026-08-19 实测 qFatal, 日志特征 QObject::killTimer/
  Timers cannot be stopped from another thread + Fatal Python error: Segmentation fault)

## 3. 弹窗被置顶视频窗口遮挡 (用户报"Feature List 打开的是视频")
VcXsrv 下多置顶窗口 z-order 不稳, 后 show 的置顶窗口可能被播放中的视频窗口盖住。
修复: show 后 QTimer.singleShot(60/250ms, dlg.raise_) 延迟双 raise。

## 4. 排查工具 (本会话新增)
- `xwd` 截图 + `ffmpeg -i fl.xwd fl.png` + tesseract OCR = 无头验证窗口内容是否渲染正常
  (apt-get install x11-apps tesseract-ocr tesseract-ocr-chi-sim)
- 判定视频/窗口"内容对但显示错": xwininfo -root -tree 查窗口列表 → xwd 截目标窗口 →
  OCR 验证内容, 区分"代码 bug" vs "VcXsrv 显示 bug"
