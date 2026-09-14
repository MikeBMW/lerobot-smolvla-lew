# feature.dbc 能力库 + 第三方模型导入 + YOLO 感知 (2026-08-19)

## 能力特征库架构 (v2.0, R MPV Z700 方案书驱动)

- 四层架构: L0 任务规划 → L1 技能编排(200项原子技能) → L2 模型决策(可替换)
  → L3 感知执行。文档: docs/model_capability_architecture.md
- **8 能力域 31 项**: A 移动流转 / B 感知认知 / C 作业执行 / D 决策引导 /
  E 数据学习 / F 部署运行 / G 对外协作 / H 工程交付。
  **能力视角** (能做什么), 禁技术词 (YOLO/ACT/MLP/状态空间方程), 程序校验零残留。
- 每条能力完整定义: id/name/desc/explain/iface/iface_def/io_in/io_out/scene/eng/app。
  用户铁律: "别只写关键词" — 解释说明=段落, 接口定义=用途+输入+输出+对接,
  输入输出=信号清单(带类型/说明)。

## feature.dbc (参考 Vector CANoe DBC)

- 文件: 仓库根 `feature.dbc` — **文件即配置事实**; 解析器 tools/gui/feature_dbc.py
  (export_dbc/parse_dbc/build_tree_from_dbc/export_excel/upload_excel)。
- 格式: `BU_: 模型节点` / `BO_ 能力: 接口 类别` / `SG_ 字段: 位宽 "内容"`
  (字段: 简述/解释/接口定义/输入/输出/场景/工程/归属) / `CM_ 节点: 能力ID...`。
- 10 接口: IN/OUT/CFG/GUIDE/MOD/TRAIN/DEPLOY/EVAL/MON/SCHED。
- 模型节点: JOB_MODEL(作业执行)/GUIDE_MODEL(预判引导)/SCHED_MODEL(作业编排)/
  PERCEPT_MODEL(感知)/THIRD_PARTY(第三方)。
- 数据字典树/Feature List 弹窗/Excel 导出 四端同源 (model_feature.py → dbc → 树)。

## 第三方模型导入保证链路 (tools/gui/model_importer.py)

标准格式 zmax-model-v1 (manifest.json: format/name/node/version/capabilities/
interfaces/weights; 规范: docs/third_party_model_spec.md)。
四步保证: ①校验(能力ID必须存在于能力库, 不达标拒绝) ②自动注册(feature.dbc
BU_+CM_) ③接口挂载(无 adapter 用默认观测→动作直通) ④冒烟验证(出动作才算,
失败自动回滚注册)。GUI: 数据字典面板「导入」按钮, 后台线程不卡 UI。

## Excel 导出 + 上传 (用户可下载)

- 容器无 /mnt/c 共享 → **导出自动上传 datadrive.world** (sshpass scp ECS +
  chmod 644), 返回下载 URL 显示在界面。
- **链接要可选中可点击**: QLabel 加 `setTextInteractionFlags(Qt.TextSelectableByMouse
  | Qt.TextBrowserInteraction)` + setOpenExternalLinks(True), 提示用 <a href>。
- **导出/导入必须后台线程** (sshpass scp 最长 60s 主线程 = 假死 "按钮没反应"),
  pyqtSignal 回主线程更新提示。

## YOLO 感知实装 (tools/gui/yolo_perception.py)

- 状态空间画布补全感知层: 🎯YOLO目标检测(B1)/📐2D→3D解算(B2)/🖐触觉感知(B3)/
  🔍外观质量检测(B5) — 数据层(metaworld)→感知层→43D 完整运行环境。
- 画布节点: 双击 YOLO → on_yolo_sense 实际加载 yolov8s.pt 跑检测→2D→3D→43D。
- 真机同构: 不依赖 metaworld/mujoco, 相机参数配置化。
- **ultralytics BGR 坑**: RGB 数组检测失败, 必须 cv2.cvtColor(RGB2BGR)。
- 环境: torch CPU 从 https://download.pytorch.org/whl/cpu 装;
  **torch 2.13 必须配 torchvision 0.28.0+cpu** (旧版 torchvision 报
  "operator torchvision::nms does not exist", 需 --reinstall 强制重装)。
- 数据层: flows/state_space_obs.json 加 ssbg_data 背景 + 📦metaworld 数据源
  (run_env: True) + 🔀训练/推理 (mode_switch, 双击切换) — 双击数据源按
  _current_mode() 运行真实模型 (train→on_train(policy=left_right) /
  infer→on_infer)。
