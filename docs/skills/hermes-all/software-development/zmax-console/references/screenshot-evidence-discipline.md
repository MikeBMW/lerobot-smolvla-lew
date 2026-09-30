# 控制台页面截图取证 —— 文件名必须与内容一一对应

## 2026-09-29 追加(实测踩到)
- **切过 Tab 再截整页 ⇒ 假亮底**: 逐 Tab 切换后布局重排, 未绘制区域按调色板默认色出图, 实测假白底 7.7%(假警报)。
  规矩: **整合页先截, 再逐 Tab 截**; 每次 grab 前 `processEvents()` 6 次 + `refresh()` + 再 4 次。
- **自定义 QWidget 子类不认样式表 background**: `self.setStyleSheet('background:#0d1117')` 不生效 ⇒ 漏出调色板亮底
  (顶部工具条/底部告警条整条亮)。规矩: 加 `self.setAttribute(Qt.WA_StyledBackground, True)`
  (实测整页纯白 7.88% → 0.12%)。
- **取证要机检化, 别只靠视觉复核**: 标题 vs 卡片几何交叠(`geometry().intersects()`)、文字硬切(labal 是否以 '…' 结尾;
  短名(<28 字)不算)、纯白像素占比(>1% 即亮底) 都能脚本判定并打 ✔/✗, 比再跑一遍视觉复核快一个量级。

## 坑: 用 tab 索引截图 ⇒ 文件名与内容错位

`_DataSpacePage._tabs` 是**所有子组件共享的一个** QTabWidget(总线组 7 个 + dds_space 4 个 +
全息映射)。如果按 `tabs.widget(0..n)` 顺序命名(bus_topology.png / bus_stats.png …),
索引与预期完全对不上 —— 上一轮交付的截图里 “bus_topology.png” 实际是数据空间页,
“bus_stats.png” 实际是报文追踪表, 而且“质量告警”那张根本没生成。视觉复核第一件事就是把它拆穿了。

**规则: 截图按 Tab 文本映射文件名, 不要按索引。**

```python
NAME = {'🚦 状态灯': 'lampwall', '🚌 总线架构': 'topology', '📋 报文追踪': 'trace',
        '📊 统计': 'stats', '🔌 信号': 'signals', '⚠ 质量告警': 'quality', '📥 回灌': 'restbus'}
for i in range(tabs.count()):
    txt = tabs.tabText(i).strip()
    if txt not in NAME: continue
    tabs.setCurrentIndex(i); app.processEvents(); app.processEvents()
    tabs.widget(i).grab().save('.../bus_%s.png' % NAME[txt])
```

顺手在同一个脚本里做**客观量测**: 用 cv2 数每张图的纯白像素占比, 直接验证“深色主题有没有生效”
(改前 62~79% ⇒ 改后 0.0%), 比“我看着是深色”硬得多。

## 坑: 按文本去重会把两份都删掉

为了去掉重复入口, 用 `for i in reversed(range(count)): if tabText(i)==X: removeTab(i)` ⇒ 把所有重名 Tab
(包括要保留的那份)**全删了**(实测“⚠ 质量告警”整个 Tab 消失)。正确做法: 先收集所有匹配索引,
保留最小的那个, 只删其余。

## 坑: 首次 refresh 抛异常 ⇒ Tab 在但对象引用是 None

`Panel.__init__` 里先 addTab 再 refresh; refresh 抛异常时上层 try 捕获 ⇒ 表现为“界面上有 Tab,
但 panel 变量是 None”。所以: ① refresh 自己包 try/except 并把异常写到可见位置;
② 别把“数据解析失败”和“界面没建起来”混成一个失败面。
