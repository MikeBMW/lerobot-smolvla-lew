# 2026-08-08 老倪 UI 删改偏好 + 配置通道表格（会话实测）

## 老倪删改 UI 的纠正模式（多轮实测）

- **删 UI 行保留控件属性**：删参数窗口的行（`param_layout.addRow(...)` 40 处）时**只删 addRow，保留 `self.xxx = QSpinBox()/QCheckBox()` 创建**——训练逻辑（_start_training/_on_model_changed）还读这些控件值，删对象 → AttributeError 崩。删显示 ≠ 删对象。
- **改名先确认范围**：老倪"模型引擎改成配置通道"→ 我把页标题/首页卡/引擎标签/参数窗口全改了 → 老倪"功能页面原来的模型引擎不要改，改回去"——**范围猜错**。正确：先确认他指哪个显示元素（页名 vs 窗口标题 vs 标签），或只改最明确的那个，等反馈再扩散。
- **"删 X 保留 Y" 语义**："删掉 SmolVLA 模型，参数项目保留" → 我理解成删表格 SmolVLA 列 → 老倪"停止删除 smolvla"+"不是删除 smolvla 模型列"——**他指的是删除旧的 SmolVLA 专属信息块**（🧠 SmolVLA Model 标签/vlm_info），不是表格列。删改前先 grep 所有相关显示元素，挑最可能是的那一个，高风险改动先问或先小步。
- **"删表格下面旧参数，不要删表格"**：删范围精确到行（addRow），表格（zoo_table）一根毫毛不动。

## 配置通道 = 宝马整车配置表风格（老倪参考形式）

用户给了宝马 5 系配置表 URL 作为参考——**横向对比表格**：
- 类别分组行（🏗 架构 / ⚙️ 训练 / 📊 数据·输出 / 🏆 性能）横跨全宽（QTableWidget setSpan）
- 表头 = 配置项 + 7 模型横列；参数行 = 参数名 + 各模型值
- 亮点值金色标注（✅/🏆/唯一/novae）
- 只读（NoEditTriggers + NoSelection）
- 数据源类级常量 ZOO_SPEC（list[(类别, [(参数, {模型: 值})])]）+ ZOO_MODELS（7 模型列表）
- 旧参数控件隐藏/删行后表格是配置通道主体

## 其他本轮 UI 改动速记

- Architecture 功能页删除：首页卡 + stack.addWidget + PAGE_MAP（后续索引 -1 连锁）+ _modules_grid 越界防护（删卡后列表非 3 倍数 → `if idx >= len(modules): break`）
- ✅SmolVLA 徽章（旧单模型按钮）删除：grep 全部引用（创建 + addWidget + setText/setEnabled/setStyleSheet）一并清；**批量删 setStyleSheet 链时 QSS 块残留会坏语法**（`QPushButton {{` 孤立）→ 删后必须 ast.parse 验证，残留手动清
- 模型对比 → Model Zoo 改名：模板名 replace_all 50 处（subsystem 指向/加载名/desc 全同步）
- 总系统展开三层：subsystem 指向新模板「🏗 三层总系统」（SYS2 数据+GPU / SYS1 Model Zoo / SYS0 硬件配置，三行横排）

## 验证风格（沿用）

tempfile ad-hoc 脚本用后即删；offscreen 下 isVisible/isHidden 语义怪（parent 未 show）——用 isVisible()（False=隐藏生效）或直接构造断言；fresh 验证命名 hermes-verify-<主题>-<随机>.py
