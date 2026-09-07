# 2026-08-08 控制台删改三连 + 参数联动收尾 + 飞书文件交付

## 1. 功能页/按钮删改 (老倪风格: 删=先确认再删, 保留训练按钮)

### 🔬 模型对比 → 🦓 Model Zoo
- `simulink_module.py` replace_all "模型对比"→"Model Zoo"（50 处：模板名/按钮/desc/内部引用一并换——模板名变了按钮文本自动变，加载用新名）
- 验证：`[t[0] for t in REFERENCE_APPS if 'Model Zoo' in t[0]]` + `load_reference_app_by_name` 成功

### Architecture 功能页删除 (首页卡 + stack 页 + PAGE_MAP)
- 删 4 处：首页功能卡元组（`("architecture","🏗️","系统架构",...)`）、`self.stack.addWidget(ArchitectureModule())`、PAGE_MAP `"architecture": 1` + **后续索引全部 -1**（dataset 2→1 ... dataspace 12→11）、首页 "系统架构 Architecture" QLabel（ArchFlowBar 保留）
- ⚠️ **删卡后 grid 越界**：`_modules_grid` 里 `modules[gi*3+c]` 在列表非 3 倍数时 IndexError → 加 `if idx >= len(modules): break` 防护
- 验证：构造 StudioMainWindow 不炸 + `"architecture" not in m.modules` + simulink 索引=10

### ✅SmolVLA 徽章删除 (模型引擎页)
- `smolvla_btn`（QPushButton "✅ SmolVLA"）是 7 模型下拉前的旧遗留——删创建块 + `top_bar.addWidget` + 3 处 setText/setEnabled 引用
- ⚠️ **行级删除脚本危险**：带 skip_until 状态的手写删行脚本（删 setStyleSheet 链）**误删了无关代码的 dict 闭合 `}`**（skip 状态未复位跨段）→ 语法 `'{' was never closed`。教训：**删除必须精确 patch（整块 old_string）**，不要写带状态的行扫描脚本；误删后 `git checkout` 恢复 + 重新精确改
- 验证：`not hasattr(m, "smolvla_btn")` + start_btn/stop_btn/pause_btn 保留 + model_combo.count()==7

### Model Engine 参数窗口删除
- 老倪："选哪个模型显示哪个参数" 之后又"把参数窗口删掉"——**param_group.setVisible(False)** 而非删代码（控件保留 → _on_model_changed/_start_training 读控件不崩，只 UI 隐藏）
- 验证：`not m.param_group.isVisible()`（offscreen 用 isVisible，isHidden/isVisibleTo 不可靠）

## 2. 模型参数联动收尾 (选模型 → 参数全跟随)

- **arch 预设加 steps/batch/lr 键**（7 模型全量）——config 存在读 config（gv 正则），**config 缺失（如官方专家）用 arch fallback**（不留上一模型残留参数）
- `vlm_layers_spin.setRange(4,32)` → `setRange(0,32)`：vlm=0 的模型（ACT/MLP/专家）禁用时显示 0 而非 minimum 4（老倪看"4"以为参数没变）
- config 里 lr 在 `optimizer:` 下缩进 → 正则必须 `^\s*{key}:\s*([\d.eE+-]+)`（`^lr:` 匹配不到缩进行）
- QSpinBox 无 decimals()（QDoubleSpinBox 才有）——setValue try float 先、int 回退

## 3. 飞书文件交付 (视频/DAG json)
- 文本消息只说明路径不够——老倪"把 json 文件给我"要**真文件**：
  1. `POST /open-apis/im/v1/files`（form: file_type=stream + file_name + file=@path）→ data.file_key
  2. `POST /open-apis/im/v1/messages?receive_id_type=chat_id` msg_type=file content=`{"file_key": ...}`
- chats 列表只有 dataworld（bot 未入静界群）——发 dataworld 并注明；静界要发需把 bot 拉进群
- DAG json 导出：offscreen 加载模板 → 构造 `{"format":"zmax-simulink",...,"nodes":m.nodes,"links":m.links}` → 写 flows/模型对比_DAG.json（与 _save_flow 同构）
