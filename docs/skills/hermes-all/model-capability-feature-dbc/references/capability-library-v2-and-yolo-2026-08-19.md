# 能力库 v2 + 实际 YOLO 感知 (2026-08-19)

> SKILL.md 主体更新受阻时的完整备份。未来 agent 合并进 SKILL.md 5b/5c/5d 节。

## 能力库 v2 — R MPV Z700 方案书驱动

四层架构: L0 任务规划(多车调度) → L1 技能编排(阶段/200原子技能) →
L2 模型决策(可替换) → L3 感知执行. 文档: docs/model_capability_architecture.md

8 大能力域 31 项 (能力视角, 程序校验零技术词):
- A 移动流转 (移动即工位): 自主导航流转/工位精准对接/举升高度调节(0~800mm)/双形态作业
- B 感知认知: 目标识别定位/空间位姿感知/触感感知/自身状态感知/外观质量检测(AOI)
- C 作业执行: 完整作业/精细对位(±0.02mm)/力控插拔保护(≤2N)/灵活翻转取放/双臂协同/宏微复合
- D 决策引导: 过程预判/运动规律建模/决策说明
- E 数据学习: 车载数据采集(数据飞轮)/边学边练/上岗考核
- F 部署运行: 本地实时(70ms)/远程升级/多车协同调度
- G 对外协作: 标准模型接入/运行状态上报/事件通知/产线系统对接(PLC/MES)
- H 工程交付: 现场参数可调/方案文档交付/远程查看

模型节点 (L2, 非技术表达): JOB_MODEL 作业执行模型(26项) / GUIDE_MODEL 预判引导 /
SCHED_MODEL 作业编排 / PERCEPT_MODEL 感知(B1 B2 B4 B5 G1) / THIRD_PARTY 第三方(空)
新接口: GUIDE 引导输出(下一状态/接触概率) + MOD 阶段调制 → 共 10 接口
数据字典树根节点: "🧩 能力数据库 feature.dbc · 精细操作"

feature.dbc 生成: feature_dbc.py write_dbc(FEATURE_LIBRARY, MODEL_MANIFESTS,
DATAFLOW_STAGES, INTERFACE_DEFS); 树构建 feature_dbc.build_tree_from_dbc()
Excel 导出: export_excel() 3 sheets; 上传: upload_excel() → datadrive.world
BO_ 块 8 个 SG_ 行: 简述/解释/接口定义/输入/输出/场景/工程/归属 (全部字段入库)

## 实际 YOLO 感知 (yolo_perception.py)

- 位置: tools/gui/yolo_perception.py; 画布节点双击接线: NODE_RUN_ACTIONS
  加 ("YOLO", "on_yolo_sense") → _start_worker 后台加载
- 类: YoloPerception — _load(实际 YOLO 加载) / detect(B1 2D框) / to_3d(B2 反投影,
  平面假设+标定修正) / align_obs(→43D = 39D + 触觉4D) / smoke
- 39D 段结构: [0:3]=hand, [18:21]=peg, [36:39]=hole (与 yolo_state_aligner 一致)
- 真机同构原则: 不依赖 metaworld/mujoco, 相机参数配置化
- 环境: gui-venv311 装 torch(CUDA CPU 源) + ultralytics(阿里云); torchvision 版本
  必须匹配 torch (uv 不自动重装 → --reinstall 指定源)
- 演示: reports/_yolo_demo.jpg (真实照片, COCO 检测 bus/person 实测 conf 0.92/0.61)

## 新增 Pitfalls (2026-08-19)

- CM_ 解析: `CM_ NODE: ids...` 用 regex `CM_\s+(\S+):\s*(.*)`, 不是 "CM_:" 前缀
- QLabel 链接/结果提示默认不可选不可点 → setTextInteractionFlags(
  Qt.TextSelectableByMouse | Qt.TextBrowserInteraction) + openExternalLinks,
  URL 用 <a href> 蓝色渲染
- 导出/导入按钮: sshpass scp 60s 超时必须后台线程 + pyqtSignal 回主线程
  (ModelTreeDock.export_done = pyqtSignal(str); 完成后 refresh 树)
- torchvision 与 torch 版本不匹配: RuntimeError "operator torchvision::nms does not
  exist" → --reinstall torchvision --index-url https://download.pytorch.org/whl/cpu
