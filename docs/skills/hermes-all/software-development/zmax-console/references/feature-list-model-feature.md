# Feature List 展品特征 + 模型 Feature 注册表 (2026-08-19)

## 1. 菜单「✨ Feature List · 产品特征清单」— 展品特征内容规范
入口: 菜单栏最右「帮助文档」第一项 → `studio.py _show_feature_list()` →
`tools/gui/feature_list.py FeatureListDialog` (QTextBrowser + HTML, 深色, 920x680)。
老倪要求 (内容铁律):
- **不强调模型架构** — 禁 ACT/SmolVLA/MLP/VLA-Touch/AWE/latent/backbone/蒸馏/坐标叠加
- 视角: 工程需求 / 标准接口 / 展品特征
- 板块: ① 产品定位 (Z700 L4 / Z700F Fix L2) ② 应用场景 ③ 核心功能 ④ 标准接口 ⑤ 性能指标
- 数据源: Z700_technical_agreement_v3.md (5 场景表: FW Loading ≤6s / 上下料搬运 /
  BI老化箱 ≤60s / 热海柜体 ≤20s / ATS ≤15s, 成功率 ≥99%) + 需求规格书 +
  实测 (插拔 抓起6-8/8 插入4-6/8, 如实标注不吹牛)
- 窗口标题/按钮禁 emoji (VcXsrv wqy 无字形 → ??)，菜单项 emoji 可以

实现坑: HTML/CSS 的 `width:100%` 与 `%` 格式化冲突 → 用 `%TEXT%` 占位符 +
`.replace("%TEXT%", _TEXT)` 链，别用 `% (dict)` 格式化带 CSS 的 HTML。

## 2. 数据字典「🧩 模型 Feature」— 模块化可替换设计 (model_feature.py)
入口: 右侧数据字典树 (ModelTreeDock.refresh()) 顶部顶级节点，仅状态空间画布显示。
老倪要求: 模型特征 + 总体接口 + **模块化开发可换第三方模型** + 工程映射。

设计 (注册表模式，每个模型一份 feature 定义，第三方模型实现同接口即可换装):
```
MODEL_INTERFACES: 8 个标准接口 (ModelSpec 契约)
  IN 输入 / OUT 输出 / CFG 配置 / TRAIN 训练 / DEPLOY 部署 / EVAL 评估 / MON 监控 / SCHED 调度
STATE_SPACE_FEATURES: 10 项, 每项 (名称, 描述, 对应接口, 工程映射)
  F1 物理世界建模→CFG→physical_world_params.html(execution.py)
  F2 状态空间方程 ẋ=Ax+Bu→IN/OUT→flows json+六层源码+node_logic
  F3 前馈PD双通道→CFG/OUT→ff_pd_top.json(双击标定, 只移零点不改根)
  F4 增益调度5阶段→CFG→stab_5stage.py 根轨迹(j1肩瓶颈)
  F5 状态机编排→SCHED→插拔流程 接近/抓取/抬起/转移/插入
  F6 稳定性保证→EVAL→stab_7dof.py STABLE
  F7 仿真验证→EVAL→state_space_sim.py 真仿真
  F8 触觉力控→IN→58D=45+触觉4+CoT9 力控插拔
  F9 可解释决策→MON→大屏决策链
  F10 端侧实时→DEPLOY→0.64M Orin 热更新
```
集成: `build_model_feature_item(module)` 返回 QTreeWidgetItem，`current_model_key(module)`
按画布 nodes 判断 (有 state_space params → state_space)，非状态空间返回 None 不显示。
换装路径: 注册 model_feature.py + 画布模型引擎选择 → 同接口运行。

## 3. 模型 Feature 树结构 (三层)
📦 标准接口 ModelSpec (8 项) → ✨ 模型特征 (N 项, 每项子节点: 接口/工程映射) →
🔄 可替换机制 (接入标准/当前实现/换装路径)。
