# Z-MAX · INTACT 节点设计 (L4 层) — 2026-09-11

> 目标: 在状态空间画布 **L4 层**新增「🧠 INTACT 意图-动作」节点, 把
> [zju3dv/INTACT-JEPA](https://github.com/zju3dv/INTACT-JEPA) (INTACT: Isomorphic
> Intent-to-Action Learning for Search-Free World Models, MIT) 的能力**完全封装在节点内**:
> 输入走数据源层 (数据可再下载), 输出直接接机器人硬件 (预留接口), 先调试通, 再适配到当前 L4 层。

## 1. INTACT 是什么 (读源码结论, 不是转述)

| 组件 | 文件 | 作用 |
|---|---|---|
| `JEPA` | `jepa.py` | 前向世界模型 + **共享 local/goal 动作律**; `encode() / predict() / goal_intent() / action_mean()` |
| `IntentActionActor` | `module.py` | **核心**: 同一算子吃 local intent (观测到的物理变化 m_t) 与 goal intent (部署期可用的目标), 显式四槽语法 `[z, m_t, z⊙m_t, A(a_{t-1})]` → 输出动作分布 (mean, log_std) |
| `ARPredictor` | `module.py` | LeWM 式**自回归潜空间预测器** (AdaLN 条件化) |
| `DirectSolver` | `direct_solver.py` | **零搜索控制器**: 直接取 `action_mean()`, `get_cost_calls=0`, `candidate_sequences=0` (可选 guarded 局部 CEM 128×3) |
| 训练 | `train.py` + `config/train/intact_goal.yaml` | 1 epoch, bf16, `intent_mode=goal_displacement`, 损失 = forward(1.0) + SIGReg(0.02) + intent(local 0.1 / goal 0.05) —— **local/goal 上游梯度路径故意不对称** |

**关键差异 (为什么值得接)**: 常规做法是"世界模型 + 采样搜索(CEM 300×30)"; INTACT 把目标意图直接
映射成**动作律**, 部署期**不做候选搜索**——省掉的正是我们引擎里最长的那条链。

## 2. 部署契约 (节点接口的硬边界, 来自 `JEPA.get_action`)

输入 `info`:
| key | 形状 | 说明 |
|---|---|---|
| `pixels` | `[B,T,C,H,W]` | 观测帧序列 (官方 224×224, history_size=3, num_frames=8) |
| `goal` | `[B,C,H,W]` | **目标帧**; `goal_*` 前缀键会被改写成对应字段 (waypoint 模式用坐标) |
| `action` | `[B,T,D]` | **动作历史** (reset 时必须是 **raw 零**, 在 normalizer 之前) —— `_coerce_action_history` |
| (其它张量键) | — | 透传给 `encode()` (proprio 等) |

输出: `get_action(info, horizon=H) → [B,H,D]` action chunk (**零搜索**, 内部 `horizon` 次前向)。
诊断: `last_direct_diagnostics = {intent_norm, terminal_latent_error, forward_calls=H, candidate_sequences=0}`。

## 3. 节点设计 (4 个对外接口, 内部全封装)

```
        ┌──────────────────── 🧠 INTACT 意图-动作 (L4) ─────────────────────┐
数据源层 │ set_source(src)  ─► clips[(obs, goal, action, proprio)]            │
         │ set_goal(frame|waypoint) ─► goal 帧/坐标                           │
         │ step(obs)  ─► JEPA.get_action(info, H)  ─► action chunk[H,D]        │
         │ attach_robot(io) ─► RobotIO.send_chunk(chunk)  ← 硬件预留接口       │
         └───────────────────────────────────────────────────────────────────┘
```

- **输入 (数据源层新增)**: `IntactDataSource` 注册表 —— ① 官方下载数据 (pusht/cube/reacher/tworoom, HF LeWM 集合);
  ② 我们自己的 L4 episode (`reports/l4_demo_*.npz` → obs 帧 + goal 帧); ③ (预留) 真机相机流。
- **输出 (硬件预留接口)**: `RobotIO` 抽象基类 —— `send_chunk(chunk)` / `reset()` / `estop()`。
  已实现 `SimRobotIO` (接 L4 引擎, 调试用) 与 `HardwareRobotIO` (**预留**: 文档化契约 + 明确 `NotImplementedError`,
  不写假实现; 真机侧按 EtherCAT/ROS2/串口 实现同一签名即可插拔)。
- **封装边界**: 节点外只认上面 4 个方法; JEPA/actor/solver/normalizer 全部在节点内部, 不做全局副作用。

## 4. 三阶段落地 (每阶段都有可验证判据)

