# L4 档「L2 兼容」接线与取证 (v5.6.8 补丁, 2026-09-16 09:05)

老倪: 「运行 L4 功能, YOLO 未启动呢? L2 功能应该和 L4 功能兼容, 运行 L4 的时候 L2 也可以运行; 也要连线」

## 一、真因 (两处, 都定位到行)

### ① YOLO 未启动 (你贴的日志行)
`tools/gui/simulink_module.py:11471` (装配 L4 时):
```python
vision=(str(_cap or "").upper() == "L3") and (not _model_exec)
```
→ **vision 只给 L3 档**; L4 档 vision=False ⇒ `state_space_sim_real.py:3503` 的日志分支
`if _v.get("shot") ... else "YOLO 未启动"` 恒取后者 (shot 只在本帧真跑 detect_3d 时累加)。
历史原因写在同处注释里: 「R1 每帧 YOLO 要 5-9 分钟/轮, 太慢看不清完整插→拔→AOI 链」。

### ② 前馈 MLP 真身永不进入
`tools/gui/state_space_sim_real.py:399`:
```python
else: self.accel.forward = self.accel.analytic_forward   # 实例属性遮蔽类方法
```
→ 不设 `SS_USE_MLP=1` 时, `parallel.py:143` 的 `def forward` **一次都不进** (n_mlp=0 **且** n_guard=0,
即 `D_GUARD/DOMAIN_SIGMA` 那条域判定根本没被执行 —— 所以不是"被域判定挡了")。
L4 另有两条旁路: 插入段硬调 `analytic_forward` (:2584, 分层伺服设计) ｜ L4 直驱用模型动作做 env.step,
u_ff 只取阶段标签/gripper/skill_ctx。

## 二、接线 (档位内生效, 全局默认不动)

`simulink_module.py` L4 装配处新增 (只在 **L4 + 引擎路径** 生效; L4 纯演示档走 L4Demo 独立链不动;
非 L4 档 pop 回原状):
- `SS_USE_MLP=1` → 前馈蒸馏 MLP 真身进 forward (L2 执行层)
- `vision=True` (vision_every=1) → R1 真实视觉链 (YOLO→2D→3D→融合) 在 L4 同档运行
- 开关: `SS_L4_L2_COMPAT=1` 打开 / 默认关

**连线 (画布)**: `flows/state_space_obs.json` 文本级插入 2 条 (节点 77 不变 · 连线 95→97 ·
旧连线逐字段 0 变化):
- `📡 传感器融合 → 🎯 INTACT 策略 (L4)`  t_port=in2  ↩ L2 融合状态 39D
- `⚡ 前馈加速器 → 🎯 INTACT 策略 (L4)`  t_port=in3  ↩ L2 前馈 MLP u_ff
- `ssintact` 的 desc 补"三路入线口径" (in1 数据源 / in2 L2 感知 / in3 L2 执行) = 自解释

## 三、同口径 A/B (同解释器 gui-venv311 · 同 seed 104 · 同步数 120 · cap=l4 · 每臂独立进程)

| 判据 | 臂A (L4 现状) | 臂B (L4 + L2 兼容) |
|---|---|---|
| vision | False | True |
| SS_USE_MLP | (不设) | 1 |
| 装配期覆盖 forward | **True** (真身被替换) | False |
| MLP 真身进入 | **0** | **120 / 120 帧** |
| n_guard (域外兜底) | 0 | 0 (域内, 无兜底) |
| YOLO 出帧 / 检出 | 0 / 0 (**"YOLO 未启动"**) | **120 / 240 (100%)** |
| 日志样例行 | `[100/120] … · YOLO 未启动` | `[100/120] … · YOLO 检出率 202/202 (100%)` |
| 最小距离 | **0.13mm** | 2.77mm |
| 终点距离 | **0.42mm** | **6.82mm (16×)** |
| 墙钟 (120 步) | 3.3s | 6.9s (2.1×) |

复现命令:
```
# 臂A
./gui-venv311/bin/python tools/ab_l4_l2_compat.py A 120
# 臂B
SS_USE_MLP=1 ./gui-venv311/bin/python tools/ab_l4_l2_compat.py B 120
```

## 四、结论 (诚实)

1. **接线成功且可验证**: L2 的前馈 MLP 每帧真身进入 (120/120, 域判定 0 次兜底) + YOLO 每帧真检出
   (240/240, 100%), 日志从"YOLO 未启动"变为真实检出率 —— 这就是你要的"L4 时 L2 也在运行"。
2. **但没有提升, 是精度回退**: 终点距离 0.42 → 6.82mm (16×), 最小距离 0.13 → 2.77mm。
   两个可解释来源: (a) vision=True 后引擎用 **YOLO 检测值**替换 R0 真值 → 2D→3D 检测误差直接进 obs;
   (b) MLP 在种子 104 布局下处于训练分布边缘 (代码注释早已标注该已知问题), 每帧主导 u_ff。
3. **因此按门槛不进默认档** (未证明提升不得进默认档): 开关默认关 `SS_L4_L2_COMPAT=1` 才开, 打开时日志
   明写代价。要不要进默认档, 得先解决上面 (a)(b) 两条, 或改成"感知只做校验不替换真值"。

## 五、画布代价 (同工具改前/改后)

`tools/verify_l4_layout.py` (真画布, 同基线对比):
| 指标 | 改前 | 改后 |
|---|---|---|
| 反向连线 | 2 | 4 (+2 = 本次两条, 均标 ↩) |
| 方框重叠 | 0 | 0 |
| 连线穿框 | 44 | 45 |
| 连线交叉 | 145 | 161 (+16) |

原因: L2 行位于画布右侧 (前馈 x≈3826), L4 行在左侧 (x=387) → 这两条天生反向 (与既有
SK04-08→执行器 5 条反向同源)。结构性修法 = 把 L2 行/执行器位置按"右出左入"重排 (下一轮)。
`tools/verify_l4_zero_regression.py`: 档位归属无变化 · L2/L3/L4 执行集 55/60/77 逐项不变 · 旧连线 0 丢失 ✅

## 六、附带发现 (环境)

`ultralytics` 只在 **gui-venv311** (8.4.126), 不在 `~/lerobot-venv` → 任何带 vision=True 的引擎跑法
(含 on_infer/on_eval 里的 lerobot-venv 路径) 会 `ModuleNotFoundError: ultralytics`。GUI 本身跑
gui-venv311 所以 L3 档一直没事; 跑 A/B 必须用 gui-venv311。
