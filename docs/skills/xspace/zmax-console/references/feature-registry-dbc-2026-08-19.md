# 能力特征库 + feature.dbc 方案 (2026-08-19 老倪)

## 用户偏好 (铁律, 编写特征/能力清单时)
1. **能力视角, 不写算法/技术词**: 从「模型能做什么」定义, 禁 YOLO/ẋ=Ax+Bu/Kp/Kd/PD/CoT/
   行为克隆/backbone/微调/safetensors/LeRobotDataset/metaworld 等词。
   例: "YOLO 2D 检测" → "目标识别定位"; "ẋ=Ax+Bu" → "运动规律建模"; "metaworld rollout" → "上岗前考核"
2. **完整定义, 不是关键词**: 每条能力必须含 解释说明(段落)/接口定义(用途+输入+输出+对接)/
   输入信号/输出信号(清单含类型), 长度门槛: explain≥50 接口定义≥40 信号≥20 字符
3. **模型名抽象表达**: 不写具体模型名, 用「类别（例模型）」格式:
   感知（例YOLO）/ 端到端动作（例ACT）/ 世界模型（例LEW）/ 状态空间（例状态空间模型）/
   触觉力控（例VLA-Touch）/ 轻量决策（例MLP）/ 全模型通用
4. **工程映射**: 每条能力带工程落点 (文件/工具/场景/指标), 可落地可追溯
5. **数据流视角**: 状态空间只是众多数据流形态之一 (感知→决策→控制→执行), 不把它当唯一模型

## 能力库结构 (model_feature.py)
- 8 大类 27 条能力: A感知 B决策 C控制 D数据 E学习训练 F部署运行 G对外协作 H工程交付
- 每条: id/name/desc/explain/iface/iface_def/io_in/io_out/scene/eng/app
- 模型组合 MODEL_MANIFESTS: 每模型 = 能力 ID 集合 (state_space 21项/act 19项/...)
- 当前模型识别: 状态空间画布 → state_space; Model Zoo → cmb_model.currentText() 模糊匹配

## feature.dbc 方案 (参考 Vector CANoe DBC)
同一平台/容器内配置不同模型的能力接入, 文件即配置事实:
```
VERSION "1.0"
BU_: STATE_SPACE ACT SMOLVLA VLA_TOUCH YOLO          // 模型节点 (第三方=加节点)
FLOW_: STATE_VECTOR "状态向量流" "..." STATE_SPACE    // 数据流形态
BO_ A1 目标识别定位: IN A                             // 能力 = 消息
 SG_ 解释 : 512 "..."                                 // 完整定义 (解释/接口定义/输入/输出/场景/工程/归属)
 SG_ 输入 : 24 "..."
 SG_ 输出 : 64 "..."
CM_ STATE_SPACE: A1 A2 A3 ...                        // 模型能力组合
```
- 实现: tools/gui/feature_dbc.py — export_dbc/parse_dbc/load_dbc/build_tree_from_dbc/export_excel
- 数据字典树从 feature.dbc 构建 (缺失时自动从 model_feature.py 生成)
- Excel 导出: reports/feature_dbc.xlsx, 3 sheets (能力库 27x11 / 模型组合 / 接口说明), openpyxl
- 帮助文档「Feature List」弹窗含模型能力区块 (当前模型高亮 ← 当前) + 导出 Excel 按钮
- 第三方接入三步: BU_ 加节点 → CM_ 声明能力 → SG_ 信号契约适配 → 平台同流程运行

## 踩坑
1. **% 格式化 vs CSS %**: Python `%` 格式化 HTML 字符串, CSS `width:100%` 和数据里的
   `≥99%` 是裸 % → "not enough arguments for format string"。用 `.replace` 链占位符
   (%ACCENT% 等) 而非 % 格式化, 或全部 %% 转义。两次踩坑 (feature_list.py)
2. **make_item 单参语义**: 树构建辅助函数统一 `make_item(texts)` 单参返回 item +
   `parent.addChild(item)`; 双参调用 (make_item(parent, texts)) 与单参 lambda 不匹配 →
   TypeError 被 except 吞 → 整棵子树不显示且无报错。测试必须用与生产一致的单参 lambda
   (传 QTreeWidgetItem 类会掩盖此 bug)
3. **except 吞异常 = 功能静默消失**: GUI 树/面板构建的 try/except 要 print/logger,
   否则用户报"不见了"排查半天 (本次 feature.dbc 树不显示根因)
