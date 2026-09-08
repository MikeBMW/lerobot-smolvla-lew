# VcXsrv 弹窗三坑 + QTextBrowser 滚动修复 (2026-08-19 实测)

Feature List 菜单弹窗 (帮助文档菜单第一项, studio.py _show_feature_list →
tools/gui/feature_list.py FeatureListDialog) 踩过的坑, 全部 VcXsrv 软渲染下实测。

## 坑1: 置顶窗口 z-order 不稳 → 新弹窗被遮挡 (用户报"打开的是视频")
- 现象: 操作视频窗口(MLPRolloutDialog, WindowStaysOnTopHint 置顶, 播放中)还开着时,
  点菜单弹 Feature List → 新窗口被播放中的视频窗口盖住 → 用户以为"打开了视频"
- 修复: show() 后 QTimer.singleShot(60/250ms) 延迟双 raise_()
- 实测证据: offscreen 触发菜单 action 正确弹 FeatureListDialog; xwininfo 确认窗口存在
  且内容正常 (截图 OCR 验证) → 判定为遮挡而非打开错对象

## 坑2: 频繁刷新窗口关闭后像素残留污染新弹窗 (用户报"左侧还是操作视频遗留的")
- 现象: 视频窗口播放时频繁 XPutImage/XCopyArea, 关闭后 X 层残留 → 新弹窗部分区域
  显示旧画面 (左侧窄条)
- 修复: 弹窗 show 后延迟多次强制全量重绘 repaint (100/400/800/1500ms 四连,
  repaint 同步立即绘制, update 是异步排队可能被合并), 逐次覆盖残留区
- 防污染源: 弹出前置顶遮挡窗口降级 —
  `vd.setWindowFlags(vd.windowFlags() & ~Qt.WindowStaysOnTopHint); vd.lower()`
  (操作视频窗口通过 module._mlp_dlg_or_none() 获取, studio.py 用 self._simulink 访问)

## 坑3: QTextBrowser 滚动条拖动只更新窄条 (用户报"拖动条只能控制左侧很窄范围")
- 根因: VcXsrv XCopyArea 半移 bug (滚动搬运只画部分区域) — 主窗口画布滚动同款
- 修复: 子类化 QTextBrowser 重写 scrollContentsBy:
  ```python
  class _FLTextBrowser(QTextBrowser):
      def scrollContentsBy(self, dx, dy):
          super().scrollContentsBy(dx, dy)
          self.viewport().update()   # 强制全量重绘覆盖残留
  ```
  内容小(7KB HTML)代价无感; 大文档滚动会慢, 需权衡

## Feature List 弹窗实现模式 (可复用)
- 菜单项: `m_doc.addAction("✨ Feature List · 产品特征清单", self._show_feature_list)`
  (QMenu.addAction(text, callable), PyQt5 支持)
- 弹窗: QDialog + QTextBrowser + 深色 QSS + setSizeGripEnabled + 非模态 show()
  (禁 exec_, 弹窗零容忍铁律); 窗口标题禁 emoji (VcXsrv wqy 变 ??)
- HTML 生成: **不要用 % 格式化** — CSS width:100% 会撞占位符报
  "not enough arguments for format string"; 用 %BG% 占位 + .replace() 链
- 验证: 离屏触发菜单 action 断言弹窗类型 + 顶层窗口列表; 截图 xwd+ffmpeg+PIL+tesseract
  OCR 验证内容渲染 (apt install x11-apps 拿 xwd, 无 imagemagick 用 ffmpeg 转 png)
