# 弹窗显示坑 + 内容验证法 + HTML 编码坑 (2026-08-19 Feature List 会话实测)

## 1. VcXsrv 多置顶窗口 z-order 不稳 ("打开的是视频"假象)
- 症状: 多个 WindowStaysOnTopHint 窗口并存时 (操作视频 MLPRolloutDialog 播放中 +
  新弹 FeatureListDialog), VcXsrv 下新弹窗**不压过旧置顶窗口** — 用户点菜单项,
  看到的是播放中的视频窗口 → 误报"打开的是视频"。
- 排查顺序:
  1. `xwininfo -root -tree | grep -iE "Feature|视频|XSpace"` 看窗口列表 —
     新弹窗其实存在且内容正常 (别先怀疑代码链路/信号连接)
  2. offscreen 触发 action (app.topLevelWidgets 快照对比) 验证信号连接无误
  3. 抓用户环境的窗口验证内容 (见 §2), 区分"渲染坏" vs "被遮挡" vs "用户误解"
- 修复: show() 后 `QTimer.singleShot(60, dlg.raise_)` + `singleShot(250, dlg.raise_)`
  延迟双 raise。单次 show()+raise_()+activateWindow() 在 VcXsrv 下不可靠。

## 2. 弹窗内容验证: Qt grab + tesseract OCR (无截图工具)
容器无 imagemagick/xwd (`apt-get install x11-apps` 可拿 xwd, 但 TCP X 下 xwd 截图
不如 Qt 侧可靠; VcXsrv 的 X_GetImage 对隐藏/override-redirect 窗口报 BadMatch):
- 抓指定窗口: 遍历 `app.topLevelWidgets()` 按 windowTitle 匹配 → `w.grab()`
  → save PNG → PIL 打开
- OCR 验证: `tesseract stdin stdout -l chi_sim+eng --psm 3` 识别, 断言关键标题/
  字段在文本里 (中文标题 OCR 会误读个别字: Z700→7700, L4→4, 不影响判定)
- 黑屏判定: numpy `(a>40).any(axis=2).mean()` — 正常内容 ~15%+, 黑屏 <1%
- 对比法: 同时抓"用户环境里已开的窗口"(xwininfo 拿 id, 程序内按 title 匹配)
  和"自己新弹的窗口", 内容一致 = 渲染没问题, 是遮挡/误解

## 3. HTML 字符串 % 格式化与 CSS 冲突 (Python 坑)
- 症状: `_HTML = """<html>...width:100%...</html>""" % {...}` 报
  `TypeError: not enough arguments for format string` — CSS 的 `width:100%`
  和内容里的 `≥99%` 都是裸 %, 被 % 格式化当成占位符
- 修复: 占位符改 `%(x)s` → `%X%` 风格, 结尾 `""".replace("%X%", val)...` 链;
  CSS 的 % 原样保留, 与 replace 无冲突
- 教训: 含 CSS/百分号内容的 HTML 模板**永远用 replace 占位符**, 不用 % 或
  .format (f-string 撞 CSS 花括号同病)

## 4. Feature List 展品特征内容视角 (老倪明确要求, 2026-08-19)
- 入口: 菜单栏最右「帮助文档」下拉第一项 (QMenu.addAction(text, callable) 直接连
  bound method 即可, PyQt5 支持)
- 内容组织铁律: **不强调模型架构** (禁 ACT/SmolVLA/MLP/latent/backbone/蒸馏/
  坐标叠加/39D 等词, 程序 grep 校验), 从工程需求/标准接口角度定义展品特征:
  产品定位 (Z700 L4 / Z700F L2) → 应用场景 (5 大场景表: 节拍+成功率) →
  核心功能 (端侧自主/技能库/力控保护/作业编排/边学边练/仿真先行/多方案管理/
  大屏监督) → 标准接口 (部署热更新/数据SN追溯/监控HTTP/消息飞书/Web/训练容器/
  硬件) → 性能指标 (规格+实测分开, 不吹牛如实标注仿真实测区间)
- 数据来源: Z700_technical_agreement_v3.md (5 场景节拍/成功率) + 需求规格书 +
  实测评估; 与画布模型一一对应
- 展示: QDialog + QTextBrowser 深色表格, 非模态 show (弹窗零容忍铁律);
  窗口标题禁 emoji (VcXsrv 变 ??), 菜单项文字可带 emoji
