# metaworld peg-insert-side-v3 控制契约 (2026-09-04 R0 真实化 12 发探针实测)

来源: tools/probes_real/probe_mw_real*.py (保留为标定工具) + tools/gui/state_space_sim_real.py。
gui-venv311 环境, DISPLAY=:0, MUJOCO_GL=glfw。这些数字都是实测, 不是文档抄的。

## ⚠️ 控制锚: obs[0:3] hand, 不是 endEffector site (最大坑, 空夹根因)
- obs[0:3] hand = 腕部 body = **真实夹爪 claw geom 位置** (z≈0.195 初始)。
- `site("endEffector")` 是腕下 **4cm 虚拟视觉点** (z≈0.155), 非夹持件!
  用 site 当锚降到销身高度时, 真实夹爪还悬空 2-3.5cm → 永远空夹。
- 探针12 实证: hand 引导到 peg 上方 (hand_z ≈ peg_z+0.02, 被销顶住, 指已包住销上部),
  闭合 grp 0.66 接触建立 → 抬升 peg 随动 = 夹住。gen_insert_video 也用 obs hand 当手。
- 判别口诀: 控制/观测用 obs 段位; site 只是视觉/参考标记。接触实验务必查 contact 对里
  的 geom 名 — "peg 接触 4 点" 曾全是 **peg 贴桌面** (桌体 geom 无名 vs peg), 误读成夹持。

## gripper 语义 (与引擎简化世界相反!)
- obs[3] gripper: **1=全开, 0=全闭** (引擎语义是 0=开 1=闭, 别混)。
- 空夹(无物)全闭收敛 ≈0.29; 夹住 3cm 销接触建立 ≈0.66-0.70 (cognition.py 注释 0.70 对);
  深夹可到 0.28。**单看 gripper 分不清夹住/空夹** (都收敛 0.3 附近) → 夹持判定靠
  "抬起时 peg 随动" (夹住: peg 相对夹爪偏移不变; 空夹: peg 不动, 偏移漂移 → 判滑脱回退)。
- 夹爪动作: act[3] = 0.6-1.0 闭合 (gen_insert_video 用 0.6 防夹死), -1.0 张开。
  夹爪一阶收敛慢: 闭合 ~10 步到 0.7, ~20 步到 0.3 — 抓取阶段停留要给足步数。

## 动作映射与时间尺度 (引擎速度指令 → metaworld action)
- metaworld act[:3] = **目标位移增量** (±1 → ~10mm 目标/步), 伺服 ramp 收敛:
  act=1.0 连续 10 步累积 64mm, 稳态 ~9mm/步。≈ 引擎 0.5m/s×0.02s=10mm/步 (巧合对齐)。
- 实测映射: act = clip(u_vec[:3] / K_ACT, -1, 1), K_ACT=0.5 起步 (u 是 m/s 速度指令)。
  比例逼近控制 act = dv/0.03 clip ±1 收敛到 ±0.4mm (探针实测), 比引擎 v_min 逻辑更直接。
- **估计器/动力学 B 增益标定 0.02**: B=0.1 (≈1 env step 物理时长) 预测过冲 5 倍 →
  残差 0.5 级爆发 → contact_p σ(8r) 误判接触 (夹爪离销 20cm 就"接触") → 卡死循环。
  实测每步位移 ≈ 速度指令 × 0.018-0.02s。
- env.step 无渲染 <1ms; render 480×480 = 0.14s; +YOLO 检测+深度 ≈ 0.3-1s (R1 预算)。

## 几何与随机化
- **布局跨进程漂移 >10cm**: 同进程内 freeze 后 seed0 稳定; 不同进程 peg/goal 位置不同
  (探针 3 进程 peg y: 0.58/0.67/0.69/0.52 全不同)。→ 几何**每轮现场采样** (obs 段位 +
  site xpos), 不许写死常量。引擎注释里的 pegGrasp/hole 坐标只是某次快照, 差 3-6cm。
- 任务结构固定: 销沿 x 平躺 24cm (geom size [0.015,0.015,0.12] 局部, 世界=[0.12,0.015,0.015]),
  截面 3×3cm; 孔/终点在 -x 侧; peg 0.1kg free body, 底嵌入桌面 0.3mm (桌面顶 z=0)。
- 夹爪沿 **y 开合** (两指全开 y 距 ~9cm, 全闭 ~3cm = 机械限位), 夹 3cm 宽销刚好过盈。
- 闭合后两指中心漂移 +5mm (结构不对称) → y 目标补偿 -5mm 让闭合中心对准销。
- site 名: goal/hole/pegGrasp/pegHead/pegEnd/endEffector/leftEndEffector/rightEndEffector
  (m.site(name).id + d.site_xpos 可取世界位; pegHead z 比 pegGrasp 低 1cm = 销头)。
- obs 段位 (metaworld 语义, 与 node_obs39 文档一致): [0:3]hand [3]gripper [4:7]peg
  [7:11]peg_quat [11:18]pad [18:21]prev_hand [36:39]goal=site goal ✓ (孔深处, 非孔口;
  hole site = 孔口, 比 goal x 大 ~6-8cm)。

## env API 坑
- **单轮硬上限 max_path_length=500 步**, 到顶 env.step 抛 ValueError("truncate") →
  必须手动 reset; 未完成轮 = 截断 (try/except 捕获结束本轮)。
- 随机化冻结: env.reset(seed=s) 后 env._freeze_rand_vec = True; 同进程二次 reset 一致。
  ⚠️ 8 个不同 seed 跑出全同轨迹 (seed 参数疑似未影响布局) — 多 seed 统计前先验证布局真变了。
- mujoco API 版本差异: model.site_id2name / data.body_xpos / model.geom_xmat **不存在**
  → 用 model.site(name).id / d.site_xpos / d.geom_xpos / m.geom_quat+手写 quat2mat;
  model.geom(i).name 可枚举; 无名 geom 用 m.geom(c.geom1).name or f"g{id}" 兜底。
- 抓取完整序列 (验证可行): 悬停(z=销+8cm)水平对准 → 垂直降 (hand 到销身, 被销顶住) →
  闭合 20-30 步 (grp<0.7) → 抬升 act z 0.4-0.5 (peg 随动 Δz>3cm = 夹住; 不随 → 回退重抓)。
- 接触力合成 (metaworld 无力传感器): 未夹持=夹爪到销上方 gap_z 判据; 夹持=销头-孔口
  距离 <D_CONTACT。合成力只用于残差/接触概率, 夹持真伪靠 peg 随动。

## R0 实现要点 (state_space_sim_real.py)
- 几何每轮 _reset 现场采样存 self.geom; 阶段机每轮新建 ActionModulator
  (grasp_th=0.28 / lift_h=0.08 / max_veto=5; 阈值按 metaworld 实测, 引擎默认值会卡)。
- 夹持: 抓取阶段 grp<0.78 连续 3 步锁存"闭合候选" → 抬起阶段 peg 随动验证 (gf),
  滑脱置 grasped=False → 调度器 advance 夹持丢失回退 (grasp_force<0.05 连续5帧+peg落回)。
- 单轮全流程跑通 (seed 100): 八阶段完成, 真夹持 gf=1。遗留: 多轮 0/8 (布局敏感)。
- 引擎语义 39D 与 metaworld 39D 段位冲突 ([4:7]=v vs peg) — 前馈解析律只吃 [0:3]/[36:39]
  相对量不受影响; 挂训练 MLP 前必须统一语义 (R1 决策点)。
