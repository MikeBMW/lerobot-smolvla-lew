# 🧩 能力特征库 Feature Registry — 设计规范 (2026-08-19 老倪确立)

GUI: tools/gui/model_feature.py → 数据字典树顶部「🧩 能力特征库」节点。

## 用户确立的铁律 (多次纠正, 已定稿)

1. **能力视角定义** — feature 从「模型能做什么」写, 禁止算法/技术词。
   定义字段 (name/desc/explain/io/scene) 程序扫描零残留的技术词:
   YOLO/ẋ/Ax+Bu/Kp/Kd/PD/CoT/行为克隆/扩散/backbone/冻结/微调/safetensors/
   LeRobot/metaworld/rollout/Transformer/token/GRU/latent/39D/45D/58D/HTTP/JSON…
   - ❌ "YOLO 2D 检测" → ✅ "目标识别定位"
   - ❌ "ẋ=Ax+Bu 状态空间" → ✅ "运动规律建模"
   - ❌ "Kp/Kd 增益调度" → ✅ "阶段力度调节"
   - ❌ "PD 前馈校正" → ✅ "精准到位"
   - ❌ "CoT 思维链" → ✅ "决策说明"
   - ❌ "LeRobotDataset" → ✅ "标准数据采集"
   - ❌ "metaworld rollout" → ✅ "上岗前考核"
2. **适用模型用「类别(例具体模型)」格式** — 不直接列模型名:
   `感知（例YOLO）` / `端到端动作（例ACT）` / `世界模型（例LEW）` /
   `状态空间（例状态空间模型）` / `触觉力控（例VLA-Touch）` / `轻量决策（例MLP）` /
   `全模型通用` / `产线部署版` / `交付`
3. **状态空间只是数据流形态之一** — 作业数据流: 感知→决策→控制→执行;
   形态: 状态向量流 / 图像→动作流 / 视频预测流 / 感知专用流。
   不要在设计中把状态空间当唯一形式。
4. **每条能力四要素**: explain(能力解释) / io(输入输出信号 IN→OUT 通俗化) /
   scene(使用场景) / iface(接口 IN/OUT/CFG/TRAIN/DEPLOY/EVAL/MON/SCHED)。
   树子节点: 能力/信号/接口/场景/工程/归属 六行。
5. **模型 = 能力 Manifest (组合)** — MODEL_MANIFESTS 里每个模型一个特征 ID 集合;
   第三方模型: 注册 Manifest + 补齐缺失能力 → 同流程运行。
   复用/增加/组合: 能力独立定义多模型共用; 新能力注册新条目; 按需勾选组合。
6. **工程映射字段 (eng) 保留内部落点** — 工程师定位用, 可含目录/工具名。

## 特征库结构 (8 大类 27 条)

A 感知能力: A1目标识别定位 A2空间位姿感知 A3触感感知 A4自身状态感知
B 决策能力: B1完整作业执行 B2过程预判 B3运动规律建模 B4精准到位 B5决策说明
C 作业控制能力: C1分步作业编排 C2阶段力度调节 C3作业保护 C4平稳运行
D 数据能力: D1标准数据采集 D2边学边练 D3作业追溯
E 学习训练能力: E1一键训练 E2上岗前考核 E3渐进式上岗
F 部署运行能力: F1本地实时作业 F2远程升级
G 对外协作能力: G1标准模型接入 G2运行状态上报 G3事件自动通知
H 工程交付能力: H1现场参数可调 H2方案文档交付 H3远程查看

Manifest: state_space(21项) / act(19) / smolvla(20) / vla_touch(21) / yolo(3)。

## 验证方法

- offscreen 构建树 + 技术词正则扫描定义字段 (见会话 2026-08-19)
- current_model_key(module): state_space 画布→state_space; 否则 cmb_model.currentText() 模糊匹配
- 无匹配模型时仍显示特征库总览 (不显示组合)
