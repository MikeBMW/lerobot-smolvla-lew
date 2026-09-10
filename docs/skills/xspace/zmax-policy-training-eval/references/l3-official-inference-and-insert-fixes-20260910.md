# L3 官方管道验证 + 插入成功率修复集 (2026-09-10 实测)

姊妹文件: l4-lew-mamba-closedloop-20260910.md (LEW/Mamba 闭环诊断)、l34-joint-baseline-lessons.md
(32.1% 基线与失败模式分类)。本文件 = 基线之后的两项推进。

## 一、验证已训练策略必须走官方处理器管道 (否则误差虚高一倍)

- ❌ 直喂原始 tensor 给 `policy.select_action`: 动作误差 0.35 (假象)。
- ✅ 正确链路:
  ```python
  from lerobot.policies.factory import make_pre_post_processors
  pre, post = make_pre_post_processors(policy.config, pretrained_path=ckpt)
  item = ds[i]
  item["task"] = "metaworld 光模块插拔"        # ← 必须补字符串, 见下
  batch = pre({k: (v.unsqueeze(0) if hasattr(v, "unsqueeze") else v) for k, v in item.items()})
  act = policy.select_action(batch)
  act = post(act)                              # 反归一化
  ```
  同一 checkpoint 误差立刻 0.35 → 0.15。
- **`item["task"]` 必须是字符串**: LeRobotDataset 的 `task` 字段是 `task_index`(int);
  缺字符串时 `_prepare_model_inputs` 里 `instructions = list(tasks)` 抛
  `TypeError: 'int' object is not iterable` (源码里有缺省分支但只对 None/str 生效, int 会崩)。
- **诊断必须按阶段/按夹爪真值分组, 不能只看平均误差**: 实测
  | 帧类型 | 动作误差 |
  |---|---|
  | 移动/插入段 (gripper 真值 0) | 0.008 - 0.055 ✅ |
  | **抓取段 (gripper 真值 1.0, 预测 ≈0)** | **0.31 - 0.36 ❌** |
  → 结论: 模型数值回归学得好, **没学会"何时闭合夹爪"** = 裸 rollout 不抓的根因。
  平均误差 0.15 会把这个关键短板平均掉。

## 二、引擎插入成功率 32.1% → 46.4% (28 seed 同口径)

三项修复, 全在 `tools/gui/state_space_sim_real.py`:

1. **insert 步数上限 500 → 1000** (`run()` 的 `max_steps` 默认分支):
   深孔布局 (seed1 hole x=-0.242) 需多次"遇阻→回接近重抓", 每次重抓要重跑
   下降/抓取/抬起/转移 (~100 帧) → 500 步只够 2-3 次尝试。
   **seed1: 500 步失败 → 681 步 done=True**。
   判别信号: 失败 seed 全是整步超时, 且中途其实**插进去过** (min 3D 到孔底 0.4-0.5mm)。
2. **插入深处夹持误判回退** (`_gf` 夹持质量判据):
   原式 `|o[4:7] - x - off0| < 0.02` — peg 顶孔壁时相对夹爪位移可 >2cm 但并没掉 →
   `_gf=0` → 调度器判"夹持丢失"回退, **把已插到 0.4mm 的 peg 又拔出来** (seed1 实锤)。
   修: elif 分支加 `self.grasped and stage.startswith("插入") and depth < 0.03 → 1.0`。
3. **遇阻后按滑移量选回退目标**:
   原逻辑恒 `_retreat_then = 5` (回转移), 但遇阻时 peg 已在夹爪内滑
   (site-推算差 3.1 → 6.4 → 7.4mm 递增) → 用旧锁存回转移永远对不准。
   修: 算 `|site_xpos[_site_ph] - peg_head()|`, **>5mm → 回接近(0) 重抓刷新锁存**,
   ≤5mm 才回转移(5)。
   ⚠️ **别顺手把守卫 `INS_DEV_MM` 从 8mm 收紧到 3mm** — 实测误伤正常微滑, 连原本成功的
   seed6 也一起打成失败 (0/6), 已回滚。

结果: 13/28 = 46.4% (新增 seed 1/2/50 成功)。与"布局随机波动"同族 —
**单次对比需 ≥3 复测** (metaworld 每进程布局漂移 ±3.8cm)。

## 三、诊断脚本模式 (可复用)

- 阶段分布: `Counter(str(s) for s in tr["stage"])` + 末 5 阶段 → 区分"卡下降"vs"卡插入·接触"。
- 全局渐进: 每 N 帧打印 `离孔距离 / stage / u` → 看是"推不进"还是"插进去又被打断"。
- 孔位对比: 对比 seed 前**先打印双方 `sim.geom["hole"]` / `["goal"]`** (布局漂移可达 y 差 0.13)。
- ⚠️ `sim.sched` 在 `_reset()` 里构造, 不在 `__init__` — 访问阈值前先 `sim._reset(seed)`。
