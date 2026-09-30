---
name: zmax-real-closed-loop
description: Use when 状态空间引擎换 metaworld+YOLO 真实化闭环, R0/R1 分层, 探针先行。
version: 1.0.0
author: 静静 (Hermes)
license: internal
metadata:
  hermes:
    tags: [zmax, state-space, metaworld, yolo, real-closed-loop, reality-gap, mujoco]
    related_skills: [zmax-policy-training-eval, zmax-scene-engineering, zmax-console]
---

# Z-MAX 状态空间真实化闭环 (R0 物理 / R1 视觉工件感知)

## When to Use
- 老倪要"引擎世界换 metaworld、YOLO 每步喂 obs——真闭环"(方案2)
- 状态空间画布 ▶运行 的简化世界(纯 numpy 积分)要换成真实物理 + 视觉感知
- RealityGap 验证:控制器/阶段机在"真实物理 + 视觉定位误差"下能否完成插拔

## 核心文件
- 引擎(简化世界): `tools/gui/state_space_sim.py` — 六层控制器源码按文件 importlib 加载(纯 numpy)
- 真实化闭环: `tools/gui/state_space_sim_real.py` — R0/R1 一体化, `--vision` 开关
- 六层源码: `src/lerobot/policies/left_right/state_space/{perception,parallel,cognition,dynamics,safety,execution}.py`
- YOLO 链: `src/lerobot/policies/yolo_3d/yolo_state_aligner.py` (detect_3d / align)
- 设计文档: `docs/closed_loop_realization_design.md`
- 探针存档: `tools/probes_real/probe_mw_real*.py` (契约实测) + `probe_r1_calib.py` (视觉定标)

## 命令
```bash
cd /home/ubuntu/lerobot-smolvla-lew
# R0 物理真实化 (env.step 真物理 + 真值感知), 8 轮成功率
gui-venv311/bin/python tools/gui/state_space_sim_real.py 8
# R1 视觉工件感知 (YOLO 定位来料 peg + 编码器末端), YOLO 每 20 步刷新
gui-venv311/bin/python tools/gui/state_space_sim_real.py 6 --vision --every 20
# 单轮调试 trace (每 25 步打 x/tgt/残差/接触/夹持)
R0_TRACE=1 gui-venv311/bin/python -c "import sys; sys.path.insert(0,'tools/gui'); from state_space_sim_real import RealStateSpaceSim; print(RealStateSpaceSim(seed=100).run()['stage'][-1])"
```

## 基线 (2026-09-04 实测)
- R0 真值感知: 5/8 = 62% (成功轮 265-346 步)
- R1 视觉工件: 3/6 = 50% → 视觉定位误差成本 ≈ 12%
- 基线对照: R0 = 控制器+真实物理可行性; R1 = +视觉工件定位误差

## 分层设计
- **R0 物理真实化**: 六层控制器指令 → metaworld env.step 真实接触/夹持/插入; 感知=env 真值直读。验证"控制器+真实物理"
- **R1 视觉工件感知**: 感知层 = YOLO 定位来料 peg(悬停区刷新+EMA) + 工位标定孔位 + 编码器末端。真机同构架构
- 顺序: R0 先行 (秒级/轮, 快速暴露控制器问题), R1 后上 (视觉慢)。R0 崩别让 YOLO 背锅

## 探针先行方法论 (铁律)
写任何真实化代码前, 先跑探针钉死 metaworld 契约 (每个都是血泪教训):

