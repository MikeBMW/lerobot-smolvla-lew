# 闭环真实化设计 (方案2) — metaworld 物理 + YOLO 视觉感知真闭环

日期: 2026-09-04 · 静静 设计 · 老倪 拍板
状态: **待确认** (决策点 D1-D4 在文末)

## 1. 目标

状态空间画布 ▶运行 的 500 步闭环,把"物理世界推进 + 感知"从引擎简化世界
换成 metaworld peg-insert-side-v3 真实物理,感知 obs 由"渲染帧 → YOLO → 3D"
构造(真机同构:真机也只有 2D 检测,没有世界真值直读)。

验证命题:**六层控制器(前馈/估计/调度/限幅)在真实物理 + 视觉感知下能否
完成插拔**,并量化 YOLO 感知误差(RealityGap)对成功率的影响。

## 2. 分层:先 R0 后 R1 (推荐顺序)

| 层 | 物理推进 | 感知来源 | 单轮耗时 | 验证什么 |
|----|---------|---------|---------|---------|
| R0 物理真实化 | metaworld env.step | env 真值直读 (obs[0:3]/[4:7]/[36:39]) | ~秒级 (500 步 × <1ms) | 控制器+真实物理 (接触/夹持/插入动力学) |
| R1 感知真实化 | metaworld env.step | 渲染帧→YOLO det3d→39D (每 N 步刷新) | ~8min/轮 (N=1, 500 步×~1s) | 控制器+真实物理+视觉感知 (RealityGap) |

R0 是 R1 的地基和对照:若 R0 成功率高而 R1 崩,失败归因 = 感知误差;
若 R0 就崩,先修控制器/物理映射,别拿 YOLO 背锅。

## 3. 探针实测契约 (2026-09-04 三发探针, gui-venv311)

### 3.1 时序与性能
- env.step 无渲染 <1ms/步 → R0 秒级; metaworld import+构造 ~0.8s
- render 480×480 corner2 = 0.14s/帧; +YOLO 检测+深度模型 ≈ 0.3-1s → R1 预算 ~1s/步
- 引擎 dt=0.02 (50Hz); metaworld 1 step ≈ 0.1s 物理 (10Hz) → 步频差 5 倍,
  控制器时间常数 (EMA α=0.15≈10步 / confirm_n=2 / 阶段限速) 需按新步频重标

### 3.2 动作映射 (速度指令 → metaworld action)
- 引擎: u (m/s, ±0.5) × dt 0.02 → 位移 10mm/引擎步
- metaworld: act ±1 = 目标位移, 伺服 ramp 收敛; 连续同向 10 步累积 64mm,
  稳态 ~9mm/步 (act=1.0) → 位移尺度巧合对齐: 1 引擎步 ≈ 1 env step
- 标定: act = clip(u_vec[:3] / 0.5, -1, 1) 起步, audit_state_machine.py 实测调

### 3.3 几何一致性 (⚠️ 架构级事实)
- **同进程内 seed0 freeze 稳定; 跨进程漂移** (peg/goal 两次进程差 >10cm)
  → 引擎写死常量 (PEG_POS0/HOLE_POS/HOLE_MOUTH) 是某次运行的快照,
    与当前 env 配置差 3-6cm → 真实化**每轮现场采样几何**, 常量仅作展示
- site 实测 (当前进程): goal(-0.266,0.4452,0.1304)=obs[36:39]✓ /
  hole(-0.2,0.4452,0.1304) 孔口 / pegGrasp≈obs[4:7] / 销头朝 -x
- **endEffector site z=0.155 ≠ obs hand z=0.195** (夹爪中心 vs 腕部):
  YOLO 检的是夹爪 → R1 的 hand 语义 = 夹爪视觉位, 与 metaworld obs 腕部
  差 ~4cm 固定偏移 → 阶段证据/前馈目标必须同源, 不许混

### 3.4 夹爪与力觉
- metaworld 夹住 0.03m 销后 gripper 饱和 ~0.70 (cognition.py 注释已预警)
  → grasp_th 0.8 会卡死抓取阶段, R0/R1 标定到 ~0.65-0.7
