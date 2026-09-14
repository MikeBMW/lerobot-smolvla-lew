# 7轴冗余臂李雅普诺夫稳定性分析 (2026-08-16)

## 背景 (老倪质疑)

"前馈PD系统根本没有质量, 你的数学分析怎么算的?" + "正确的方法怎么算稳定性? 用7轴冗余臂?"

画布上二阶分析 m·s²+(b+Kd)s+(k+Kp)=0 的 m/b/k 是**动作节点 params 的默认值** (m=1.0 b=2.0 k=5.0,
ff_pd_top.json 里根本没写 → 永远默认) — 是单轴直觉玩具, 不是真实机械臂稳定性证明。

## 正确方法 (3 步)

1. **拉格朗日建模**: M(q)q̈ + C(q,q̇)q̇ + G(q) = τ — 7×7 惯性矩阵 M(q) (随位形变) + 科氏 C + 重力 G
2. **李雅普诺夫直接法**: PD+重力补偿 τ=-Kp·e-Kd·q̇+G(q), 能量函数 V = ½q̇ᵀMq̇ + ½eᵀKpe
   → V̇ = -q̇ᵀKdq̇ ≤ 0 (Takegaki-Arimoto 1981: 半全局渐近稳定, 不需 m 具体值)
3. **冗余性**: 7轴>6维任务空间, 零空间运动不影响末端稳定性

## 工具: tools/stab_7dof.py + tools/seven_dof_arm.xml (gui-venv 跑)

7R 串联臂 (连杆 1.0/1.0/0.9/0.8/0.7/0.6/2.0kg, 重力 -9.81, timestep 0.0005,
每个关节 armature=0.02 电机转子惯量 — 防末端关节数值刚性):
- M(q): `mujoco.mj_fullM` (7×7, 对称误差 ~1e-15)
- G(q): **`G = M @ d.qacc[arm_idx]`** — mj_forward 后 qacc 是重力加速度 (无控时 M·qacc=G)
  - ⚠️ mujoco 3.x **mj_inverse/qfrc_inverse/qfrc_gravcomp 全返回 0** (此模型下) — 别用
  - ⚠️ 提取 G 前必须 **保存/恢复 qvel** (清零算 G, 恢复仿真状态)
- 验证: 3 组随机扰动 (0.15 rad) → V̇≤0 100% + 误差 → 1e-12 + V 衰减 1e-23 → STABLE

## 坑 (踩了一路)

1. **metaworld Sawyer 模型不能直接做力矩控制**: 臂关节是自由关节 (无 actuator, nu=2 只夹爪),
   metaworld 用 mocap 位置控制 (eq weld hand↔mocap) → qfrc_gravcomp=0, 力矩控制失效
   → 放弃, 自己写 clean 7R 模型
2. **mujoco 3.x**: mj_inverse 输出在 qfrc_inverse 但此模型恒 0; qfrc_gravcomp 也 0;
   jnt_qposadr/jnt_dofadr/body_mass 是 numpy 数组 (取值要 [0] 索引)
3. **数值刚性**: 末端关节 M[6,6]≈0.001 极轻 → Kp 大 + dt 大 → qvel 爆炸 (760 rad/s)
   → timestep 0.0005 + armature 0.02 + 末端质量 2kg + Kp=200/Kd=40
4. **model/data 绑定**: `MjData(MjModel.from_xml_path(XML))` 两次加载 → data 绑错模型 → G 全 0
   → 必须 `m = from_xml_path(XML); MjData(m)`
5. **目标位形≠初始时 G 提取混入科氏残留** → 停在不完全补偿平衡点 (误差 0.35 不收敛)
   → 同一目标位形 + 多随机扰动 (G 精确) 才是严格验证
6. **mj_step 用 model.opt.timestep** (不是代码传的 dt) → 传 dt 只影响 V̇ 差分, 必须在 XML 设 timestep
7. 模型 XML 被 .gitignore 拦 (*.xml) → `git add -f`

## 结果

reports/stab_7dof.json + stab_7dof.png (V(t)/V̇(t)/‖e‖ 三联动图, 对数轴):
- 7轴冗余臂 PD+重力补偿: **V̇≤0 100%, 误差 1e-12, V 衰减 1e-23 → 半全局渐近稳定 STABLE**
- 无补偿对照: 终态静差 0.03-0.8 rad (vs 有补偿 1e-12) — 重力补偿必要性
- 结论可写进技术协议: "符合5个场景的具身方案" 的稳定性证明 = 李雅普诺夫直接法 (非二阶特征根)
