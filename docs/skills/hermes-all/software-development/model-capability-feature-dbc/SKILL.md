---
name: model-capability-feature-dbc
title: "Model Capability Feature Library & feature.dbc"
description: "Use when 模型能力清单/feature.dbc 设计 — capability-first, DBC 配置."
trigger: "User asks for 模型feature/特征清单/能力清单/feature list/能力库/feature.dbc — capability-oriented model description with interfaces and engineering mapping."
---

# Model Capability Feature Library & feature.dbc

User (老倪, Z-MAX) corrections distilled — 4 rounds of correction in one session (2026-08-19).

## 1. Capability-first definitions (user iron rule)
Define features as "what the model CAN DO", NOT how it works. Forbidden words in
feature definitions: algorithm names (YOLO/ACT/MLP/backbone), math (ẋ=Ax+Bu, Kp/Kd, PD),
pipeline jargon (CoT, behavior cloning, metaworld rollout, LeRobotDataset, safetensors,
39D/45D/58D). Rewrites that passed review:
- "YOLO 2D 检测" → 目标识别定位 (recognize parts/holes and give positions)
- "ẋ=Ax+Bu 状态空间方程" → 运动规律建模
- "Kp/Kd 增益调度" → 阶段力度调节
- "PD 前馈校正" → 精准到位
- "CoT 思维链" → 决策说明
- "metaworld rollout" → 上岗前考核 (sim evaluation before deployment)
- "safetensors 热更新" → 远程升级

## 2. Complete field spec, not keywords (user corrected twice: "别只写关键词啊")
Every capability MUST carry full definitions (program-verified length gates:
explain≥50 chars, iface_def≥40, io_in/io_out≥20, all fields non-empty):
- explain 解释说明 — paragraph: what it is / how it works / what problem it solves
- iface_def 接口定义 — interface purpose + inputs + outputs + integration contract
- io_in / io_out 输入输出信号 — signal list with types and descriptions
- scene 使用场景 / eng 工程落点 / app 归属
Tree/table shows all fields; short keyword cells get rejected by user.

## 3. Model naming: 类别（例具体模型）
Never write concrete model names in the feature list. Format: 感知（例YOLO）/
端到端动作（例ACT）/ 世界模型（例LEW）/ 状态空间（例状态空间模型）/
触觉力控（例VLA-Touch）/ 轻量决策（例MLP）/ 全模型通用.

## 4. Model = capability combination (Manifest)
Every model has capabilities; a model is a selected subset of the library.
Tree marks ✓ selected / ○ not; current model auto-detected from canvas context.

## 5. feature.dbc — capability database file (Vector CANoe DBC pattern)
One standardized file configures different models in the same platform/container.
DBC analogy: BU_=model nodes (ECUs), BO_=capability (messages), SG_=signals,
CM_=node→capability mapping. Third-party model onboarding: add BU_ node → declare
CM_ capabilities → implement SG_ signal contract → same pipeline runs, zero platform code.
Format and implementation details: see zmax-console skill references/
feature-registry-dbc-2026-08-19.md (co-located in the Z-MAX GUI repo).

## 7. v4.0 大小脑×原型对照 (2026-08-19 老倪, 现行版)
- 老倪原型前「大小脑」清单 (VIS/TAC/LAN/FUS/DEC/CTR/SYS 30项) 为骨架, 对照工程原型逐项增补更新:
  65 能力 = 更新30 + 增补35 (✅实装51 / 🛠部分11 / 🔲待建3)。
- **7 域结构**: P 感知(10)=多模态 / F 融合(5) / S 策略(17)=决策规划 / E 控制执行(7)=控制 /
  X 安全边界(10) / M 平台执行(4) / K 支撑(12)。能力 ID 沿用老倪编号 (VIS-01/DEC_01→DEC-01/SYS-01)。
- 每条能力带 **status** 字段 (✅实装/🛠部分/🔲待建), 对照原型依据写进 explain。
- **关键修正** (原型前→后): DEC_04 避障定义矛盾修正; DEC_09 运动学逆解归位控制域(CTR-05);
  VIS-05 显微/VIS-06 进出料口/SYS-08 静态安全 = 🔲待建; 控制层独立成 E 域。
- 六层源码映射: perception→P, dynamics+parallel(右脑)+cognition(校正)→F, parallel(左脑)+cognition(调度)→S,
  execution+夹爪→E, safety→X。8状态机(APPROACH..DONE)=DEC-01 原型; 前馈加速器=DEC-13; 7轴stab=X3。

## 8. v3.0 双视图架构 (2026-08-19, 已被 v4 取代, 保留参考)
- **四层架构**: P 感知层(采集+初级理解) / F 融合层(统一状态+时序估计) / S 策略层(决策+编排+动作) /
  X 安全边界层(保护+限幅+稳定+联锁), 外加 M 平台执行域(移动承载) + K 支撑能力域(数据/运行/协同/工程)。
  对应六层源码: perception→P, dynamics/parallel(右脑)/cognition(校正)→F, parallel(左脑)/cognition(调度)→S, safety→X。
- **双视图**: Query 需求角度(场景→需求点, 如插拔电口/插拔光纤/固件刷写/AOI检测/老化箱/ATS测试) /
  Key 实现角度(层→能力→当前模块)。追溯链: 需求点 → (层·能力ID) → 模块。
- **SCENES 结构** (model_feature.py): {sid, name, requirements:[{rid, desc, layer, capability, module}]},
  layer 用 "P/S" 多值; 自检: 需求点引用的能力ID必须存在 + layer 标注必须包含能力实际归属层。
- **落地文件**: docs/feature_list_v3_architecture.md (设计稿) / model_feature.py (45能力+8场景+46需求点+5模型)
  / feature.dbc (v3.0, FLOW_ 改四层)。export_dbc 完全兼容 (cat 首词即层标记 P/F/S/X/M/K)。
- **质量门槛实测**: explain≥50 / iface_def≥40 / io_in·io_out 各≥20 (中文字符 len) — 新写能力必须过线,
  io 用 "信号名 (类型, 说明)；信号名 (类型, 说明)" 清单格式最容易过线。
- 重启 GUI 后数据字典树按新四层显示; 场景视图树 (Query) 为下一步迭代。

## 8. Pitfalls (全部实测 2026-08-19)
- Python `%` formatting on HTML with CSS `width:100%` / data `≥99%` → "not enough
  arguments for format string". Use .replace() placeholder chain, not % format.
- Tree builder helpers must be single-arg `make_item(texts)` + parent.addChild(item);
  two-arg calls silently TypeError inside try/except → whole subtree missing with no error.
- try/except swallowing GUI build errors = feature silently disappears; log exceptions.
- Never run long subprocess (sshpass scp, any network) on GUI main thread — button
  freezes 60s (gdb: selectors.py select). Use threading.Thread + pyqtSignal to update UI.
- Container without /mnt/c: exported files are invisible to user on Windows — upload
  to their website (datadrive.world) and show the URL.
- QTimer.singleShot callbacks touching a possibly-closed QDialog: guard with
  `from PyQt5 import sip; if sip.isdeleted(dlg): return` (Segfault prevention).
- VcXsrv multiple always-on-top windows: z-order unstable, video window covers new
  dialog (user reports "Feature List opened the video"). Fix: delayed double raise_
  after show (60/250ms) + lower other always-on-top windows before showing.
