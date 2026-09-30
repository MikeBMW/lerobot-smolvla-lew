# 版本迭代 2026-08-16 — v2.1.1 实测要点

## 版本号实际散落 5 处 (不是 3 处!)

1. `tools/gui/studio.py` 窗口标题: `self.setWindowTitle("XSpace Studio — Z-MAX v2.1.1 [W-01]")` (~L9245)
2. `tools/gui/studio.py` 侧栏 QLabel: `ver = QLabel("Z-MAX v2.1.1")` (~L230)
3. `tools/gui/update_checker.py` `CURRENT_VERSION = "v2.1.1"` (~L10)
4. `tools/gui/docs_sync.py` `"version": "v2.1.1"` (~L193)
5. `tools/gui/docs_sync.py` `"zmax_version": "v2.1.1"` (~L197)

`tools/ci/integrity_check.py` 里 `EXPECTED_VERSION` 也要同步改 (检查器比对 5 处)。

注意: 2026-08-16 发现 update_checker.py / docs_sync.py 停在 v1.8.0 而 studio.py 已是 v2.1.0 — 之前迭代只改了 studio.py 两处, 检查器 EXPECTED_VERSION 也没跟着升, 一直假绿。升级时必须 5 处 + 检查器全改, 跑 `python3 tools/ci/integrity_check.py` 真绿才算。

## 完整性检查器 2 个坑 (2026-08-16 修复)

### 坑1: SimulinkModule 延迟创建 → addWidget 检查漏检

- 2026-08-12 起 SimulinkModule 改为延迟创建: `QTimer.singleShot(400, self._init_simulink)`, 在 `_init_simulink` 里 `self.stack.insertWidget(self._simulink_index, sim)` 插回原位。
- 检查器 `get_addwidget_order` 原来只认 `addWidget`, 不认识 `insertWidget` → SimulinkModule 永远不在顺序里 → 报 "stack addWidget 顺序不一致"。
- 修复 (integrity_check.py):
  1. `f.attr in ("addWidget", "insertWidget")`
  2. 参数位置不同: `a = node.args[1] if f.attr == "insertWidget" else node.args[0]` (insertWidget(index, widget))
  3. ALIAS 加 `"sim": "SimulinkModule"` (局部变量名)
  4. 比较时剔除 SimulinkModule (延迟创建源码顺序≠运行时顺序), 单独验证 `"SimulinkModule" in addw`

### 坑2: insertWidget 源码顺序 ≠ 运行时顺序

`_init_simulink` 方法体定义在 `__init__` 之后, AST 遍历按源码顺序 → insertWidget 出现在 DataSpaceModule/ArchitectureModule 之后, 但运行时是插回 _simulink_index (在 DataSpace 之前)。不能直接按 AST 顺序比较 — 剔除延迟创建的类再比。

## 提交节奏

```bash
python3 tools/ci/integrity_check.py   # 先真绿
git add -A && git commit -m "release: Z-MAX v2.1.1 — <改动说明>"
git tag v2.1.1 && git push origin main --tags
git ls-remote --tags origin | grep v2.1.1   # 验证远端 tag 指向新 SHA
```

## 本次迭代内容 (v2.1.1)

- model_tree.py 数据字典右侧列表 (ModelTreeDock QTreeWidget) 字体 11px→13px, padding 2px→4px; 视图切换下拉 12px
- integrity_check.py 支持延迟创建 (上述 2 坑)
- 附带: flows/ 数学化 JSON 更新 + reports/dev_flow_report.md/pdf + configs/scenes/scene_config.yaml (新场景配置, 入库)
