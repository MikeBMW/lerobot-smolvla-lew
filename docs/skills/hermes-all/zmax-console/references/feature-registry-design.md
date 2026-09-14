# Feature Registry 特征库体系 — 系统工程模块化设计 (2026-08-19 老倪)

数据字典右侧列表的「🧩 特征库」= model_feature.py (tools/gui/), 供数据字典树
(ModelTreeDock.refresh) 展示当前模型特征。老倪方法论, 后续加模型/加特征照此扩展。

## 老倪的设计要求 (必须遵守)
- **按系统工程模块化思维划分**, 不按模型划分: 状态空间只是众多数据流形态中的一种
- **参考 LeRobot 生态标准**: PretrainedPolicy 接口 / @register_subclass 注册机制 /
  LeRobotDataset 格式 / ProcessorStep 管道
- **偏向功能**, 特征可**复用/增加/组合**; 第三方模型注册 Manifest + 缺失特征适配器
  即可换装, 同接口进训练/评估/部署/监控管道
- **每个特征必须有三要素**: explain 解释(功能定义) / io 输入输出信号(IN→OUT 契约) /
  scene 使用场景; 另带 iface(接口) / eng(工程映射=文件工具落点) / app(适用模型)

## 数据结构 (model_feature.py)
- DATAFLOW_STAGES: 感知→决策→控制→执行 四环节 + 当前模型形态
  (状态向量流 / 图像→动作流 / 视频预测流 / 感知专用流)
- FEATURE_LIBRARY: 8 大类 27 条, 每条 dict {id,name,desc,explain,io,scene,iface,eng,app}
  A感知(4) B决策(5) C控制(4) D数据(3) E训练(3) F部署(2) G接口(3) H工程(3)
- MODEL_MANIFESTS: 模型 key → {name, dataflow, features: set(特征ID)}
  已有: state_space(21项) / act(19) / smolvla(20) / vla_touch(21) / yolo(3)
- current_model_key(module): 状态空间画布(state_space params)→state_space;
  Model Zoo→module.cmb_model.currentText() 模糊匹配; 否则 None(只显示库总览)
- build_model_feature_item(module) → QTreeWidgetItem 顶级节点:
  🔄数据流形态 → 📂8大类(✓选中/○未选用, 每条6子节点) → 📦当前模型组合(选用/未选用/可替换机制)

## 加模型/加特征步骤
1. 新特征: FEATURE_LIBRARY 对应大类加 dict, 三要素必须齐全 (程序校验: 27条全齐)
2. 新模型: MODEL_MANIFESTS 加 {name, dataflow, features}, 复用已有特征 ID
3. 第三方模型: 同 2, 缺失能力在 FEATURE_LIBRARY 注册新特征 → 适配器实现
4. 验证: offscreen 构建 FakeMod(nodes/cmb_model) 调 build_model_feature_item
   (状态空间/ACT/空画布三态都要测)

## 展示注意
- 树深: 大类→特征→6子节点, 数据字典树本来就深, 可接受
- 特征行值列=简述, 子节点依次 解释/信号/接口/场景/工程映射/适用
- 弹窗类展示 (Feature List 菜单) 见 vcxsrv-popup-pitfalls.md