| 阶段 | 内容 | 判据 (证据) |
|---|---|---|
| **S1 调试通** | 在 INTACT-JEPA 自己的 venv 里跑官方 `eval_official.sh direct pusht` (checkpoint `paper-e5-goal-v1`) | 终端出 SR 数值 + `get_cost_calls=0` / `candidate_sequences=0` 计时统计 |
| **S2 装进节点** | 用 `IntactRuntime` 在**我们的** L4 episode 上取 goal→出 chunk (stub 模式先验证链路, 再换真权重) | 节点自检: `obs/goal → chunk[H,D] → RobotIO` 全链打通 + 断点可进 `IntactNode.step` |
| **S3 适配 L4** | 把 chunk 接到 L4 现有决策点 (② 段 yaw / ④ 试抓), 与现有解析链**同口径 A/B** | 成功率不回退 (红线) + 3D 面板标注指令来源 = INTACT |

**红线**: S1/S2 全程不动 L4 默认档; S3 只有 A/B 通过才切默认 (与 v5.5.21→v5.5.24 同一套纪律)。

## 5. 预留接口清单 (老倪说的"预留接口")

1. `RobotIO` — 真机输出 (EtherCAT / ROS2 / 串口 / SDK): 只需实现 `send_chunk/reset/estop`。
2. `IntactDataSource.register(name, factory)` — 新数据源即插即用 (含下载器 `download_intact_dataset(...)`)。
3. `IntactRuntime(policy="direct"|"guarded_a")` — solver 可换 (direct=零搜索 / guarded_a=局部 CEM 128×3 复核)。
4. `intent_mode="goal_displacement"|"waypoint"` — 目标表示可换 (图像目标 / 坐标目标)。
5. `IntactNode.set_horizon(H)` / `set_action_dim(D)` — 与不同本体动作维度对接。

## 6. 风险与诚实标注

- INTACT 官方 checkpoint 在 **224×224 RGB + 特定动作维度** 上训练 (pusht/cube/reacher/tworoom);
  直接迁移到我们的 metaworld 插拔场景 **不可能零样本成功** → S3 必须重训/微调 (其代码支持 `--task` 单任务训练与多任务共享编码器训练)。
- 节点在权重缺失时**必须**标 `trained=False` 并给直通/零动作, 不许冒充已训练 (与仓库既有纪律一致)。
- 真机输出接口在未接硬件前**只**允许接 `SimRobotIO`; 任何写死的"成功"一律视为不合格。

## 7. Step 0 实施记录 (2026-09-12, 老倪拍板顺序: ①先出 action 屏蔽流形 ②再接流形)

**目标**: 把"潜空间接出来"做成事实, 并解决**真实性前置**——引擎真实渲染帧喂节点 (原来
`l4_episode` 数据源的观测是"依 meta 合成的运动序列", 该 npz 无渲染帧, 拿合成观测喂模型 = 蒙眼)。

**落地**:
1. `tools/intact_worker.py::act` — **截获**模型 `get_action` 内部两次 `self.encode()` 的输出
   (`jepa.py:688` obs / `:700` goal), 落盘 `z_t` / `z_goal` / `delta` 到同一个 npz (键名向后兼容)。
   截获而非重新推导 ⇒ 与动作律实际吃到的潜变量逐位一致。诊断增 `latent_norm/intent_norm/
   latent_encode_calls/latent_dim`。
2. `model_adapter.get_action` — 读回潜空间到 `runtime.last_latent` (缺失不报错, 兼容旧 worker)。
3. `contracts.IntactOutput` — 增 `latent` + `obs_source`; `build_info_dict` 增 HWC→CHW 防御。
4. `node.step(obs_frame, obs_source=...)` — 传帧默认标 `engine_render`; 数据源路径取数据源自报
   `obs_mode` (如 `synthetic_from_trace`) ⇒ **观测来源逐帧可溯源**, 面板/报告必须显示。
5. `action_adapter.IntactActionAdapter` (新) — 官方 10 维 → 本工程 4D 的**标定契约**: 未标定
   (`models/intact_action_map.json` 不存在) 时 `map_chunk()` **拒绝返回数值** (只给 reason)。默认不进引擎。
6. `tools/intact_render_probe.py` (新) — 旁路探针: 引擎全链真渲染帧 480²→224²(CHW) → 节点逐帧真前向
   → 五道闸 (G1 chunk 真值 / G2 潜空间 192 导出 / G3 |Δ| 随进度下降 / G4 观测=engine_render / G5 零搜索)。

