---
name: zmax-left-right-policy
description: Use when 训练/评估/部署 left_right 双脑策略 (左脑MLP+右脑WM+8状态机), 指标上报大屏。
---

# Z-MAX left_right 双脑策略 (2026-08-10 v2.0.0)

## 触发条件
- left_right / 双脑 / 状态机插拔训练评估
- P3 指标上报 / 大屏监督 / robot-action

## 核心文件
- `tools/train_full_pipeline.py` — 训练+评估 (collect_data → 左脑+右脑 → 8 seed 评估)
- `src/lerobot/policies/left_right/` — lerobot 标准 policy (configuration/modeling/processor)
- `tools/p3_metrics_bridge.py` — 指标上报 bridge (metrics → HTTP API)
- `tools/eval_left_right_policy.py` / `tools/eval_std_left_right.py` — 评估脚本
- `docs/left_right_policy.md` — 技术方案 (39D 结构 + 状态机调制表)
- `docs/factory_fine_ops_supervision.md` — 大屏监督方案 (8状态×指标)

## 架构 (必记)
- 左脑 LeftBrainMLP: 39D→4D 动作 (MLP 偏置接近: act=act×0.3+clip(delta×2))
- 右脑 RightBrainWM: obs+act→next+contact (contact 只给状态机, 不给左脑)
- 状态机 8 状态: APPROACH=0/ALIGN=1/DESCEND=2/GRASP=3/LIFT=4/TRANSFER=5/INSERT=6/DONE=7
- 39D obs: [0:3]hand [3]gripper [4:7]peg [7:11]peg_quat [18:21]prev_hand (与[0:3]重复!) [36:39]hole
- **39D obs 无真实 peg 段** → 评估/推理必须 set_env(env) 用 env.data.site_xpos 真值

## 架构术语辨析 (Model Zoo 配置表, 2026-08-25)
- **三层划分**: ①模型层(可学习: 状态编码39D→512/左脑MLP/右脑WM/VLM层/CNN层/Expert层) ②决策编排层(规则非参数: 动作调制) ③系统安全层(硬件约束: 安全限值)。只有①是"层"。
- **模型宽度 = 向量宽度**(隐藏层维度), 非模型规模。YOLO 无此概念→"—"(曾误填 yolov8s)。
- **状态空间(State Space, 控制论) ≠ 状态空间模型(SSM=Mamba/S4)**。Z-MAX 用前者。
- **39D state = 状态观测**(输入特征向量), 处理它的层叫**状态编码器** 39D→512。
- **动作调制 = 决策编排模块**(非层): `_act_state_machine` 8阶段门控, u=g(stage)·(w_ff·u_ff+(1−w_ff)·u_fb), 无参数梯度不流经。理论=Brooks包容架构+残差策略。专业名 Action Modulator/行为仲裁。
- **安全限值 = 安全护盾**(Safety Shield/CBF, 系统级): safety.py saturate + sys0_safety.py L1-L4。独立于模型, 所有路线共有, 不入模型架构表。
- 配置表 ZOO_SPEC 栏位: 🏗架构(架构/VLM层/CNN层/状态编码/动作调制/Expert层/模型宽度/世界模型) + 🛡安全(安全机制/动作限幅/力限值/否决重试)。详见 docs/model_zoo_architecture.md。
- **三层安全对比**: 状态空间唯一三层(内置否决 veto_th=2.0 + saturate限幅 clip(±0.6~±1) + Sys0外部壳); VLA/ACT/MLP蒸馏仅Sys0外挂; 官方专家力控闭环有界; YOLO不输出动作无安全需求。

## 训练 (train_full_pipeline.py)
```bash
DISPLAY=:0 MUJOCO_GL=glfw .venv/bin/python -u tools/train_full_pipeline.py
```
- collect_data(n_eps=120, aug=True): 种子 0-499 随机 (数据增强降波动)
- 训练后自动 8 seed 评估: 抓起 6-8/8, 插入 4-6/8
- 权重: outputs/rl_peg/full_pipeline.pt (left/right/xm/xs/ym/ys)

## 关键参数 (复现)
- seed 42 + 800 epoch; 夹持 act[3]=0.6 (grab_effort 正=夹持, 负=张开)
- 锁定条件 contact>0.5 && d_hp<0.06; 抬起 peg_z > peg_z0+0.08 (抬8cm避台面)
- 转移速度自适应: >0.2m→0.6, >0.05m→0.35, 否则 0.15

## 评估铁律 (血泪)
- **metaworld reset(seed) 后仍有物理随机** → 8 seed 单次结果波动大 (插入 4-6/8)
- **必须多 seed 重复评估取波动范围** (同权重跑 3 次: 5/8,4/8,6/8 正常)
- 7/8 vs 4/8 差异 = 随机波动非代码差异 (已逐帧+3次重复验证)
- 插入 4-6/8 vs 手写 7/8 同分布; 转移卡顿=物理碰撞非控制参数

## P3 指标上报 (大屏监督)
- select_action 内 `_measure_metrics`: 8 阶段量测 → self.metrics (实时) + self.action_log (留痕)
- bridge: `python tools/p3_metrics_bridge.py --local` (回环) / `--api URL` (上报)
- payload: {robot, zone, stage, stageIdx, metrics[], pass, ts}
- 指标: APPROACH收敛距离/GRASP接触/夹持/LIFT抬升/TRANSFER到位偏差/INSERT插入距离力

## 坑 (已踩)
- **np.float32/np.bool_ 不可 JSON 序列化** → metrics 全部 float(round())/bool() 包裹 (踩 3 轮: float32→np.bool_→GRASP分支漏包)
- metrics 的 pass 必须 bool(all(...)) (all 遇 np.bool_ 返回 np.bool_)
- actionLog 记录旧阶段指标 (转移前最后 metrics), 用 _prev_metrics
- **脚本重训覆盖好模型** → 好结果立即留存
- 跨天 WSL 重启容器训练卡死 → 输出目录时间戳

## lerobot 标准集成
- factory 注册: `_get_policy_cls_from_policy_name('left_right')` ✅
- processor: PolicyProcessorPipeline + Normalizer/Unnormalizer (同 act 结构)
- lerobot_train: configs/policies/config_left_right.yaml (39D peg_long 数据, 3000步)
- get_optimizer_preset 返回 AdamWConfig 类 (非 dict); get_optim_params 返回参数组列表
- forward 返回 (loss, output_dict) 元组 (lerobot_train 期望)
- save_pretrained: PolicyFeature → dict (JSON 序列化)
