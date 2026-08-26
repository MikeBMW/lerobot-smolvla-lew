# Z-MAX 状态空间数据空间（数据服务化定义）— 2026-08-20 静静 → web

> 老倪指示: 根据状态空间的数据层, 每层数据做成数据服务, 更新到新页面数据服务。
> 本文档 = 最新版 zmax 状态空间**每层数据的确切结构**, web 据此做数据服务页面。

## 〇、数据分层总览

状态空间 = 5 层数据, 每层 = 一个数据服务:

```
┌─────────────────────────────────────────────────────────┐
│ L1 感知层   39D 观测 (obs)        → /api/obs             │
│ L2 模型层   左脑4D动作草稿+右脑contact → /api/infer       │
│ L3 状态机层 6阶段状态+转移条件     → /api/state-machine   │
│ L4 动作层   调制后 4D 最终动作     → /api/action          │
│ L5 监督层   metrics+action_log    → /api/supervision     │
└─────────────────────────────────────────────────────────┘
```

## L1 感知层 · 39D 观测 (obs)

**来源**: metaworld/真机 传感器 → StateAdapter 归一化
**服务**: `GET /api/obs?robot=R3` → 当前 39D 观测

```json
{
  "robot": "R3", "ts": 1786405775.95,
  "obs_raw": [39个float],          // 原始观测 (单位见下)
  "obs_norm": [39个float],         // 归一化 (x_mean/x_std)
  "x_mean": [39个float], "x_std": [39个float]
}
```
**39D 字段表**:
| 索引 | 字段 | 单位 | 说明 |
|---|---|---|---|
| [0:3] | hand_pos | m | 末端位置 xyz |
| [3] | gripper | 0-1 | 夹爪开度 (0闭 1张) |
| [4:7] | peg_pos | m | 销钉位置 xyz |
| [7:11] | peg_quat | xyzw | 销钉四元数 |
| [11:18] | pad | 固定0 | 填充槽 |
| [18:21] | prev_hand | m | 上一帧末端 (⚠️与[0:3]重复) |
| [21] | prev_grip | 0-1 | 上一帧夹爪 |
| [22:25] | prev_peg | m | 上一帧销钉 |
| [25:29] | prev_quat | xyzw | 上一帧四元数 |
| [29:36] | prev_pad | 固定0 | 填充槽 |
| [36:39] | hole_pos | m | 插孔目标位 (goal) |

⚠️ **关键**: obs 无真实 peg 段 ([18:21] 是 hand 重复) → 真值须从 env.data.site_xpos 取

## L2 模型层 · 左脑动作草稿 + 右脑 contact

**来源**: left_right policy 推理
**服务**: `POST /api/infer` → {obs} → {act_draft, contact, next_obs_pred}

```json
{
  "robot": "R3", "ts": 1786405775.95,
  "act_draft": [4个float],        // 左脑 4D 动作草稿 [vx,vy,vz,gripper] (归一化前)
  "act_norm": [4个float],         // 归一化后 (模型输出)
  "contact": 0.787,               // 右脑接触概率 0-1
  "next_obs_pred": [39个float],   // 右脑世界模型预测下一帧
  "params": {"left": 547844, "right": 87336}  // 模型参数量
}
```

## L3 状态机层 · 6 阶段状态 + 转移条件

**来源**: node_logic.py (simulink 权威) / left_right _step_state_machine
**服务**: `GET /api/state-machine?robot=R3` → 当前阶段

```json
{
  "robot": "R3", "ts": 1786405775.95,
  "stage": "GRASP",              // APPROACH/ALIGN/DESCEND/GRASP/LIFT/TRANSFER/INSERT/DONE
  "stageIdx": 3,                 // 0-7
  "prev_stage": "DESCEND",
  "transitions": {               // 当前可转移条件 (达标情况)
    "grasp": {"d_hp": 0.032, "target": 0.06, "pass": true},
    "contact": {"v": 0.98, "target": 0.5, "pass": true}
  },
  "stages_total": 8
}
```