- metaworld 无 6D 力传感器 → force_norm/触觉 4D 从几何合成
  (夹持状态 + 销头-孔口接触几何, 沿用 gen_tactile synth_tactile 思路)

## 4. obs 39D 语义决策 (关键)

两套 39D 段位冲突 (探针证实):
- 引擎语义 cur = [x(3),gripper(1),**v速度(3)**,peg(3),HOLE_POS(3),pad…] — 训练数据/左脑 MLP
- metaworld 语义 cur = [hand(3),gripper(1),peg(3),peg_quat(4),pad(7)] — YOLO align 输出

**但真正消费 39D 全段的只有训练 MLP**; 真实化闭环的消费方:
- 前馈解析律 u=Kp(target−pos) 只吃 [0:3]/[36:39] (相对量)
- 估计器 latent 4D 只吃位置; 状态机 advance 吃几何证据 (相对量)
- 阶段子目标 [36:39] 由调度器算 (pos/target 同源即可)

→ 推荐 D2: R1 显式用**解析前馈** (不挂引擎训练 MLP), obs 按引擎语义骨架
构造 ([0:3]=hand 视觉位, [4:7]=差分速度, [7:10]=peg 视觉位, [10:13]=现场
采样 goal, [36:39]=阶段子目标), 段位与训练分布兼容但**诚实标注前馈=解析律,
模型重训另立任务** (需要新世界数据采集, 防"引擎语义模型吃 metaworld 语义 obs")

## 5. R1 每步数据流 (真闭环)

```
[每 env step]
  ① 控制器旧指令 u_prev → 映射 act → env.step(act) → 真实物理推进
  ② 每 N 步 (N=1 起步): render() → YOLO detect_3d → {hand,peg,hole} 3D (视觉)
     中间步: 用上一感知值 + 估计器外推 (真机相机节流同构)
  ③ 构造 39D (hand=夹爪视觉位 / peg / goal 现场采样 / 差分 v) + 触觉 4D (几何合成)
  ④ fuse_sensors → 43D obs
  ⑤ 六层照跑: 前馈 u_ff → 估计 predict → 校正 → 调度 decide → 限幅 → u_prev (回 ①)
  ⑥ 阶段证据全从视觉/几何算: d_xy(hand-peg) / dist_h(peg头-孔口) / depth / lifted
  ⑦ 完成判定: 真值核对 (插深<阈值 & stage=完成)
```

成败验收: 成功率 R0 vs 引擎闭环 vs R1; 失败模式归因 (YOLO conf 掉/深度错/夹爪没夹住)

## 6. 落地形式 (推荐 D4)

- 新文件 `state_space_sim_real.py` (独立类 RealStateSpaceSim), **不动**现引擎默认路径
- 复用: perception/parallel/cognition/safety/execution 源码 importlib (同引擎)
- GUI 接入: ▶运行 旁新增「真实化运行」按钮/模式 (或右键菜单), 轨迹结构与
  现 io_trace 兼容 (3D/画布播放可复用), 不进默认 ▶运行
- 探针脚本 tools/probe_mw_real*.py 保留为标定工具

## 7. 风险与止损
- 大改隔离: 新文件新模式, 引擎闭环原样保留 (破坏性操作先留分支/验证)
- R1 慢: N=1 先验证正确性 (8min/轮可接受), 再调 N 和感知节流
- 控制器时间常数重标: 步频 50Hz→10Hz, EMA/confirm_n/限速按 audit 实测调
- metaworld 几何漂移: 每轮现场采样, 不允许写死

## D. 决策点 (请老倪拍板)
- D1: 先 R0 (秒级基线) 后 R1 (视觉), 两步走? (推荐: 是)
- D2: R1 前馈用解析律 (不挂引擎训练 MLP), 模型重训另立任务? (推荐: 是)
- D3: 感知刷新 N=1 起步验证? (推荐: 是, 成功后再调大)
- D4: 落地 = 新文件 state_space_sim_real.py + GUI 新模式, 不动默认 ▶运行? (推荐: 是)
