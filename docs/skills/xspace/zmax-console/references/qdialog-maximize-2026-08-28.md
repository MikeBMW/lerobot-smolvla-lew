# QDialog 最大化按钮"不好使" + 状态空间拓扑答疑 (2026-08-28)

## ⚠️ 语言歧义铁律: "不好使" = 修好, 不是禁用
老倪说「XX按钮不好使/没反应/点了没用」 = **功能坏了, 修好它**, 绝不是「不要用/禁用/去掉」。
本会话实例: 老倪说「节点逻辑窗口的最大化按钮不好使」→ 我误解成「不要使」→ 加了
`~Qt.WindowMaximizeButtonHint` 禁用 → 被当场纠正「不是让你禁用啊。修复最大化按钮功能」。
**任何"控件不工作"类反馈, 默认方向 = 修复功能, 除非用户明确说删除/移除。**
(同一家族: 「右键没反应」=菜单弹在屏幕外要修坐标, 不是去掉右键菜单。)

## QDialog 最大化按钮在 X11 下点了没反应 — 根因与修法
**症状**: 节点逻辑 (NodeLogicDialog) / 查看源码 (SourceViewDialog) / 节点参数
(BlockParamsDialog) 标题栏最大化按钮存在但点击无效。
**根因**: QDialog 默认窗口类型 `Qt.Dialog`。在 X11 WM (本机 Xorg/Openbox 系) 下,
Dialog 类型的窗口最大化按钮**画了但 Qt 不响应** (WM 不把 Dialog 当普通窗口处理 maximize)。
**修法**: 显式转普通窗口类型 + 显式三按钮:
```python
self.setWindowFlags(Qt.Window | Qt.WindowMaximizeButtonHint
                    | Qt.WindowMinimizeButtonHint | Qt.WindowCloseButtonHint)
```
⚠️ 不能只加 `Qt.WindowMaximizeButtonHint` 到原有 flags — 必须把类型从 `Qt.Dialog`
换成 `Qt.Window`, 否则 WM 仍不响应。`Qt.WindowStaysOnTopHint` (非模态置顶) 与最大化
不冲突, 可共存。适用: 所有 QDialog 子类 (NodeLogicDialog / SourceViewDialog /
BlockParamsDialog, commit 36b18134)。
**验证 (必须真实 DISPLAY=:0 — offscreen 不渲染 WM 标题栏按钮)**:
```python
dlg.showMaximized(); app.processEvents(); time.sleep(0.2)
assert dlg.isMaximized()
assert dlg.width() >= app.primaryScreen().availableGeometry().width() - 20
```
⚠️ 判定坑: 本机 WM 最大化窗口 = 3068x1862, availableGeometry = 3068x1936
(标题栏/边框差 74px) — 用严格 `>= aw.height()-10` 会误报 FAIL。判据用
`isMaximized()` + 宽度≈屏宽即可。

## 状态空间画布拓扑 (flows/state_space_obs.json, 29 节点)
- **数据源头 = 「📦 metaworld 数据源」节点** (node_logic.py node_metaworld_data,
  默认 source=metaworld 占位集, 可切 orin 真实产线, 双击节点切换):
  📦metaworld数据源 → 📡传感器融合 → 🧩43D统一状态向量 → ⚡前馈加速器/🔮自适应状态估计器/
  📈先验动力学预测器/🧪状态校正器 (S2 并行) → 🧭动作调制器 (S3, 八阶段状态机+否决权)
  → 🛡安全执行边界 (饱和限幅) → 🤖机器人执行器 → 🌍物理世界 (闭环回传感器)。
  3D 视图/操作视频同源的 episode 也是 metaworld 直接驱动 → metaworld 就是逻辑源头, 不是摆设。
- **异常推理器 (🔍 LLM) 画布上是 2 节点反馈环**: 🧭动作调制器 → 🔍异常推理器 → 🧭动作调制器。
  **这是正确的架构, 不要改成返回 🔮自适应状态估计器** (老倪问过「返回状态估计器是不是更好」):
  - 异常推理器输出的是**策略恢复建议** (planner.py ExceptionReasoner.diagnose:
    力控异常→减速重试+复核力阈值 / 对准失败→视觉复核孔位+重新对准 / 插入未到位→复测+低力重插),
    消费方 = 状态机 (决定"下一步动作怎么做")。
  - 状态估计器只消费**观测 z_k** (算"机器人现在在哪"), 喂决策建议会污染状态认知。
  - 大模型层 = 回路外慢决策 (row_bg 注释「云端任务规划 · 慢决策 · 回路外」), 只在
    状态机卡死时 (max_veto 连续否决 / 阶段停留超时 / 接触概率过低) 介入给建议后退出。
  - 若异常根因是"状态估计漂了", 正确路径 = 异常建议 (视觉复核) → 📡传感器融合 → 估计器/校正器,
    这条物理链路画布上已存在, 不需要直接接线。
  - 环在 `_topo_sort` 走「剩余(有环)追加」分支: 不卡死, 只排到末尾; 运行时真执行是
    state_space_sim 引擎, 画布环仅影响展示顺序, 不影响仿真。