**6 阶段权威表** (simulink node_logic, 2026-08-12 老倪):
| 阶段 | 节点 | 关键参数 |
|---|---|---|
| 1 接近 | stage_approach | bias: act*0.3 + dir*2.0 |
| 2 抓取 | stage_grasp | effort: 0.6 |
| 3 抬起 | stage_lift | height: 0.08m, force: 0.8 |
| 4 转移 | stage_transfer | tolerance: 0.05m |
| 5 插入 | stage_insert | tolerance: 0.05m |
| 6 完成 | stage_done | stage: done |

**夹爪状态机**: open → grasp → hold → release (4 状态)

## L4 动作层 · 调制后 4D 最终动作

**来源**: _act_state_machine (每阶段调制)
**服务**: `GET /api/action?robot=R3` → 当前下发动作

```json
{
  "robot": "R3", "ts": 1786405775.95,
  "stage": "INSERT", "stageIdx": 6,
  "act_raw": [4个float],         // 左脑草稿 (调制前)
  "act_modulated": [4个float],   // 调制后 (最终下发, 归一化|act|max≤1)
  "modulation": "INSERT: act=[0,0,clip((hole_z-peg_z)*2,±0.6)]; grip=0.6",
  "clipped": false               // 是否触发幅值裁剪
}
```

## L5 监督层 · metrics + action_log

**来源**: _measure_metrics (P3, 2026-08-10 实现)
**服务**: `GET /api/supervision?robot=R3` + `POST /api/action-log`

```json
// 实时指标 (当前阶段)
{
  "robot": "R3", "ts": 1786405775.95,
  "stage": "INSERT", "stageIdx": 6,
  "metrics": [
    {"k": "d_ph", "name": "插入距离", "v": 48.37, "unit": "mm", "target": 50, "pass": true},
    {"k": "f_ins", "name": "插入力", "v": 0.6, "unit": "", "target": 0.6, "pass": true}
  ],
  "pass": true
}
// 历史留痕 (阶段变化时 POST)
{
  "robot": "R3", "ts": 1786405943.79, "stage": "TRANSFER", "stageIdx": 5,
  "metrics": [...], "pass": false, "done": true
}
```

**8 阶段指标模板** (web 前端预置 STAGE_METRICS):
| 阶段 | 指标 |
|---|---|
| APPROACH | d_hp 收敛距离 ≤0.06m · contact ≤1.5s |
| ALIGN | e_xy 对位误差 ≤0.5mm |
| DESCEND | e_z 到位精度 ≤0.2mm · v_desc ≤0.5m/s |
| GRASP | contact >0.5 · grip_f 0.6±0.05 · 抓取成功 |
| LIFT | dz 抬升 +8cm±2mm · t_lift ≤0.5s |
| TRANSFER | t_xfer ≤2s · e_xy2 ≤5mm · v_profile 分级正确 |
| INSERT | d_ins 到位±0.1mm · f_ins ≤力阈值 · done |
| DONE | hold 无漂移 · t_done 按工艺 |

## 数据服务页面建议 (web 新页面)

```
新页面: /data-services.html (数据服务总览)
┌─────────────────────────────────────┐
│ L1 感知  │ 实时39D观测波形/表格       │
│ L2 模型  │ 左脑动作草稿+contact 曲线  │
│ L3 状态机│ 当前阶段+转移条件灯         │
│ L4 动作  │ 调制前后动作对比+裁剪标记   │
│ L5 监督  │ 指标达标灯+action_log时间线 │
└─────────────────────────────────────┘
每层: 实时值 + 历史曲线 + 服务端点说明
```

## 关联文件
- 状态空间权威定义: docs/simulink状态空间权威定义.md
- left_right 技术方案: docs/left_right_policy.md
- 大屏监督方案: docs/factory_fine_ops_supervision.md
- 模型侧实现: src/lerobot/policies/left_right/modeling_left_right.py (select_action/_measure_metrics)
