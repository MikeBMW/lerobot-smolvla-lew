---
name: zmax-metaworld-real-loop
title: "Z-MAX 引擎真实化闭环 (R0 物理 / R1 感知)"
description: "Use when 状态空间引擎接 metaworld 真实物理闭环 (R0/R1)."
trigger: "Use when 老倪提 真实化/闭环真实化/R0/R1/metaworld 物理闭环/引擎世界换 metaworld/YOLO 每步喂 obs, 或改 tools/gui/state_space_sim_real.py。"
---

# Z-MAX 引擎真实化闭环 (R0 物理真实化 → R1 YOLO感知真实化)

> 设计文档: `docs/closed_loop_realization_design.md`
> 代码: `tools/gui/state_space_sim_real.py` (RealStateSpaceSim, R0 已落地)
> 探针: `tools/probes_real/probe_mw_real*.py` (12 发, 契约数据源, 保留为标定工具)
> 全量契约表见 `references/metaworld-contract-2026-09-04.md`

## 为什么做 (架构背景)
▶运行 现状: 引擎 = 简化世界数值闭环 (**obs 世界状态直读**, YOLO 从不进闭环, det3d 只进缓存展示);
真实 YOLO 感知 = 引擎跑完后 **1 帧** metaworld 证据采样 (_real_yolo_sense_once)。
老倪方案2 真实化: 物理推进换 metaworld env.step, 感知换渲染→YOLO→39D, 让控制器在真实物理+视觉下闭环
(RealityGap 仿真验证)。分层:
- **R0 物理真实化** (已落地): env.step 真物理 + env 真值直读感知。秒级/轮。验证控制器+真实物理。
- **R1 感知真实化** (待做): obs 由渲染帧→YOLO det3d→39D 构造。N=1 时 ~1s/步, 单轮 ~8min。

## R0 架构
RealStateSpaceSim 复用六层控制器源码 importlib (perception/parallel/cognition/dynamics/safety/execution,
同引擎 _load 方式), **控制器代码不改**, 只换"物理推进 + 感知源":
- 每步: 上一拍 u_vec → act 映射 → env.step → 读 obs → 构造 39D (引擎语义骨架, 几何全现场) →
  六层照跑 (前馈/估计/校正/调度/限幅/执行) → 阶段机 advance (证据全现场几何) → 记录 tr (引擎兼容集)
- 八阶段: 接近→对位→下降→抓取→抬起→转移→插入→完成

## 探针钉死的 metaworld 契约 (全部实测, 别信引擎常量/代码注释几何)
1. **控制锚 = obs[0:3] hand (腕部=真实夹爪 claw)**; endEffector site 是腕下 4cm 虚拟视觉点 —
   拿它当夹爪位置 = 空夹根因 (探针12 前所有抓取全空夹; 探针里 "peg 接触" 其实是 peg 贴桌面 g3,
   被误读成夹持!). 抓握: hand 降到 peg_z+0.02 (被销顶住 = 指已包销) 闭合即夹住。
2. **metaworld 布局跨进程漂移 >10cm** (同进程同 seed 稳定) → 几何每轮 env 现场采样,
   引擎写死常量 (PEG_POS0/HOLE_POS/HOLE_MOUTH) 是某次随机化快照, 只配展示。
3. **_freeze_rand_vec 必须先解冻再 reset(seed) 再冻结** — 先 freeze 后 reset = 布局锁死,
   多 seed 全跑同一轨迹 (0/8 实锤)。每轮 _reset 解冻→reset→冻结。
4. **gripper obs 语义 1=开 0=闭 (与引擎相反)**; 空夹收敛 ~0.29, 深夹夹住 3cm 销也到 ~0.28-0.66 →
   grp 单值无法区分夹住/空夹, **夹持判定 = 抬起时 peg 随动** (grasp_force, |peg−x−off0|<0.02)。
5. **action ±1 = 目标位移, 伺服 ramp 收敛**: act=1.0 稳态 ~9mm/步 → 位移≈速度指令×0.018-0.02s;
   估计器 B 标定 0.02 (原 B=0.1 预测过冲 5 倍 → 残差 0.5 爆发 → contact_p 误判接触)。
6. **metaworld 单轮硬上限 500 步** (max_path_length), truncate 后 step 抛 ValueError → try/except 截断本轮。
7. peg = 0.1kg free body, 底面嵌桌面 0.3mm; 夹爪沿 y 开合 (3cm 宽销沿 x 躺); 夹住销深夹 grp~0.28-0.30。
8. **mujoco API (本机版本)**: m.site(name).id / m.geom(name).id / d.geom_xpos / m.geom_quat (无 geom_xmat,
   用 quat2mat) / d.xpos (无 body_xpos) / m.jnt_bodyid / m.geom_bodyid; geom size 是**局部**半尺寸,
   世界尺寸 = quat 旋转后 (peg size [0.015,0.015,0.12] 世界 = [0.12,0.015,0.015] 沿 x 躺)。

## 抓取/夹持真实语义 (控制器落地)
- 下降目标 hand_z≈peg_z+0.004 但物理挡在 peg+0.02 (被销顶) → at_grasp_pose 用几何证据
  (d_xy<0.025 and x[2]<peg_z+0.03), 别只等力觉 (cognition 注释 151: 张开指下到销两侧可能不接触)。
- 深夹 grp<0.60 (close_steps≥3) 才锁存抬升试探; 浅夹 0.78 就抬 = 滑脱率高。
- 滑脱 (peg 未随动) → **强制回退 stage 0** (advance 的"peg 落回台面"判据在 peg 半挂时永不触发 →
  卡死在转移 350 步实锤); 回退后夹爪张开, peg 掉回台面, 重抓目标用**实时 obs[4:7]** (销可能被碰移)。
- 插入: 阈值 6mm (0.004 在真物理下差 0.1mm 磨死) + 插入阶段 v_min=0.02 (孔壁摩擦, 比例项趋零磨死)。

## R0 状态 (2026-09-04)
- 成功率 6/12 (seed 100-111 真随机布局); 成功轮 265-346 步八阶段全走通, 夹持全程 gf=1.0。
- 失败: A 抬起滑脱后重抓 ~25% (销被推移/半挂) B 插入卡滞 ~17% (孔壁摩擦边界)。调参边际收益递减。
- 验证: `R0_TRACE=1` 逐 25 步 trace; `gui-venv311/bin/python tools/gui/state_space_sim_real.py N` 统计。
- 代码在 gui 侧但控制器源码在 src/lerobot/policies/left_right/state_space/, 引擎断点坑见 zmax-console。

## R1 待办 & 决策点 (D1-D4 老倪未拍板, 推荐: D1 先R0后R1✓ D2 解析前馈不挂引擎MLP D3 N=1起步 D4 新文件独立)
- **两套 39D 段位冲突**: 引擎 cur=[x(3),gripper(1),v(3),peg(3),HOLE_POS(3),pad…] vs
  metaworld/YOLO cur=[hand(3),gripper(1),peg(3),peg_quat(4),pad(7)]。前馈解析律 u=Kp(target−pos)
  只吃 [0:3]/[36:39] 相对量 → 不受段位冲突影响; 引擎训练 MLP 吃引擎语义 → 换世界后错位,
  故 R1 推荐解析前馈。
- YOLO 检夹爪中心 (endEffector z≈0.155) vs obs hand 腕部 (z≈0.195): 4cm 固定偏移 —
  **pos 与 target 必须同源** (都 YOLO 或都真值), 不许混坐标系。
- 真实化感知刷新: metaworld 布局/接触真实执行 = 真机 RealityGap 数据源。