**实测 (seed=0, paper 权重, **CPU** 推理避免抢 v10 训练显存; 引擎链 success=True 4892 步 1630 渲染帧)**:
```
20 帧真渲染 → INTACT: chunk[8,10] 每帧 nonzero=80 · std 0.32~0.46 (随观测变) · |z|≈6.88 (192维)
|Δ|=|z_goal−z_t| 逐帧 0.0~1.34 · candidate_sequences=0 (零搜索) · 单步 ~330ms(CPU)
五道闸 5/5 通过; |Δ| vs 进度 Spearman ρ=−0.109 (剔除末点) · −0.236 (含末点)
诚实边界: ρ 只是弱负相关 (非单调) —— ⑤插入段 |Δ| 反而偏大 (1.34), 末点 |Δ|=0 是构造性的
(goal 帧=末帧); 因此**不能**声称"|Δ| 随相位单调下降", 只能说方向为负。
另: 帧数 1630 vs 步记录 4692 → 阶段名按比例映射 (估算, 非逐帧对齐), 已在报告里标注。
```

**未做 (下一步)**: u_ff 注入 (Step 1, 需先标定 10→4 映射) · 流形接入 (Step 2, 需先做 z→流形真值
可解码性探针) · 真机 RobotIO。

## 8. Step 1 / Step 2 实测结果 (2026-09-12 当天做完, 结论含负结果)

### Step 1 — 动作进前馈加速器 (u_ff 槽位)
接线: `RealStateSpaceSim.attach_intact(node, adapter)` + `SS_INTACT` 三档
(不设=现状解析/MLP · `SS_INTACT_SHADOW=1`=影子: 真推理真记录不接管 · `SS_INTACT=1`=接管 xyz,
gripper 仍由状态机); 阶段白名单默认排除"插入" (插入段引擎保持解析精插);
**未标定/推理异常/映射拒绝 → 保持原 u_ff 但计数 + 记录来源** (不静默回退)。

配对数据 (`tools/intact_pair_collect.py`, 9 轮 1661 帧, 引擎真渲染帧 480²→224² CHW):
每帧同时取 (INTACT 官方 10 维 chunk + z_t 192) × (引擎 u_ff 4 维 + 流形真值 6 + obs39)。

标定 (`tools/intact_fit_maps.py --mode action`, **留一轮交叉验证**):
```
dx +0.018 / dy −0.269 / dz −0.026 / gripper −0.402 → 中位 R² = −0.147 (null −0.03~−0.24)
→ 未过 0.05 下限 → **不写 models/intact_action_map.json** (映射不出信息, 硬用=假接入)
对照: 潜空间 z_t(192→PCA16) → u_ff 同样无信号 (中位 −0.327)
⇒ 结论: 不是映射形式问题, 是**域差** (pusht 权重 vs 本插拔任务的动作语义)
```
三臂 A/B (`tools/ab_intact_uff.py`, 3 seeds × 1 rep, max_steps=600):
```
A_analytic 1/3 · 步数 526.3
B_shadow   1/3 · 步数 527.0 · INTACT 真推理 390.7 次/轮 · |chunk|=2.5583 · 行为零改变
C_intact   1/3 · 步数 527.0 · **INTACT 调用 0 次 · 拒绝映射 1172** → 未真正接管
```
⇒ **管线通 + 守卫生效 + 影子档可用** (引擎每帧真渲染喂 INTACT 真推理); **接管未验收** ——
C 臂根本没接管 (标定前提不成立), 所以"接管不回退"这个红线本轮**没有**被验证。

### Step 2 — 可解码性 (INTACT z_t → 引擎流形真值 6 维)
`tools/intact_fit_maps.py --mode decode` (留一轮 + PCA16 + 打乱标签 null):
```
rem    R²=+0.648±0.205 (null −0.565)   ✅ 有真信号
dperp  R²=+0.627±0.121 (null −0.128)   ✅ 有真信号
progress +0.029 · risk −0.763 · V −0.254 · eta +0.008   ✗ 不可解 (中位 0.019)
裁决: **部分可解码 (2/6)** → 只允许 rem/dperp 进流形; 其余维须先做 z→本工程潜空间对齐映射
```
含义: INTACT 潜空间里确实含"距离/偏离"类几何信息 (与我们流形 rem/dperp 对应), 但**不含**
接触流的进度/风险/势 —— 这与 Step 1 动作线性映射失败是同一个根因的两面。

**方法学踩坑 (已修正, 留档)**: 第一版探针用 192 维原始 z + 单次切分, 结果 train R² 0.43~0.98
而 test 全负、CCA≈1.0 —— 是 p≈n 的过拟合假象; 近常值维 (eta 恒 1.0) 还会算出 −1e7 的假极端值。
修正: 先 PCA(训练折内) 降维 + 留一轮交叉验证 + null 对照 + 近常值双重闸 (绝对 std + 相对 std)。

**下一步 (需老倪定)**: ① 在本任务数据上微调/重训 INTACT (官方支持 `--task` 单任务训练, 需先做
我们 episode → INTACT 格式的数据转换) —— 这是唯一能让"接管"真正成立的路径; ② 先把已通过闸的
rem/dperp 两个量按"部分接入"落进流形; ③ 长期保留影子档作为观测通道。


