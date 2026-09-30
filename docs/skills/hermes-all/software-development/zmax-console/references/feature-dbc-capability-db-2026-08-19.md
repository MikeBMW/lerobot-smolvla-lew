# 能力特征库 + feature.dbc + 第三方导入 (2026-08-19)

## 架构
```
model_feature.py (能力库 v2: 8 域 31 能力, 零技术词)
   │ export_dbc() / 画布 JSON 同源
   ▼
feature.dbc (CANoe DBC 式能力数据库, 仓库根, **文件即配置事实**)
   │ parse → build_tree_from_dbc() → 数据字典树 / Feature List 弹窗 / Excel
   ▼
model_importer.py (第三方 zmax-model-v1 导入: 校验→注册→适配→冒烟)
```
四层架构 (对齐 Z700 方案书): L0 任务规划 / L1 技能编排 / L2 模型决策(可替换) /
L3 感知执行。能力域: A 移动流转 / B 感知认知 / C 作业执行 / D 决策引导 /
E 数据学习 / F 部署运行 / G 对外协作 / H 工程交付。
接口 10 个: IN/OUT/CFG/GUIDE(引导输出)/MOD(阶段调制)/TRAIN/DEPLOY/EVAL/MON/SCHED。

## feature.dbc 格式 (DBC 风格)
```
BU_: STATE_SPACE ACT SMOLVLA VLA_TOUCH YOLO        // 模型节点
FLOW_: L0 任务规划 "多机台·多车协同调度 · 场景编排"  // 数据流形态
BO_ B1 目标识别定位: IN B                           // 能力=消息
 SG_ 解释 : 512 "..."                              // 完整定义非关键词
 SG_ 接口定义 : 512 "..."
 SG_ 输入 : 24 "...";  SG_ 输出 : 64 "..."
 SG_ 场景/工程/归属 : ...
CM_ JOB_MODEL: A1 B1 C1 ...                        // 模型能力组合
```
解析注意: CM_ 行是 `CM_ 节点名:` (有空格), 正则 `CM_\s+(\S+):\s*(.*)`。

## 第三方模型导入 (model_importer.py, 四条硬保证)
1. **校验拒绝**: manifest.json schema (format=zmax-model-v1, name/node/version/
   capabilities/interfaces/weights 必填) + **能力 ID 必须在能力库** + 权重存在
2. **自动注册**: 校验过 → 自动写 feature.dbc (BU_ 加节点 + CM_ 加组合)
3. **适配兜底**: adapter.py 可选; 缺省用平台默认适配器 (观测→动作直通)
4. **冒烟回滚**: 自动跑一次推理出动作才算成功, 失败 unregister_model 回滚
GUI 入口: 数据字典面板「导入」按钮 (QFileDialog 选 zip → 后台线程 + 信号)。

## 权重格式评估结论
- 平台内模型: **safetensors** (延续 Orin 热更新链路, 安全标准)
- 第三方导入: **ONNX 优先** (格式中立+无 pickle RCE+Orin TensorRT 路径),
  .pth state_dict 仅兜底且必须 `torch.load(weights_only=True)`
- .pth 是 pickle → 反序列化任意代码执行风险, 第三方不可信包致命

## Excel 导出 + 上传
- `export_excel()`: openpyxl 3 sheets (能力库 27-31×11 / 模型组合 / 接口说明)
- `upload_excel()`: sshpass scp → datadrive.world + chmod 644 → 返回下载 URL
  (容器无 /mnt/c, 用户只能从网站下载)
- **按钮假死坑**: sshpass scp 主线程跑卡 60s → 必须 threading.Thread +
  pyqtSignal 回主线程更新 label
- **QLabel 链接可选中/可点**: setTextInteractionFlags(TextSelectableByMouse |
  TextBrowserInteraction) + setOpenExternalLinks(True) + HTML `<a href>`

## YOLO 感知实装 (状态空间补全)
- `tools/gui/yolo_perception.py`: B1 识别 (YOLO 检测, **ultralytics 用 BGR** —
  RGB 数组检测失败) / B2 位姿 (2D 框→相机反投影 3D) / 状态对齐 43D
- 环境: gui-venv311 装 torch CPU (pytorch.org cpu 源) + ultralytics (阿里云);
  **torch 2.13 必须配 torchvision 0.28+cpu, uv 需 --reinstall 才重装**
- 双击画布「🎯 YOLO 目标检测」→ NODE_RUN_ACTIONS 匹配 "YOLO" → on_yolo_sense
  (_start_worker 后台, 实际加载 yolov8s.pt 跑检测→3D→43D 日志输出)

## 画布扩展模式 (状态空间 flows/state_space_obs.json 同源)
- 加背景分区: row_bg 节点 (x=-20, w=1480, 同款 #1f2937) + 节点整齐等间距摆放
- 加端口: 节点 inputs 字符串列表加 "in2"/"in3" (扩展不改现有链路)
- 模式开关: type=mode_switch, params.mode="train"/"infer", 双击 _toggle_mode,
  `_current_mode()` 读取; paint 里加 mode_switch 绘制分支
- 运行分发: 数据源节点 params.run_env → on_node_activated 里 **run_env 优先于
  source 分支** → on_run_env 按 _current_mode() 分发 on_train(policy=left_right)/
  on_infer
- **双参 make_item 坑**: build_tree_from_dbc 的 make_item 回调必须单参
  (lambda texts: QTreeWidgetItem(texts)) + 调用处 addChild; 测试必须用与
  model_tree.py 相同的单参 lambda 形式 (传 QTreeWidgetItem 类会掩盖 TypeError)
- 被 except 吞掉的构建异常 = 整棵树不显示 ("feature list 不见了" 类问题:
  先查树构建回调签名)

## HTML % 格式化坑
产品文档模板里 CSS `width:100%` 撞 `%` 格式化 → TypeError:
not enough arguments。用 **replace 链** 替代 % 格式化 (占位符 %(xxx)s +
`.replace` 逐个替换), 内容里的裸 % 不转义也安全。