### metaworld 关键契约 (实测)
1. **布局跨进程漂移 >10cm**: 同进程 seed0 freeze 稳定, 换进程 peg/goal 全变 → 几何必须每轮现场采样 (obs[4:7]/site), 引擎写死常量仅作展示
2. **seed 冻结时序**: `_freeze_rand_vec=True` 必须在 `reset(seed)` **之后**设; 先 freeze 则布局锁死, 多轮跑同一轨迹 (0/8 实锤)
3. **控制锚 = obs[0:3] hand (腕部=真实夹爪 claw), 不是 endEffector site**: site 是腕下 4cm 虚拟视觉点! 用 site 当夹爪 → 真夹爪悬空 2-3.5cm → 永远空夹。且 site 与 claw 都挂 hand body (claw 局部 z=0, site 局部 z≈-0.04)
4. **动作映射**: metaworld act ±1 = 目标位移, 伺服 ramp 收敛稳态 ~9mm/步@act1 (≈ 引擎 0.5m/s×0.02s=10mm/步, 巧合对齐); act = u(m/s) / 0.5
5. **估计器/动力学 B 增益**: B=0.02 (实测位移≈u×0.018), 不是 dt_env=0.1 → B 0.1 预测过冲 5 倍 → 残差爆发 → contact_p 误判接触 (离销 20cm 空闭合)
6. **gripper 语义反转**: metaworld obs gripper 1=全开 0=全闭 (与引擎相反!); 空夹收敛 ~0.29, 夹住 3cm 销后深夹也到 ~0.28-0.30 (cognition 注释"夹住饱和 0.70"指接触建立时刻的早期值, 别当深夹判据)
7. **peg 0.1kg free body**: 贴桌面 (底嵌入 0.3mm), 长 24cm 沿 x 躺平 (geom size [0.015,0.015,0.12] 局部, 世界 [0.12,0.015,0.015] 需 quat 旋转确认); 夹爪两指沿 y 开合
8. **真夹持判定 = 抬起 peg 随动**: 夹爪移动时 |peg−x−锁存偏移| 保持 = 夹住; 漂移>3.5cm = 滑脱 → 强制回退 stage0 (peg 半挂不落台面时 advance 的"落回"判据不触发会卡死 350 步)
9. **夹持锁存要深夹**: grp<0.60 (闭合 10-15 步) 才锁存抬升; 浅夹 0.78 就抬滑脱率高
10. **抓握目标用实时销位置**: 静态采样坐标会被首次下降碰移的销坑掉 (回退重抓空夹); 接近/对位/下降/抓取目标 = 每步实时 peg

### R1 视觉契约 (定标实测)
1. **YOLO hand 不可用于控制**: 夹爪接近销遮挡 → 检测漂移 12-20cm。hand 必须走编码器 (真机同构: 机械臂有编码器, 视觉只定位工件)
2. **YOLO hole 不可用**: 漂移 6-37cm → 插入工位固定, 产线一次标定 (仿真: 每轮现场采样 site 值)
3. **YOLO peg 有条件可用**: 悬停高度 (夹爪 z>0.09, 销上方 6cm+) 误差 7-17mm; 贴近 2cm 遮挡崩到 26-48mm → 悬停区刷新 + 下降/抓取期冻结
4. **视觉 peg 单帧噪声 ±1-3cm**: EMA α=0.5 + 跳变>5cm 丢弃; 悬停多次刷新收敛
5. **视觉反投影 z 偏低 ~1.5cm**: 不能用视觉 z 阈值判"到抓握位" → 改物理停滞检测 (下降中 z 连续 ≥8 帧位移 <0.4mm = 被销顶住 → at_grasp_pose)
6. **R1 失败自愈**: 滑脱回退后悬停 (z 高) 自动重新视觉定位被碰移的销

### mujoco API 陷阱
- site 名: `m.site("name").id` 可用; `model.site_id2name` / `site_name2id` **不存在** (版本差异)
- 世界坐标: `d.site_xpos[id]` / `d.geom_xpos[id]`; body 用 `d.xpos`, **没有** `body_xpos`
- geom 名: `m.geom("name").id`; `m.jnt_bodyid[j]` (数组索引); 质量 `m.body_mass`
- geom 朝向: `m.geom_quat[gid]` (没有 geom_xmat), 手动 quat→mat 乘 size 得世界半尺寸
- contact 遍历: `d.contact[:d.ncon]`, geom 名可能为空串 (桌面等) — 接触对里 `'' <-> peg` 是 peg 贴桌面, 别误读成夹持!

