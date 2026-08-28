# Feature List / 能力特征库 设计铁律 (2026-08-19 老倪多轮纠正沉淀)

## 老倪铁律 (特征清单/能力库文档, 违反必被纠正)

1. **能力视角, 不写算法技术** — feature 从「模型能做什么」定义。全禁词:
   YOLO / ẋ=Ax+Bu / Kp / Kd / PD / CoT / 行为克隆 / 扩散 / backbone / 冻结 / 微调 /
   safetensors / LeRobotDataset / metaworld / rollout / 39D/45D/58D / 状态空间方程 等。
   "YOLO 2D 检测" → "目标识别定位"; "ẋ=Ax+Bu" → "运动规律建模"; "增益调度" → "阶段力度调节"。
2. **模型名抽象格式** — 适用字段用「类别(例具体模型)」:
   感知(例YOLO) / 端到端动作(例ACT) / 世界模型(例LEW) / 触觉力控(例VLA-Touch) /
   状态空间(例状态空间模型) / 轻量决策(例MLP) / 全模型通用。manifest 当前模型显示同理。
3. **完整定义, 别只写关键词** (用户原话"别只写关键词啊") — 每条能力含:
   - explain 解释说明: 完整段落 (是什么/怎么工作/解决什么问题)
   - iface_def 接口定义: 用途/输入/输出/对接方式 (完整定义, 非"对应IN"标签)
   - io_in / io_out 输入输出信号: 清单含类型与说明 (如 "现场图像 (RGB 640×480, 约30fps)")
   - scene 场景 + eng 工程落点 + app 归属
   程序校验: explain≥50字, iface_def≥40, io≥20, 否则算关键词级要补。
4. **系统工程模块化** — 特征库 8 大类 (感知/决策/控制/数据/学习训练/部署运行/对外协作/工程交付),
   可复用/可增加/可组合; 模型 = 能力组合 (Manifest); 状态空间只是数据流形态之一
   (感知→决策→控制→执行)。
5. **参考生态标准** — LeRobot: PretrainedPolicy 注册机制 / 标准数据集格式 / ProcessorStep 管道。

## feature.dbc 方案 (参考 Vector CANoe DBC, 2026-08-19)

- **动机**: CANoe 用 DBC 让多个 ECU 共享同一套信号定义; 同构问题 = 多个模型在同一个
  平台/容器内配置接入 → 用 feature.dbc 能力数据库文件。
- **格式**: `BU_` 模型节点 / `FLOW_` 数据流形态 / `BO_ 能力: 接口 类别` / `SG_ 信号 : 位宽 "说明"`
  (输入/输出/解释/接口定义/场景/工程/归属 均为 SG_ 行) / `CM_ 节点: 能力ID...` / `//` 注释。
- **第三方接入三步**: ① BU_ 加节点 ② CM_ 声明能力组合 ③ 按 SG_ 信号契约实现适配
  → 同流程进训练/评估/部署/监控, 平台零改码。
- **文件即配置事实**: 数据字典树从 feature.dbc 解析构建 (model_tree.py refresh),
  缺失时自动从能力库生成; export_dbc/parse_dbc/build_tree_from_dbc 双向。
- 工程落点: `tools/gui/model_feature.py` (能力库+Manifest) / `tools/gui/feature_dbc.py`
  (解析器) / `feature.dbc` (仓库根) / `docs/feature_dbc_spec.md` (方案文档)。

## VcXsrv 弹窗实战坑 (Feature List 弹窗, 2026-08-19)

- **置顶视频窗口遮挡新弹窗** (用户报"打开的是视频"): 操作视频窗口 WindowStaysOnTopHint
  在 VcXsrv 下 z-order 不稳 → 新弹窗 show 后延迟双 raise (QTimer 60/250ms)。
- **滚动只更新窄条** (用户报"右侧不动"): XCopyArea 半移 bug → QTextBrowser 子类重写
  scrollContentsBy: super() 后 viewport().update() 强制全量重绘。
- **视频像素残留污染新窗口** (用户报"左侧是操作视频遗留"): 播放窗口频繁刷 X 层,
  关闭后残留 → 弹窗 show 后延迟多次 repaint (100/400/800/1500ms) + 弹出前把
  操作视频窗口降置顶 (setWindowFlags 清 hint + lower())。
- **防 Segfault**: QTimer.singleShot 延迟回调访问可能已 deleteLater 的 dialog →
  回调内先 `sip.isdeleted(dlg)` 检查再访问。崩溃特征日志:
  "QObject::killTimer: Timers cannot be stopped from another thread" + Segmentation fault。
- 诊断工具: xwd (x11-apps) 截图 + ffmpeg 转 png + tesseract OCR 验证窗口实际渲染内容
  (不依赖"能不能看见")。
