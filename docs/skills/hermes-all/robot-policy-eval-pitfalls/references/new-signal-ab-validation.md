# 新控制信号接入的 A/B 与 load-bearing 检验 (2026-09-11, L4 夹爪 yaw 指令源实测)

场景: 老倪问「某条指令是谁发的? 是模型/流形预测节点么?」→ 紧接着要求「让 X 真正发指令 + A/B 实证 + 视频」。
本测最终是**负结果**(不声明增益), 但流程与判据可直接复用。

## 1. 先静态定位现有指令源 (回答"是谁发的"必须给 file:line)
- grep 该物理量的**唯一写入点**。本测 `_grip_yaw` / `mocap_quat` 全仓库只出现在 `tools/gen_l4_demo_video.py`
  (`ramp_yaw()` 写 `env._grip_yaw`; `make_env` 打补丁在每次 `set_xyz_action` 后写 `env.data.mocap_quat[0]`)。
  ⇒ 结论: 是 L4Demo **脚本阶段逻辑**发的开环固定角, 不是模型、不是流形预测器。
- 同时说清该自由度在**别的链路是否存在**: metaworld 原生动作空间是 4D(x,y,z,gripper), **没有 yaw 自由度**;
  只有自定义 XML + mocap 补丁才有 ⇒ 引擎链路里"夹爪旋转指令"根本不存在。
- 顺带核实决策源侧的真实状态: 本测 L4Demo 里 `mani_pred` 原为 `np.zeros(6)` **0 占位**, 演示链不 import 任何 manifold/torch;
  引擎链路里 `mani_pred` 只是**旁路列**(`tr["mani_pred"]`), 动作合成只有 `u_sat = safety.saturate(u_ff+u_fb)` ⇒ 预测器无控制权。

## 2. 接线成独立执行器 (断点可进, 自证调用量)
- 单独文件 (`src/lerobot/manifold/yaw_actuator.py`): 每帧真调 `WorldModelPredictor(z7+a4 → z' → 流形 6 维)`,
  候选偏航角 (φ_ref±span, step) 逐一代价打分取最小 → 下发; slew 限幅 0.03 rad/步 (与基线同速才可比)。
- 记录取证字段: `n_calls` (前向次数, 本测 182/轮 = 26 决策 × 7 候选) / `n_decide` / 候选打分表 / `trained` / 权重文件名。
- **候选→物理量的编码若是工程假设必须标注**: 本测 = "残余失配 δφ=(来料朝向−φ) 绕z旋转相对几何"。
- **权重/trained 如实标注**: 权重缺失 → 随机对照, 绝不冒称已训练 (本测权重 `models/l4_mani_predictor_v5.pt`, trained=True)。

## 3. A/B 同口径
同链路 / 同 seed 集合 / 同重复数 / 同 slew 速率; 指标 = success / steps / 关键几何量 (插入/拔出 mm) / AOI / η / 耗时 + 决策取证。
本测 (`tools/ab_mani_yaw.py`, 3 seed × 2 重复, 12 轮 ≈ 36s): 两臂 **6/6 全成功**,
Arm A yaw=+89.4°(固定) vs Arm B yaw=-44.7°(预测器决策), 插入 49.1 vs 49.4mm, η 全 1.0 → **差异只在 yaw 指令本身**。

## 4. 先判 gating (决定结论的那一步)
问「这个信号在这条链路里 **load-bearing** 吗?」证据 = 用一个明显错的值能否照样成功。
本测 Arm B 用 -44.7°(相对"正确"的 +90° 偏 45°)仍全链 success ⇒ ② 段**不 load-bearing**
(③ 治具回正把模块转回 0° + 刚性锁掩蔽了抓取姿态) ⇒ 该位置的任何 A/B 都不会有差异, **不许声称增益**。
要测就换到 load-bearing 的位置: ④ 标准抓取的**试抓搜索** (试抬成功/失败是真判据) 或插入相位。

## 5. 判决策源是否有信息量 (候选代价表的形状)
打印候选代价表, 看形状:
- 本测实测 **单调** (+45.3°→-44.7°: 0.168→0.0955 单调降) ⇒ argmin 恒落候选区间**边界** ⇒ 选择无对准信息。
- 根因: 待决策的量**不在决策源输入维里** (act_dim=4, 无 yaw), 训练分布也没覆盖 yaw 变化 ⇒ 超纲,
  不是调权重/调 span 能救; 需要 (a) yaw 进输入维或单训 yaw-conditioned 打分头 (b) 换到 load-bearing 位置用真实成败监督。

## 6. 收口 (零回退 + 诚实归档)
默认档保持原路径 (**一行默认行为不动**), 新路径只做开关 (`--mani-yaw` / `SS_MANI_YAW_*`);
VERSION.md 写清"负结果 + 根因 + 下一步"; 两臂各出一条**同链路同视角**视频供对照 (差异只应在被测那一步)。

## 7. 证据一致性自检 (假证据零容忍)
接线时顺手 grep 被测阶段里"写死但实际会变"的日志/历史串: 本测 ② 段硬编码 `夹爪 yaw=90°`,
A/B 下实际 -44.7° ⇒ **假证据**。修复 = 打印实际下发角 + 臂别 (`[Arm A 脚本开环]` / `[Arm B 流形预测器决策]`)。
同理: 报"预测器发指令"要看 `n_calls` 与权重文件名, 不看代码里"接了"的注释。

## 可复用工件
- `tools/ab_mani_yaw.py` — 同口径 A/B 跑分 + JSON 落盘 + 汇总表
- `src/lerobot/manifold/yaw_actuator.py` — 候选打分型执行器模板 (含候选代价表取证)
- 视频/数据交付: `reports/ab_mani_yaw_<ts>.json` + 两臂 mp4 (datadrive.world/l4_armA_scripted.mp4 · l4_armB_mani_yaw.mp4)