## 验证方法
- 多轮成功率统计 (每轮不同 seed = 不同布局): 8 轮起
- 失败归因三件套: 阶段停留 Counter / 末 gripper / 接触峰; 卡死看 trace (R0_TRACE=1)
- 阶段回退 = 夹持丢失; 下降超长 = 接触/位姿证据起不来; 转移卡 = 夹持状态乱/销半挂; 插入卡 = 摩擦阻力 (加 v_min)
- 单轮成功轨迹: 接近→对位→下降→抓取(真夹持 gf=1)→抬起→转移→插入→完成, 265-346 步

## 失败模式速查 (2026-09-04 实测)
| 现象 | 根因 | 修复 |
|------|------|------|
| 8 轮同一轨迹 0/8 | seed 冻结时序错 | reset 后设 freeze |
| 永远空夹 gripper 全闭 | 控制锚用 endEffector site | 用 obs[0:3] hand |
| 接触概率 0.98 空中乱触发 | B 增益 0.1 过冲 | B=0.02 |
| 阶段抬起↔下降循环 | 夹持锁存阈值>饱和 | grp<0.60 深夹 |
| 滑脱后卡转移 350 步 | peg 半挂不落台, 回退判据不触发 | 滑脱强制 _goto(0) |
| 插入差 0.1mm 磨死 | insert_depth 太紧 | 0.006 + 插入 v_min 0.02 |
| R1 卡下降 400 步 | 视觉 peg z 偏低, z 阈值等不到 | z 停滞检测 (≥8 帧) |
| 抓取对准幻影追着跑 | 夹爪遮挡 peg 检测崩 | 悬停刷新 + 下降冻结 + EMA |
| 机械臂乱转接近/对位 0/8 (2026-09-06) | 蒸馏 MLP 单布局: goal 零方差 ss≈1e-8 → 真实化现场孔位偏离 → 归一化 ±6000σ → 输出恒饱和 [0.6,-0.6,-0.6] | 零方差通道归一化置 0 + forward 逐通道 \|x\|≤4σ 域守卫 (域外解析兜底), commit 185dab9e |

### 🐛 2026-09-06 蒸馏 MLP 域外两大坑 (R0 全 seed 失败根因, commit 185dab9e)
1. **零方差除零炸弹**: 蒸馏数据单布局 → goal/孔位通道 std≈0 → 导出 ss=std+1e-8 →
   推理现场采样孔位偏离训练常量 (真实化 >10cm 布局偏移) → 归一化 ±6000σ → 网络爆 →
   u_ff 恒饱和 ±0.6 (三通道同值 = 特征性症状)。修复: 归一化对 ss≤1e-4 通道置 0
   (训练时该通道输入恒 ≈0, 网络权重已学成忽略)。parallel.py mlp_ff_forward 与
   state_space_sim.py load_trained_left_brain **两处同修**。
2. **D_GUARD 3D 距离漏检 target 通道域外**: 布局偏移让 target 通道 (obs[36:39]) 归一化
   4-5σ (如 seed100 peg y=0.617 vs 训练 0.498±0.03), 但 hand→target 距离可能仍小 →
   MLP 放行输出弱/反 → 卡对位。修复: 域判定升级**逐通道** |x_norm| ≤ DOMAIN_SIGMA(4σ),
   任一通道域外 → analytic_forward 解析守卫 (全局稳定, 09-04 基线 62% 即解析)。
3. 诊断法: u_ff 恒 ±0.6 饱和 → 查 max|x_norm| 与 argmax 通道 (debug 打印归一化输入);
   MLP vs analytic 方向对照 (patch forward 打印两者)。
4. 蒸馏数据布局覆盖 = 根治方向 (多布局重导 → goal 方差正常, 重训 547K), 未做。

