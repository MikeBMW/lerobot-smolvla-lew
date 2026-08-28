# Simulink 画布 JSON (load_flow_file) 格式 + 场景上传窗口 + 合作闭环 (2026-08-09 验证)

## 1. load_flow_file JSON 格式铁律 (画布 DAG)
- 格式: `{"format": "<任意标识>", "meta": {...}, "nodes": [...], "links": [...]}`
- **连线字段必须是 `f` / `t`** (不是 src/dst!) —— 源码读 `spec.get("f")` / `spec.get("t")`。
  用 src/dst 时 `f=None` → **连线全部 0 条**, 节点正常建, 极难发现。
- 节点 id 任意字符串 (如 "sup"/"ncond0001") 但要唯一; 连线按 id 查 id_map。
- **⚠️ add_node 的 NODE_TYPES 必须覆盖节点 type**: type 不在 NODE_TYPES →
  `COLORS[ntype]` KeyError → **加载中断, 只建前 N 个节点就停** (无报错可见, 静默截断)。
  症状: JSON 17 节点加载后只剩 8 个 (断在第 9 个不支持的 type)。
  修复: NODE_TYPES 加类型 (如 `"data": {"cn": "数据", "color": "#58a6ff"}`) +
  add_node icon 映射同步加 (如 `"data": "📊"`)。
- 排障: 加载后打印 `[n['type'] | n['name'] for n in m.nodes]`, 看断在哪个 spec。
- 模块库加载 JSON 按钮: LIBRARY 项 `{"flow": "flows/xxx.json"}` → 点击调 `load_flow_file`。
  动态分组按钮: `btn.clicked.connect(lambda _, fl=path: self.module.load_flow_file(fl))`。

## 2. 场景 JSON 上传窗口 UI (双击场景 node, 2026-08-09 老倪)
用户要: "双击打开一个json文件的窗口, 我可以点击上传, 而且能看到上传的链接"
- 双击 scene → `_open_scene` 弹 QDialog (深色底白字, 复用 wsl-display-links §3 样式):
  - 头部: 📋 场景名 + 📊 成功率/节拍 (青绿 #00d4aa 粗体)
  - 📄 JSON 预览: `QPlainTextEdit` (预填 web 格式 payload, **可编辑**)
  - 🔗 上传链接: `QLineEdit` 只读显示 `https://datadrive.world/scene-api.php/<type>` + 📋 复制按钮
  - 结果状态 QLabel (成功 #3fb950 / 失败 #ff4444)
  - 按钮行: [📤 上传到 ECS] (POST editor 内容) [🌐 打开 3D 场景] [✖ 关闭]
- 上传实现: urllib.request POST editor.toPlainText() → 成功显示保存 URL,
  失败显示错误; 上传中按钮 disabled + "⏳ 上传中…"。
- payload 生成: name/skills(工序名列表)/specs(success_rate 小数 0.995, cycle_time)/kpi(全指标)。
- 上传链接可见 + 可复制 = 用户核心诉求 (透明, 可核对)。

## 3. 合作合规数据闭环画布 (cooperation_closed_loop.json, 19 节点 14 连线)
用户要: 供应商提供通用底座 → 我方实验室微调专有模型 → 数据闭环不出实验室。
- 布局三段 + 合规边界 (row_bg 分区):
  - 供应商合作区 (外): 🏭底座供应商 → 📄授权协议 → 🔒数据脱敏网关 → 🧬通用底座
  - 实验室闭环区 (内/SYS2): 📊采集 → 🏷标注 → 🚀SYS2云端训练微调 → 🎯Model Zoo对比 → ✅评估通过 → 📦部署
  - 现场执行区 (SYS1+SYS0): 🧠SYS1动作系统 → ⚙️SYS0硬件驱动 → 🔄新数据回传实验室 (闭环)
  - 🔒合规边界: 🛡数据不出实验室 + 🔐边界防火墙 (右侧竖条 row_bg)
- 连线: 评估不通过 → 回炉 SYS2; feedback → collect 回传闭环。
- 模块库按钮: 数据集分组后加 "🤝 合作闭环" 紫色主题 (border:#a371f733)。
- 数据脱敏/授权协议是合规叙事核心: 供应商只获脱敏底座协议, 原始数据/权重不出实验室。

## 4. ⚠️ row_bg 背景名渲染约束 (合作闭环画布踩坑, 2026-08-09 晚)
- row_bg 名字画在**背景左侧 126px 竖区** (QRectF(x+8, h/2-24, 126, 24), 15px Bold, 按 `+` 拆两行, **无省略号**)。
- **名字 ≤8 字**才完整显示: "实验室数据闭环区 (内部)" 11 字被截断 → 精简为 "实验室闭环区"。验证: `len(name.strip()) <= 8`。
- **节点必须 x ≥ bg.x + 150**: 名字区是背景内 8-134px, 画布坐标 = bg.x+8 ~ bg.x+134。节点 x=150(相对画布)若背景 x=60 → 背景内偏移 90 → **落在名字区内被压住**。规则: 非背景节点 x = max(x, 所在背景.x + 160)。
- 右侧竖条背景(合规边界)同理: 背景 x=990, 节点 x 从 1030 → **1160**; 背景 w 同步加宽 (260→340)。
- 验证: 遍历 背景×节点 两两检查 `bg.x <= nd.x <= bg.x+bg.w and bg.y <= nd.y <= bg.y+bg.h` 时 `nd.x >= bg.x+150` 必成立; 加载后 `len(m.links)` 与 JSON links 数一致 + 打印节点名确认无截断。
