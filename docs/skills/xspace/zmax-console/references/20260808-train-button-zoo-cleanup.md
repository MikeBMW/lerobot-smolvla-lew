# 训练按钮 → Simulink Model Zoo 双向注入 + 配置表格 + UI 删除纪律 (2026-08-08)

## 1. 训练按钮 ↔ Simulink Model Zoo 双向注入

老倪: "点击训练按钮, 就是训练 model zoo 的 simulink 模型" — 配置表格与 Model Zoo 数据一致。

连接（StudioMainWindow 构造处）:
```python
self.simulink.set_model_engine(self.model_engine)  # simulink 训练走 Model Engine (已有)
self.model_engine.set_simulink(self.simulink)      # 训练按钮 → simulink on_train (新增反向)
```

TrainingModule:
- `self._simulink = None`（__init__）+ `set_simulink(s)`
- `_start_training()` 开头分流:
```python
if getattr(self, "_simulink", None) is not None:
    pol = tag_map.get(self.model_combo.currentText(), "act")  # ACT→act, SmolVLA→smolvla, SmolVLA+LEW→smolvla_lew, VLA-Touch→vla_touch, AWE→awe_zflow, MLP 蒸馏→expert_mlp, 官方专家→expert_policy
    self._simulink.on_train(policy=pol)
    return
```

## 2. 数据一致性（配置表格 ↔ simulink 节点）

- 配置表格值来自类级 `ZOO_SPEC`（7 模型 × 类别分组）
- simulink 模板训练节点参数必须同源: 曾 steps=1000 vs 表格 4000 → 全模板 `"steps": 1000` → 4000（replace_all 后 ast.parse）
- 改一侧必须 grep 另一侧对齐（表格 steps/batch/lr/VAE ↔ simulink 节点 steps/batch/lr）

## 3. 宝马整车配置表风格（QTableWidget 横向对比）

- 7 模型横列（columnCount = 8: 参数名 + 7 模型），类别分组行 `setSpan(r, 0, 1, n_cols)` 横跨全宽
- 表头/类别行加粗着色（#58a6ff / #00d4aa），亮点值金色（✅/🏆/唯一/novae）
- 只读: NoEditTriggers + NoSelection + NoFocus
- **表格自身滚动条关闭**（setVertical/HorizontalScrollBarPolicy(ScrollBarAlwaysOff)）— 外层 scroll 已有，两个拖动条重复
- 内容全高: `setMinimumHeight(n_rows * 28 + 30)`（外层滚动，表格不截断）

## 4. 删 UI 控件/行的纪律（训练逻辑引用陷阱）

老倪高频操作: 删窗口/控件/行。铁律:
- **删 UI 行 = 只删 addRow/布局挂载，保留 self.xxx 对象**（训练逻辑 `_start_training` 等读 `.value()/.text()/.isChecked()` — 删对象 → AttributeError → 点击训练即崩）
- 批量删 `param_layout.addRow` 行用 python 行过滤（`'param_layout.addRow' in s`）→ 40 处删除后 ast.parse ✓
- **删大块/脚本批量改后必须 ast.parse**：一次删 smolvla_btn 块用行过滤脚本误删了相邻 `topics = {...}` dict 的闭合 `}`（skip 状态泄漏跨块）→ SyntaxError。修复: 读文件定位补回 + ast.parse
- 控件隐藏优先于删除: `setVisible(False)`（对象保留）— 除非老倪明确"删掉"（那也保留 self 对象, 只摘 UI）
- 删前 grep 该名字全部引用（smolvla_btn 有 6 处: 创建/addWidget/setText/setEnabled/setStyleSheet — 全清否则 AttributeError）
- 用户改名纪律: "配置通道"只指参数窗口; 功能页名/按钮名改回要还原（"功能页面原来的模型引擎不要改, 改回去"）— 改名前确认范围

## 5. 本会话 UI 迭代清单（老倪节奏）

- 模型引擎页: 右侧模型下拉删除（对象保留默认 ACT）→ "模型源：Simulink Model Zoo" 徽章（青色 #00d4aa 边框）
- 配置通道: 表格替换旧参数行（40 处 addRow 删）+ SmolVLA 专属信息块删
- Model Zoo 模板: 总系统展开三层（SYS2 数据+GPU / SYS1 Model Zoo / SYS0 硬件 — 三行横排）
- 架构删除: ArchitectureModule 页 + 首页卡 + PAGE_MAP 索引调整（删页后后续索引 -1）+ grid 越界防护（`idx >= len(modules): break`）
