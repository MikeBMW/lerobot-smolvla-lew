# metaworld peg-insert-side-v3 契约知识库 (2026-09-04 三进程 12 探针实测)

gui-venv311 环境: metaworld + mujoco (mujoco 版本: site(i).name 可用但 site_id2name/body_xpos/geom_xmat 不可用)。
构造: `MT1("peg-insert-side-v3").train_classes["peg-insert-side-v3"](render_mode="rgb_array", camera_name="corner2")`,
`set_task(train_tasks[0])`。渲染 corner2 480×480, 0.14s/帧; env.step 无渲染 <1ms; import+构造 ~0.8s。

## 数值表 (某进程 seed0 实测; 布局跨进程漂移, 只当量级参考)
| 量 | 值 | 说明 |
|---|---|---|
| obs[0:3] hand (腕部=真实夹爪) | 初始 (0.0046,0.6014,0.1951) | **控制锚**; claw geom 同高 |
| endEffector site | 腕下 4.0cm | **虚拟视觉点**, 非夹爪 (探针12 空夹根因) |
| obs[4:7] peg | z≈0.0248-0.03 | 销位置 (实时读它, 别缓存) |
| peg geom | 0.1kg free body, 世界半尺寸 [0.12,0.015,0.015] (沿 x 躺 24cm, 3cm×3cm 截面) | 底面嵌桌面 ~0.3mm |
| 夹爪两指 | 沿 y 开合 (claw/pad geom 各 9cm×6mm×3cm), 全开指间距 ~9cm, grp 0 全闭 ~3cm | 销 3cm 宽恰好填指间 |
| 抓握位形 | hand_z 降到 peg_z+0.02 即被销顶住 (指已包销身上部) | at_grasp_pose 几何判据 |
| 夹持 | grp 从 0.998 闭合: ~0.66 开始接触, 深夹 0.28-0.30; 空夹也收敛 ~0.29 | grp 无法区分 → 抬升 peg 随动验证 |
| action | ±1 目标位移, 伺服 ramp; act=1.0 连续步 1→2.7→4.4→…mm, 10 步累积 64mm | 稳态 ~9mm/步 |
| 位移↔速度指令 | 位移 ≈ u(m/s)×0.018-0.02s | 估计器/动力学 B=0.02 标定 |
| max_path_length | 500 步硬上限 | truncate 后 step 抛 ValueError |
| 接触 | reset 后静止 peg↔桌体 g3 4 接触常驻 (peg 贴桌面) | **别当夹持证据** (探针10 误读教训) |

## 调试用 site/geom id
- site: endEffector / leftEndEffector / rightEndEffector / pegGrasp / pegHead / pegEnd / hole / goal
- geom: peg / rail / rightclaw_it / leftclaw_it / rightpad_geom / leftpad_geom; 桌体是空名 geom
- goal site = obs[36:39]; hole site 是孔口 (比 goal 浅 ~6.6cm x); pegHead = 销头 (插入端, -x 向)

## mujoco python API 兼容 (本机版本)
- `m.site(name).id` / `m.geom(name).id` / `m.site(i).name` 可用
- `m.site_id2name` / `m.body_xpos` / `m.geom_xmat` **不存在** → 用 `m.geom_quat[gid]` + quat2mat;
  body 世界位置用 `d.xpos[body_id]`, geom 世界位置用 `d.geom_xpos[gid]`
- geom size 是局部半尺寸, 世界尺寸 = quat 旋转后 (peg [0.015,0.015,0.12] → 世界 [0.12,0.015,0.015])
- 接触遍历: `d.contact[:d.ncon]`, geom 名 `m.geom(c.geom1).name or f"g{...}"`

## 方法论: 探针先行, 控制器后写
12 发探针 (probe_mw_real1-12) 顺序: ①obs 段位/action 尺度/相机 ②site 几何/累积位移 ③freeze 时序/大步收敛
④site API/夹爪闭合 ⑤指端 vs 销几何 (发现逼近撞销) ⑥R0 式抓取几何 ⑦夹持窗口扫描 ⑧geom 尺寸/接触对
⑨闭合力度×抬升力度 ⑩抬升接触时序 (误判 peg 贴桌面=夹持) ⑪y 补偿 ⑫**正确锚 (obs hand) → 抓取成功**。
教训: 控制器写代码前先把 env 契约用探针钉死; 接触对/几何读数比 obs 值更接近真相; "夹住了"必须有
抬升随动证据, 不能只看接触对数量。

## R0 控制器参数标定 (state_space_sim_real.py)
- act[:3] = clip(u_vec[:3]/0.5, -1, 1); act[3] = 0.6 闭合 / -1.0 张开
- est/dyn B = 0.02; sched grasp_th=0.40 (grp<0.60), align_th=0.025, insert_depth=0.006,
  lift_h=0.08, max_veto=5; 插入阶段 v_min=0.02 (追加)
- 锁存: 抓取阶段 grp<0.82 计数, close_steps≥3 且 grp<0.60 → grasped 锁存 + 记录 peg_off0/gap_z
- 随动验证 gf: |obs[4:7] − x − peg_off0| < 0.02; 超 0.035 判滑脱 → 强制 sched._goto(0) 回退
- 阶段目标: 夹持前 = 实时 peg + 高度偏移; 抬起 = x.xy 保持 + z 抬到 peg_z0+0.16+gap_z;
  转移/插入 = hole/goal − (peg_head − x) (实时销头偏移)
- STAGE_V_CAP 速度上限是按引擎 0.5m/s 语义设的, metaworld 物理上限 ~0.09m/s@act1 → 阶段限速需按新世界重标
