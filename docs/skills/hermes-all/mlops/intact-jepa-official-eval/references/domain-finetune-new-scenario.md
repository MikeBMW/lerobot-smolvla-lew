# 用 INTACT 架构+模型适配新场景 (域内微调) — 2026-09-13 光模块插拔

约束口径 (老倪): **除新生成的数据外, 任何代码/接口都不动, 只是用新数据**。
目标交付物 = 在状态空间工程里看到 INTACT 真驱动新场景并**成功**完成的视频 (类比 stable-world 抓方块)。

## 1. 训练契约 (只加配置, 不改代码)
- 数据配置 `config/train/data/<task>.yaml`:
  `dataset: {num_steps: ${num_frames}, frameskip: N, name: <file>.h5, keys_to_load/cache: [pixels, action, observation]}`
  - `frameskip` 决定 action_dim = frameskip × 单步动作维 (pusht: 5×2=10; 本域: 2×4=8)
  - `pixels`=224² RGB uint8 (HWC), `action`=**实际下发的 env 级动作** (因果: 它造成该转移),
    `observation`=env 原生观测 (诊断列, 不进 JEPA 输入)
- 模型配置 `config/train/intact_goal_<domain>.yaml`: `init_weights_path` + `init_strict: false`
  (动作维不同必须部分加载), `intent_mode: goal_displacement`, Lightning `max_epochs/bf16-mixed`
- goal **不需要数据列**: 训练内部按 `goal_start` 从轨迹自身取 (goal_displacement), 所以数据侧只提供
  轨迹本身 + ep 元数据 (`ep_len`/`ep_offset`/`ep_idx`/`step_idx`)。

## 2. 🔴 失败模式 (v2 实测, 必须先绕开)
长回合 (500~600 步) 直接微调 → 离线判闸 MAE 0.1122→0.0968→0.0974 **vs 常数基线 0.0993**,
预测 std 只有真值的 **1/16** ⇒ 塌到均值。三个结构性根因:
1. **回合长度与论文契约不符**: 论文任务 50 步, goal_displacement 取 +25 步 ≈ 接近目标;
   长回合里 +25 步几乎同状态 → goal 监督信号失效。
2. **动作分布被"小接近动作"主导**: 大量微小动作 + 稀疏插入大动作 → 回归均值即最优。
3. **相位覆盖窄**: 关键相位 (对位/插入) 样本占比太低。

## 3. v3 数据配方 (短回合窗口 + 专家口径)
- 用既有引擎真链路采真轨迹 → **切 50 步短窗口**, 窗口**结束于任务完成帧**附近
  (往回退 0/15/30/45 步各切一条), 使 goal(+25 步) 落在动作富集相位 → 与论文契约同构。
- **专家口径**: `--success-only` 只留成功回合窗口 (对齐官方 `*_single_expert` 数据集语义);
  失败回合不切窗 (如实统计 skip 数)。
- **提高成功率**: 引擎 `run(max_steps, cap="l4")` = 自主恢复档 (失败回退/重抓不放弃, 预算×2)。
  实测: 不带 cap 时 done_rate 只有 0.36, 且失败回合窗口停在「接近/对位」= 没价值;
  带 cap=l4 后成功占比 ~95%。
- 元数据留档 (只进 meta, 不进训练列): 引擎阶段名序列 (`sim.sched.stage()`)、每回合 done、
  每回合帧 std (>5 判真图)、来源/时间。

## 4. 引擎事实 (Z-MAX 六层真链路, tools/gui/state_space_sim_real.py)
- `RealStateSpaceSim(log, seed, vision, vision_every, mode, demo_l4, mani_yaw)`; `mode ∈ {insert, full}`;
  `run(max_steps=None, cap=None)`; 逐帧钩子 `sim._frame_sink(sim, act, o)` (每步调用, 可读 `sim.sched.stage()`)。
- 阶段名 (切窗/统计靠它): 接近 / 对位 / 下降 / 抓取 / 抬起 / 转移 / 插入 / 拔出 / AOI转移 / AOI检测 / 回程 / 放下 / 完成。
- 实测速率 (本机 4060): mode=insert 约 3.3~8.8 s/回合 (max_steps 700~1600); mode=full 常跑满步数
  仍停在「下降」→ **不要用 full 采插入数据**。
- 数据管线: 构造器只落 `.npz` parts (内存闸 20k 帧/块, 防 OOM; 引擎 venv 无 h5py) →
  `tools/intact_parts_to_h5.py` (INTACT venv, 有 h5py) 转官方 h5。**采集与写 h5 分两个 venv 是刻意的。**

## 5. 判闸三段 (不过不上闭环, 不许把"链路跑通"说成"学会")
1. **离线**: 逐帧 MAE vs **常数基线** (需显著更低) + 预测 std / 真值 std 比值 (v2 = 1/16 ⇒ 塌缩,
   健康值经验阈 > 0.5); 不达标就调 (冻结编码器只训动作头 / lr×0.3 / 关键相位加权) 再判。
2. **闭环**: 引擎真物理 rollout, 用既有 `install_direct_act` 直驱 (L4 档把控制权交给 INTACT:
   模型动作 → env.step, 唯一变换 a_raw = z·std + mean) → 任务成功率 > 0 且可复现。
3. **视频**: 引擎真渲染视频 + 状态空间 SW 实况窗口可见; 帧 std>5 自检 (真图, 不是黑帧/占位)。

## 6. 复用清单
- 采集脚本模式: `tools/intact_insert_dataset_v3.py` (新文件, 不动任何既有代码/接口)。
- 判闸"同口径对照"铁律: 任何"有提升"的结论必须有常数基线 + 同口径对照 (老倪红线)。
