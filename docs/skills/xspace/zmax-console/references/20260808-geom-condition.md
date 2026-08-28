# 🧩 几何条件节点 (coord_overlay) — 2026-08-08

## 命名沿革 (老倪定名)
- 飞书端先加「🧩 坐标叠加」(coord_overlay) — 布局 5 模型行各一, 但**未提交 git + GUI 未重启** → 老倪"你没看到"
- 老倪: "连了好几个, 好乱, 简化" → **5 个合并为 1 个共享** (shared: True, 放公共感知链: 数据→YOLO开关→YOLO检测→2D→3D→StateAdapter→🧩)
- 老倪问技术名 → 答: **潜空间条件注入 (Latent Conditioning / Additive Latent Injection)** → 老倪定名 **「🧩 几何条件」(Geometric Conditioning)** — 节点名/布局/LIBRARY/node_logic 关键词全部统一
- ⚠️ **2026-08-08 末再改**: 老倪"几何条件怎么还是单独的 / 在YOLO之前不合理" → **改名「🧩 结构条件」+ 从感知链共享下放各模型行** (视觉主干后, 潜在空间叠加处; 名带 "· 模型" 后缀区分; 连线 StateAdapter→🧩←主干 → 🧩→后续) — 共享定义保留但不创建 (加载跳过, 详见 model-engine ref 第 15 节)

## 技术本质 (写报告/PPT 用)
- 目标物结构坐标 → MLP 投影 → `latent += proj(coords)` (加性注入 latent, 逻辑主线); 图像作背景 token 旁路 (cross-attention 上下文)
- **不是** FiLM 调制 (scale/shift 特征通道), **不是** ControlNet (可训练分支), **不是** 控制振动模态 (模态=模型固有生成先验, 坐标叠加是**加约束/边界条件**不改模态)
- 优势: 零额外参数/零推理开销; 训练注入, 推理 gate 归零可完全剥离

## 实现坑 (全部实测)
1. **新节点类型三步注册**: ①类型表 (NODE_TYPES/COLORS, `"coord_overlay": {"cn": ..., "color": "#58a6ff"}`) ②**add_node 的 icon 字典** (`"icon": {...}[ntype]` — 漏了报 `KeyError: 'coord_overlay'` 模板加载即崩) ③node_logic `_reg(...)` (漏了双击无逻辑)
2. 多会话协作: 飞书端可能只加了一部分注册 → 对账 `git status` + grep 类型名出现处逐个对照
3. **同名节点机制**: 模板布局同名 N 行 = node_specs 定义 N 次 = N 个独立节点 (每定义按布局位置放一个); 共享 = 1 定义 + shared: True
4. **改名一致性**: replace_all 节点名后, 类型注册表的 `"cn"` 值 (类型中文名) 是**另一处** — 不改则面板/绘图显示旧名 (注意全名 grep)

## 会话案例
- 飞书端改本地文件未提交: `git status --short tools/gui/` → simulink_module.py + node_logic.py M → 补 icon 字典 + 提交 f576dcd6
- 验证: hermes-verify-overlaysimplify (1 个共享节点在感知链列5 x=1120, y=80, shared True)