### 🐛 2026-09-06 真实化回归修复 (0/8→5/8=62.5%, commits c7ba9757 + 5de91cec)
1. **转移→插入过早切换**: 只看水平 dh<0.025, peg 头 z 未到位 (低于孔口 1.6cm) 就切插入
   → 插入目标=孔底-实时off 硬推 → peg 头被孔沿/夹具挡 → peg 在夹爪里被挤滑 (off 逐帧
   缩短是特征) → 滑脱。修复: advance 加 hole_z 可选参数, 转移→插入须 peg 头悬孔口上方
   2cm±1.2cm (引擎不传 hole_z 行为不变)。
2. **MLP 联合分布域外 (逐通道守卫救不了)**: 转移/搬运段 target 通道单看域内, 但布局
   随机漂移下 MLP 输出 z 与目标相悖 → peg 头被压低扫孔下夹具。修复: **R0 真实化强制
   解析** (self.accel.forward = analytic_forward; 引擎快演单布局=训练域仍 MLP)。
3. **斜插顶孔口上缘**: 插入单段直线 (悬高 2cm→孔底) 是斜插, peg 头圆柱端面无倒角
   (mujoco 刚体) → 顶孔口上缘 z 卡 +5~10mm 磨死 (seed109: z孔偏+0.010 depth 6.3cm 卡
   56 步)。修复: **两段式插入** — 段①peg 头垂直对齐孔口中心高度 (z_err≤4mm, xy 保持),
   段②水平沿孔轴推入; 配套 **peg_head 夹持后一律编码器推算** (x+_grasp_off0+head_off,
   真机同构, off 锁死不追滑脱, 滑脱由随动验证 gf 回退), R0 不再依赖 site。
4. 残余失败 (~37.5%, 与 09-04 基线同水平): 转移卡 (布局难/悬高路径) + 乱序特殊布局;
   转移路径优化/多布局重蒸馏为下一步。

### 🧪 2026-09-07 晚 静静: sim_real 失败布局根因钉死 (site 真值实验) + 学生固定布局盲区修复
**实验 (SS_R0_SITE_PEGHEAD=1 开关, 已默认关)**: 夹持后 peg_head() 强制返回 site 真值 —
seed100/105/106 **依然失败** → 失败不是感知对齐问题, 是夹持几何物理:
- peg 头是 10cm+ 悬臂 (夹爪抓中段), 插入时 site peg 头横向偏孔口 min 15.6mm (成功轮
  seed104 顺利进孔 59.6mm), 孔间隙 1-2mm → 端面顶孔沿, mujoco 无倒角刚体无解
- **成功/失败轮 site-推算偏差几乎相同 (p50 5-6mm, 插入前 5-7mm)** = 悬臂下垂系统常数,
  不是判别信号! "假对准"仅在滑动 >8mm 后成立 (seed100 插入段 5→20mm 递增)。调度阈值
  按偏差分胜负是伪命题 — 成败在误差方向是否落孔间隙内 (布局运气/夹持几何)
- 结论: seed100/105/106 = 真机级夹持几何问题 (抓取点/倒角), R0 调度层边际收益为负,
  两次会战 6+ 次尝试无突破。演示用成功布局, 难布局留真机
**mw3 学生 sim_real 固定布局 0/8 全盲 (技能坑6 现状实锤)**: 前段 MLP 卡接近/对位
(500 步不动) — 训练分布 (随机多布局 71ep) 不覆盖固定布局方位 → 解除 R0 强解析未完成。
**修复: tools/collect_simreal_teacher_data.py** — RealStateSpaceSim(seed 固定布局, 解析
教师) 成功轮 → raw npz (对齐 collect_mw 格式) → 并入 ss_mw_raw → 融合重训:
- 概念验证: 71 随机 + 4 固定布局 (101-104) → 5000 步 (0.78ep 欠拟合) → 学生 101-104
  穿过接近/对位到下降/抓取 (mw3 时卡死 500 步) — 盲区修复, 但下降/抬起段仍崩 (欠拟合)
- 铁律: 融合数据必须 ≥30K 步 (≈4.8ep), 5K 步只够修前段
- seed100 (失败布局, 不在训练集) 仍卡对位 — 训练只能覆盖成功布局 (教师都过不了的
  物理难布局蒸馏无意义, 与 09-06 晚结论一致)

