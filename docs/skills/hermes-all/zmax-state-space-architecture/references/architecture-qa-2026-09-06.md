# 状态空间架构答疑定稿 (2026-09-06 老倪三连问)

老倪在 VSCode 逐文件追问架构本质，以下为定稿答案（代码实锤 + 诚实边界）。

## 1. 右脑对应哪个节点? est vs dyn 角色映射
- 画布两节点分工 (引擎主循环逐行): 「🔮 自适应状态估计器」ss_est → AdaptiveStateEstimator:
  est.predict(latent,act) 外推 4D 潜状态 + est.update 卡尔曼后验 (维护潜状态, 去向=潜空间/
  流形可视化); 「📈 先验动力学预测器」dyn → PriorDynamicsPredictor: prior →
  state_correction(prior, z_k) 出**残差基准** (残差→u_fb 反馈 + 接触概率)。
- 训练右脑 RightBrainWM = 前向世界模型 (obs+act → next_obs + contact, 无递归) →
  对应"预测 next 给残差基准" = **dyn 的角色**。接入点 = dyn.contact_of 融合 +
  predict obs= 位置先验待命。est (卡尔曼) = 教学解析件 (A/K/B 标定), 训练侧
  LeftRightPolicy 无对应网络 (只有 LeftBrainMLP + RightBrainWM), 无权重可接。
- "est = 原右脑 GRU" (parallel.py 头注释) = **历史设计叙事**: 早期设想右脑=递归 GRU
  潜状态估计器; 2026-08-10 实现成前馈 WM 后注释没更新。判别法: 看训练模型实际 forward
  语义定角色, 别被注释带偏。

## 2. 任务空间 vs 关节空间建模 ("7轴动力学"追问)
- metaworld 实测: sawyer = right_j0~j6 **7 旋转关节** + 夹爪 2 指 (r/l_close);
  mujoco nu=2 (仅夹爪执行器, 臂由 metaworld 内部反解控制器驱动); **act = (4,)
  末端增量 dx dy dz + gripper**; obs 39D **无关节角 q**。
- 建模对象 = 任务空间"三刚体相对几何": hand(obs[0:3]) + peg + hole 笛卡尔关系;
  obs39 = cur18+prev18+target3; latent 4D = 位置3+接触力。u = 末端速度指令;
  dyn B=0.02 = 整条 7 轴伺服链压成的响应增益 (执行器模型, 同真机珞石臂 Cartesian
  SDK 控制)。关节动力学 (14D+7τ) 被 env.step 内部伺服/臂内控制器两层隐藏。
- 佐证: 引擎潜空间 PCA 4D@99% (任务自由度 4D 非 7D)。关节级模型前置条件 = obs 加 q
  通道 + 关节控制接口, 是另一层架构。

## 3. 安全执行边界 saturate "有效果么" 实测
- saturate = 逐通道 clip ±0.6 (POS_LIMIT); 调用点: 引擎/real 主循环 (decide 后执行器前)
  + node_logic 画布真实执行; u_sat[3] 夹爪通道显式恢复 (开关量不受限幅)。
- **实测日常零触发**: STAGE_V_CAP 阶段范数限速 (0.02~0.35) 已先削幅, 引擎 u 前3通道
  max 0.154 < 0.6 → saturate 是纵深防御保险丝 (cap 可标定/缺 key 时兜底), 非断路器。
  真实日常安全 = 否决权 (残差>2.0 急停 _zero) + cap 分阶段限速。
- 回答"有效果么"类问题模式: 分层 (架构定位/调用点/实测触发率/真实承担者), 承认冗余,
  讲清防御纵深价值。

## 4. decide (动作调制) 四步流水线 (老倪贴码追问)
① 否决权: residual > veto_th(2.0) → _zero 急停; 连续 max_veto(5) → 异常
② u = u_ff + k_fb·u_fb **相加** (历史: 凸组合在量级差21倍时砍速71% → 08-26 改相加)
③ 阶段 cap 等比缩放保方向 (接近0.35/对位0.12/下降0.09/抓取0.04/抬起0.30/转移0.35/
   插入0.085/完成0.02 m/s)
④ v_min 保底 (接近0.12/对位0.04/抬起0.10/转移0.12; 插入 real 另设 0.02) — 防末端磨蹭
之后: u[3] 由 gripper_cmd 状态锁存覆盖 (非比例) → saturate → 执行层 act 映射。
调制只调速度幅值, 方向永远由 u_ff+u_fb 向量和决定。
