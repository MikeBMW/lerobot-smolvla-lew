# Model Zoo 配置对比表 + 改名规则 + 三层总系统 (2026-08-08)

## Model Zoo 横向配置对比表（宝马整车配置表风格）

老倪：参考宝马车型配置表（https://www.bmw.com.cn 选车对比表）——**类别分组 × 模型横列**。

实现（studio.py TrainingModule）：
- 类级 `ZOO_SPEC`：`[(类别, [(参数名, {模型: 值, ...}), ...]), ...]`——类别 = 🏗 架构 / ⚙️ 训练 / 📊 数据·输出 / 🏆 性能；7 模型 = ZOO_MODELS 列表（ACT/SmolVLA/SmolVLA+LEW/VLA-Touch/AWE/MLP 蒸馏/官方专家）
- `_build_zoo_table(layout)`：QTableWidget（NoEditTriggers/NoSelection/隐藏表头）——表头行（参数名 + 7 模型列，蓝底加粗）→ 每类别：**类别行 setSpan(r,0,1,n_cols) 横跨全宽**（青色 #00d4aa）+ 参数行（参数名列加粗 + 各模型值居中）
- 亮点值金色 #ffd33d：值含 ✅/🏆/唯一/novae
- 旧参数控件（steps_spin 等）setVisible(False) 隐藏——**控件保留**（训练逻辑读值），表格替代显示
- 调用：param_layout 创建后 `self._build_zoo_table(param_layout)`

## 老倪改名/页面规则（重要——反复踩）

1. **功能页名"模型引擎"不要改**：曾改"配置通道"（页标题+首页卡+引擎标签）→ 老倪"改回去"——**页名保持"模型引擎"**（首页卡/页标题 🧠 Model Engine/引擎标签 🖥 模型引擎:）
2. **"配置通道" = 参数窗口名**（param_group QGroupBox 标题）——只此一处；若页标题和参数窗口都叫"配置通道"= 老倪看到"两个配置通道"（重复）
3. **模型对比 → Model Zoo**：replace_all 50 处（模板名/按钮/加载/desc——simulink_module）
4. 删除模式（老倪高频"删掉 X"）：
   - **删功能页**（ArchitectureModule）：首页卡 + `stack.addWidget` + **PAGE_MAP 索引连锁**（后续键值全部 -1）+ **grid 越界防护**（`_modules_grid` 的 `gi*3+c` 需 `idx >= len(modules): break`——模块数非 3 倍数必崩）
   - **删徽章**（✅ SmolVLA 按钮）：创建块 + addWidget + 所有引用（setText/setEnabled/setStyleSheet 链）——用 python 删行**要小心**：误删 dict 闭合 `}`/QSS 残留 → 语法崩（`{` never closed）；删后 `ast.parse` 全文件验证 + grep 无残留
5. **保留训练按钮**：删模型引擎子窗口时，训练按钮（start/pause/stop）+ 模型下拉保留

## 三层总系统展开（subsystem 链）

老倪 08-08 架构：总系统双击展开 = 三层（三行横排）：
- 🖥 SYS2 云端训练（顶层）：📦 数据集合 + 🖥 GPU 服务器
- 🧠 SYS1 动作系统（中层）：🔬 Model Zoo（subsystem → 再双击展开七模型）
- 🔧 SYS0 硬件驱动（底层）：🔧 硬件配置

实现（simulink_module REFERENCE_APPS）：
- 新模板 `"🏗 三层总系统"`（7 节点 + 三行 layout——y=[80,310,540]）
- 总系统模板的 subsystem 指向 `"🏗 三层总系统"`（原指向 "🔬 Model Zoo"）
- 验证：加载三层模板 → 7 节点 + 3 个不同 y（三行横排）+ Model Zoo 节点 params.subsystem == "🔬 Model Zoo"

## 验证风格

- 每轮 UI 改动：tempfile ad-hoc 脚本（offscreen 构造 + 断言）+ 用后即删
- offscreen 下 isHidden/isVisibleTo 语义怪——用 `not isVisible()` 判断隐藏
- 断言字符串拼接别写错引号（`'... in src and ...'` 整体成字符串 → 误报失败，分两个断言）

## 删 UI 行保留对象（配置通道后续清理——老倪高频模式）

表格建好后老倪连续要求清理右侧/下方旧 UI——**铁律：删显示行，保留对象（self.xxx）**，否则训练逻辑 `_start_training` 读 `steps_spin.value()` 等直接 AttributeError 崩：

1. **删旧参数行**（Freeze SmolVLM/Action Steps/VLM Layers/Expert Width/Obs Steps/Chunk/Max State·Action Dim 等 40 处）：只删 `param_layout.addRow(...)` 行（python 行过滤 `'param_layout.addRow' in s and not s.startswith('#')`），**控件创建代码保留**（self 属性——训练读值 ✓）。注意 `_build_zoo_table` 里的 `layout.addRow(t)` 是表格本身——别误删
2. **删右侧模型选择下拉**：删 `model_lbl`（QLabel"🤖 模型:"）创建+addWidget + `top_bar.addWidget(self.model_combo)`——**model_combo 对象保留**（self——训练逻辑 currentText() 默认 ACT 第一项）
3. **删 SmolVLA 专属信息块**（"🧠 SmolVLA Model" policy_label + `vlm_info` QLabel"SmolVLM2-500M-Video-Instruct…"）——老倪说"删掉原来的 SmolVLA 模型"指这个信息块，**不是**表格模型列！曾误删 ZOO_MODELS 的 SmolVLA 列 → 老倪连续两条"不是删除smolvla模型列/停止删除smolvla"——**"删掉 X 模型"歧义：先分清是 列 / 信息块 / 徽章**；误改立即 git revert 改回（git checkout 单文件）
4. **表格滚动条去重**（右侧两个拖动条=表格自身+外层 scroll）：表格 `setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)` + `setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)` + `setMinimumHeight(n_rows*28+30)`（内容全高——**不要 min(..., 420) 截断**）——外层 scroll 滚动，表格不滚
5. 每次删完：ast.parse 全文件 + offscreen 构造断言（表格保留/对象保留/无残留 grep）+ 提交后 kill -9 重启（gateway 自动拉起）

## 模型源徽章 + 训练数据一致性（老倪：配置表 ↔ Model Zoo 同源）

- **"模型源：Simulink Model Zoo"**：模型引擎页 top_bar 右侧加青色徽章 QLabel（`color:#00d4aa; background:#0d2a24; border:1px solid #00d4aa; border-radius:4px; padding:4px 10px; font-size:11px; font-weight:bold`）——标识配置与训练统一走 simulink Model Zoo
- **数据一致性铁律**：配置表格（ZOO_SPEC/arch 预设）的值必须 = simulink Model Zoo 训练节点（🚀 XX 训练 params）的值 = config yaml 的值——曾发现 simulink 节点 `"steps": 1000` 而表格/config 4000 → 统一 replace_all 1000→4000（20 处）
- 老倪明确："点击训练按钮 = 训练 model zoo 的 simulink 模型"——训练入口（模型引擎 Start）应触发 simulink on_train（policy 对应模型），不是独立训练路径（此连接待注入：TrainingModule.set_simulink + _start_training 调 simulink.on_train；simulink 训练节点参数 steps/batch_size/lr 与表格对齐后 on_train 才能用对值）
- 注意：新版 lerobot_train 参数格式可能与本地 GUI 调用不一致（`--config-path` unrecognized）——训练提交参数要按实际 lerobot_train.py 支持的格式（Hydra/自定义）对齐，别照抄 docker 命令