## 沿革
- 2026-09-04 首建 (R0 62% / R1 50%, 13 发探针, 提交 5f0bdf83)

### 🐛 2026-09-07 GUI ▶运行 3D 视图"显示不成功"全链路 (commits b73c37b5 + ea521b06)
**排查铁律 (先分清三层, 别被数据骗)**:
1. **npz 的 `target` = 手的目标位姿, 不是孔口!** 参照物: `hole_mouth`=孔口、`goal`=孔底、
   插入沿孔轴 (如 x: 孔口 x=-0.229 → 孔底 x=-0.295)。拿 target 当孔口会误判"peg 头偏 12cm 没插上"
   (真实已到孔底 0.2mm)。meta.success 看 meta 的 success + history 证据链 + peg_head vs goal。
2. **3D 视图显示失败 ≠ 渲染错**: ▶运行(默认真实化 R1 视觉)轨迹 = 真失败就显示失败;
   EPISODE 回放(预录成功 npz)≠ 本次运行。看 simulink_log.txt 尾部 "⚠️ 未完成/✅ 完成"。
3. **GUI 真实化 seed 写死 = 演示永远失败**: simulink_module.py:10838 `RealStateSpaceSim(seed=100...)`,
   seed100 是 R0 实测失败布局 (夹持链问题) → 每次 ▶运行 必失败。R0 回归 seed100-109 仅
   101/102/103/104/108 通过 (104 最快 352 步) → GUI 换 seed=104。

**seed100 失败根因链 (实测, 三层叠加)**:
1. 夹持后 peg 在夹爪内**逐次受压累积滑动**: 插入遇阻时推力 > 夹持保持, 顶一次滑一点
   (site真值 pegHead vs 编码器推算 hand+off+head_off 的差 11.8→13.3→14.7mm 递增 = 铁证)
2. peg 滑动 → 推算"假对准" (y/z 看着 0.3mm 准, site 真值偏 5mm) → 遇阻微调按错目标瞎调
3. 回退转移时 peg 仍卡孔沿 → 夹爪回拉把 peg 从夹爪里扯出 (gf→0 滑脱)

**修复 (通用加固, seed100 类仍物理难)**:
- 🛡 **插入遇阻保护**: depth (peg头-孔底) 停滞 5 帧 + 指令仍在推 = 顶住 → 充分回撤脱离
  (12帧≈15mm, 解除应力, peg 不再累积滑动) → 分级回退: 1-2 次回退转移重新对孔
  (z 对齐已收紧), 3 次回退接近重抓 (刷新锁存偏移)。真机同构: 遇阻先退再对不硬顶。
- **z 对齐收紧**: 两段式段①判据 z_err 4mm→1.2mm (孔间隙 1-2mm, 无倒角刚体残留 2.6mm
  水平推必顶孔口上沿; z 校到 0.6mm 即推进 1.5mm 实证)
- 随动验证 3.5cm→2cm (宽限期 20 帧 2cm, 深夹期 peg 被挤向根部属正常), 早发现夹持失效
- grasp_th 0.40→0.50 (obs<0.50 深夹到位才抬, 防浅夹 0.5x 锁存即抬滑脱)

**调参教训 (3 次尝试, 边际收益递减)**: seed100 类 = 夹持物理对 seed 敏感 (夹持 gripper
轨迹与成功轮几乎相同 0.565 vs 0.57 却一稳一滑), 抓取深度/锁存时机/随动阈值/遇阻策略
全调过无突破 (4/8~5/10 持平, 101-104 稳定不伤)。真解 = 真机级夹持几何/重抓位置策略,
非 sim 调参能覆盖。GUI 演示换成功 seed, 难布局留给真机。

### 🐛 2026-09-06 晚 大会战: 多布局重蒸馏 + 分层伺服 (学生 47/48=97.9% 追平教师, commit 3baceaf9)
**管道** (全部真实 metaworld, mujoco 真物理 + mj_contactForce 真触觉):
- 采集: `tools/collect_mw_teacher_data.py` — 解析教师 (run_episode analytic=True) × 随机多布局,
  每成功 seed 一个 raw npz (obs43/u_ff_vec/u_exec_vec/force/stage 全量)
