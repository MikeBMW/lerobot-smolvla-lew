# 控制台 DDS 总线窗口 (CANoe 式) —— 接线与坑

## 落点(一个功能一个入口, 不新建模块卡)

`tools/gui/studio.py::DataSpaceModule`(约 3434 行起) 的 `_build()`:

```
顶部: lbl_bus  总线状态条(🚦报文灯 绿/黄/红/黑 · 模块灯 绿/黄/红/黑 · 档位 · 累计报文 · 刷新龄)
_tabs: ① 🗂 全息映射(insertTab(0, wrap))
       ②-⑧ dds_bus.build_tabs(self._tabs)
             → 🚦状态灯 / 🚌总线架构 / 📋报文追踪 / 📊统计 / 🔌信号 / ⚠质量告警 / 📥回灌
       ⑨-⑪ dds_space.build_widget(self, into_tabs=self._tabs) → 频道/数据闭环/字段真值
```

**去重必须“保留最早那个”**：`⚠ 质量告警` 在总线组与 dds_space 里各有一份(重复入口)。
写成 `for i in reversed(range(count)): if tabText(i)==X: removeTab(i)` 会把**两份都删掉**
(Tab 直接消失，不看截图不会发现)。正确：先收集所有匹配索引，保留最小 index，只删其余。

`dds_bus.BusPanel(tabs, status_hint)` 自己起 1s QTimer, 不占线程, 只读 4 个文件:
`~/zmax_data/dataspace/{live.json, trace.jsonl, loop.json, busdb.json}`。

## 坑

* **`loop.json` 的 `stages` 是 list 不是 dict**(字段 `id/name/gate/owner/status/evidence/metrics`)——
  按 dict 写会 `AttributeError: 'list' object has no attribute 'items'`, 而且异常发生在
  `BusPanel.__init__` 的首次 refresh 里 ⇒ **Tab 已经加进去了, 但对象引用没赋上**
  (表现为"界面有 Tab、`panel` 却是 None")。所以: 解析数据一律写成 list/dict 双兼容。
* **首次 refresh 必须包 try/except**: 现场 GUI 不能被一条数据异常打死; 异常写进质量窗口。
* 主 venv **没有 cyclonedds**(刻意保持干净): 页面只读 JSON; 需要发/订 DDS 的动作用
  `subprocess` 调 `~/dds-venv/bin/python tools/dds_bus.py …`(跨 venv 子进程桥)。
* 离屏自检(不打扰用户桌面): `QT_QPA_PLATFORM=offscreen XDG_RUNTIME_DIR=/tmp <gui-venv>/bin/python -c …`
  然后 `widget.grab().save(png)`, 再把 png 交视觉复核。
* 回灌按钮要**先查档位**: prod 档直接拒绝并提示切 calib/test(量产不序列化是预期行为)。
* **深色主题要显式套**: 控制台其余页是深色, 但 PyQt 新建的 QTableWidget/QTreeWidget/QPlainTextEdit/
  QLineEdit 默认**白底**, 配上深色主题的字色 = “看着没字”(实测纯白像素 62~79%)。
  在每个 Tab 顶层 widget 上 `setStyleSheet(DARK_QSS)`(表/树/文本/输入/表头/滚动条都要写),
  改完用 cv2 数每张截图的纯白像素占比验证(应为 0.0%), 不要凭眼看。
* **状态灯墙**: 每个模块/每条话题一盏灯(绿正常·红故障·黄报警·黑无信号), 口径唯一真源是
  `src/lerobot/dataspace/lamps.py`, 页面只读 `live.json` 的 `lamp/lamp_reason/lamp_tally`;
  详见 dds-messaging 技能的 `references/status-lamp-four-colors.md`。
