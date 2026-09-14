# VcXsrv 弹窗遮挡 / 像素残留 / 滚动条窄条 (2026-08-19 实测)

Feature List 弹窗 (QDialog + QTextBrowser) 连续三坑, 全部 VcXsrv 渲染层问题:

## 坑1: 点菜单弹新窗, 用户看到的是「视频」= 置顶窗口遮挡

- 操作视频窗口 (MLPRolloutDialog) 是 WindowStaysOnTopHint 置顶且 100ms 轮播刷新。
- VcXsrv 下多个置顶窗口 z-order 不稳定 → 后 show 的新弹窗可能被盖住,
  用户只看到播放中的视频 → 报「Feature List 打开的是视频」。
- ✅ 修复: show() 后延迟双 raise: `QTimer.singleShot(60, dlg.raise_)` + `250ms`。

## 坑2: 新弹窗内容区残留旧窗口像素 (操作视频画面「遗留」)

- 高频刷新窗口 (视频播放器) 关闭/移走后, X 层像素残留, 新弹窗部分区域被旧画面污染。
- ✅ 修复: show 后延迟多次强制全量重绘 (repaint 同步立即绘制):
  ```python
  def _repaint_fl():
      dlg._browser.viewport().repaint(); dlg.repaint()
  for _ms in (100, 400, 800, 1500): QTimer.singleShot(_ms, _repaint_fl)
  ```
- ✅ 预防: 弹出前检测操作视频窗口 `_simulink._mlp_dlg_or_none()`, 开着则
  `setWindowFlags(flags & ~Qt.WindowStaysOnTopHint)` + `lower()`。

## 坑3: 滚动条拖动只更新左侧窄条, 右侧不动 = XCopyArea 半移

- QTextBrowser 滚动走 XCopyArea 搬运, VcXsrv 下只画部分区域。
- ✅ 修复: 子类 QTextBrowser 重写 scrollContentsBy, 滚动后强制全量重绘:
  ```python
  class _FLTextBrowser(QTextBrowser):
      def scrollContentsBy(self, dx, dy):
          super().scrollContentsBy(dx, dy)
          self.viewport().update()   # 内容小 (几KB HTML) 代价无感
  ```

## 判据 / 验证

- 窗口到底开没开: `xwininfo -root -tree | grep -iE "Feature|视频"` —
  别信用户描述, 先看 X 层窗口列表 (遮挡/残留 vs 真没弹)。
- 内容是否渲染正常: xwd 截图 (apt install x11-apps) + ffmpeg 转 png +
  tesseract OCR 验证关键文字 — 判断是「内容问题」还是「显示层问题」。
- 离屏触发验证: QT_QPA_PLATFORM=offscreen 构建主窗口 → 找到菜单 action →
  trigger() → 枚举 app.topLevelWidgets() 看弹窗类名 — 先证代码链路, 再查显示层。
