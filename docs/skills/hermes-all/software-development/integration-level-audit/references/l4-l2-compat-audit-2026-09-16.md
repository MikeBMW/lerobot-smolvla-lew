# L4 档「L2 兼容」审计实录 (2026-09-16)

老倪: 「为什么运行 L4 功能, YOLO 未启动呢? L2 功能应该和 L4 功能兼容, 运行 L4 的时候 L2 也可以运行;
也要连线。按三步做: L4 档接线 (档位内生效, 默认值不动) + 同口径 A/B 取证 + 结果落档, 然后才谈要不要进默认档。」

## 一、两处真因 (都不是能力不足, 是接线没接)

| 症状 | 代码位置 | 要点 |
|---|---|---|
| 日志恒打「YOLO 未启动」 | `tools/gui/simulink_module.py` L4 装配处 `vision=(str(_cap).upper() == "L3") and (not _model_exec)` | vision 只给 L3 档; 引擎 `state_space_sim_real.py` 的日志分支 `if _v.get("shot") ... else "YOLO 未启动"` 就是判别信号 (`shot` 只在本帧真跑 `detect_3d` 时累加)。同处注释写着历史原因: R1 每帧 YOLO 要 5-9 分钟/轮 |
| 类真身 0 次进入, 且 **n_guard 也是 0** | `state_space_sim_real.py` 装配期 `else: self.accel.forward = self.accel.analytic_forward` | 实例属性遮蔽类方法 (`parallel.py` 的 `def forward`)。**n_guard=0 ⇒ 不是 D_GUARD/DOMAIN_SIGMA 域判定挡的** (域判定代码在真身体内, body 没进就不走) |

第三类旁路: 插入段硬调 `analytic_forward` (分层伺服设计) · L4 直驱用模型动作 `env.step`, `u_ff` 只喂
阶段标签/gripper/skill_ctx ⇒ u_ff 不在 L4 执行出口上。

取证脚本 `tools/diag_ff_entry.py` (两臂, 32 步):
```
臂A (不设 SS_USE_MLP): 实例覆盖=True · acc.forward→analytic_forward · 真身 0 次 · n_mlp=0 · n_guard=0
臂B (SS_USE_MLP=1)   : 覆盖=False · acc.forward→forward(真身) · 真身 32 次 · n_mlp=32 · n_guard=0
                       域判定真值 d_guard 0.131~0.178 (门 0.25, 0/32 超门) · max|xn| 1.583 (门 4.0, 0/32 超门)
```

## 二、接线 (档位内生效, 全局默认值不动)

`simulink_module.py` L4 装配处新增: 仅 **L4 + 引擎路径** (勾 🤖INTACT 节点执行 / 🧠模型执行) 时
`SS_USE_MLP=1` + `vision=True` (vision_every=1); L4 纯演示档走 L4Demo 独立链不碰; 非 L4 档 `pop` 回原状。
开关 `SS_L4_L2_COMPAT=1` (**默认关**, 见结论)。

## 三、同口径 A/B (同解释器 gui-venv311 · 同 seed 104 · 120 步 · cap=l4 · 每臂独立进程)

| 判据 | 臂A (L4 现状) | 臂B (L4+L2 兼容) |
|---|---|---|
| 装配期覆盖 forward | True | False |
| MLP 真身进入 | 0 | **120/120 帧** |
| n_guard | 0 | 0 (域内, 无兜底) |
| YOLO 出帧 / 检出 | 0 / 0 (「YOLO 未启动」) | **120 / 240 (100%)** |
| 日志样例行 | `[100/120] … · YOLO 未启动` | `[100/120] … · YOLO 检出率 202/202 (100%)` |
| 最小距离 | **0.13mm** | 2.77mm |
| 终点距离 | **0.42mm** | **6.82mm (16× 回退)** |
| 墙钟 (120 步) | 3.3s | 6.9s (2.1×) |

复现: `tools/ab_l4_l2_compat.py` — `./gui-venv311/bin/python tools/ab_l4_l2_compat.py A 120`
(臂B 加 `SS_USE_MLP=1`, 脚本内部 `vision=(ARM=="B")`)。

## 四、结论 (诚实)

1. **接线成功且可验证** (真身 120/120 帧 + YOLO 240/240 检出), 但**没有提升, 是精度回退 16×** ⇒ 开关默认关
   (未证明提升不进默认档), 打开时日志明写代价。
2. 回退两个来源: (a) `vision=True` 用 **YOLO 检测值替换 R0 真值** → 2D→3D 检测误差直接进 obs;
   (b) 蒸馏 MLP 在 seed104 布局处于训练分布边缘 (代码注释早已标注), 每帧主导 u_ff。
3. 折中选项 (待拍板): L2 感知在 L4 里**只做校验不下发** (YOLO 结果做一致性比对/告警, 不替换真值)。

## 五、附带环境事实

`ultralytics` 只装在 **gui-venv311** (8.4.126), `~/lerobot-venv` 没有 → 任何 `vision=True` 的引擎跑法
(含 on_infer/on_eval 里走 lerobot-venv 的路径) 会 `ModuleNotFoundError: ultralytics`; **A/B 两臂必须同解释器**
(首轮臂A 用 lerobot-venv 跑完、臂B 直接炸)。

## 六、画布连线 (同会话)

`flows/state_space_obs.json` 文本级插入 2 条: `sssensor → ssintact (in2)` · `ssff → ssintact (in3)`,
节点 77 不变 · 连线 95→97 · 旧连线 0 条变化; `ssintact` desc 补"三路入线口径"。
画布代价 (同工具改前/改后): 反向 2→4 · 重叠 0→0 · 穿框 44→45 · 交叉 145→161 (两条新边天生反向,
L2 行在画布右侧而 L4 行在左侧)。零回退: 档位归属不变 · 执行集 55/60/77 逐项不变 · 旧连线 0 丢失。