- 转换: `tools/convert_mw_raw_to_ss.py` (raw→states39/actions4) → `tools/build_ss_dataset.py` →
  `configs/policies/config_left_right_mw.yaml` → lerobot_train 30K 步 → `export_ss_left_brain.py`
  (SS_STATS_ROOT=data/ss_mw_lerobot 指定训练集 stats!) → models/ss_left_brain.npz
- 右脑: `tools/train_ss_right_brain_mw.py` — 动作输入=**u_exec_vec 实际下发** (非教师建议,
  两者量级差 3 倍), contact 标签=**真实 force_norm>0.05** (非手-peg 距离代理) →
  acc 0.998 触0.98/空0.00, next 误差 0.1cm; 训练时数据/动作与推理端 (act4=u_prev) 同构
- 评估: gen 管道学生=前段 MLP + 插入段解析 (分层伺服), run_episode 单 seed 独立摸底 (勿用
  main() 的多 seed 重试 — 布局每进程随机, 重试=换布局, 统计失真!)

**关键坑 (全部实测)**:
1. **gen 采集管道 ≠ sim_real 代码, 两处修复必须同步移植**: 两段式插入 target + advance 传
   hole_z。缺一教师成功率只有 38-45% (卡插入/夹持丢失回退循环)。
2. **hole_z 条件的 peg_z = peg 头 z (pegHead site), 不是 pegGrasp 夹持点 z!** 传错对象 →
   z 条件永不满足 → 卡转移 (教师 17%)。修正后教师 12/12=100%。
3. **export 归一化 stats bug**: export_ss_left_brain.py 硬编码读 data/ss_insert_lerobot
   (引擎域) → 多布局 ckpt 导出配错 stats → 摸底 0/24 全崩。修复: SS_STATS_ROOT 环境变量
   指向训练数据集 (读 meta/stats.json)。stats 错配的症状 = 训练 loss 好但 rollout 全崩。
4. **align_th 收紧教训 (回滚!)**: 真值场景想收紧转移→插入阈值 (0.02→0.008) → 教师 97%→0/6
   全崩 (含前段接近/对位!与阈值无关的阶段也崩 — 共享调度器参数耦合比想象深, 改前必须
   单 seed A/B)。保持默认, 插入对准靠分层伺服解决。
5. **分层伺服架构 (核心结论)**: 真实碰撞插入 = 毫米级 + 无倒角刚体 → 神经网络输出底噪
   (0.4cm/s 实测) 导致转移段"漂过孔口"触发切换 (非定点悬停) → 垂直降顶座体卡死 (全 MLP
   学生 0-1/24)。工程正解 (真机同构): 前段 (接近→转移, 无接触容差大) = 蒸馏 MLP 真实主
   执行; 插入段 = 解析伺服精插。学生 47/48=97.9% 追平教师 (97-99%)。
6. **sim_real 固定布局的稀有方位泛化**: sim_real _reset 固定全局 np.random (seed×7919+13),
   某固定布局 hand-peg 相对方位在训练分布边缘 → MLP 接近段输出反向 (u_mlp 与 u_ana 同
   obs 方向相反 = 铁证), 绝对坐标 4σ 域守卫是盲区。sim_real 默认仍解析 (SS_USE_MLP=1 实验
   开关分层学生); gen 随机布局管道学生无此问题。
7. **RL 训练 30K 步 vs 数据量**: 71ep/49765帧 30K 步≈4.8 epochs 够用 (loss 0.012);
   8000 步≈1.2 epochs 欠拟合 (0/24)。
8. 数据量: 随机布局教师 ~40-98% 波动取决于代码版本; 两段式+hole_z 修复后稳定 97%+。
   71ep 成功轨迹 ≈ 2.6 万帧以上学生可追平教师; 失败布局 (物理难) 不入训练集 (教师也过
   不了, 蒸馏无意义)。
