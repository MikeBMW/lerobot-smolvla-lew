# 流形引擎 (Manifold Engine) — L4 核心内核 · 落地记录 2026-09-24

**一句话定位**: 把**高维状态**自动约束为**低维流形**, 在流形上完成 状态表征 → 约束投影 →
测地线导航 → 梯度流 → 感知反馈闭环。L4 层核心内核; 画布上位于 L4 行 **输入与输出的中点**。

- 源码: `src/lerobot/manifold/manifold_engine.py` (`class ManifoldEngine`)
- 画布节点: `ss_mani_eng` (x=7500, y=1546, 340×130) — L4 专家自主功能行
- 注册三件套: `node_logic.py` `_reg("ss_mani_eng")` + `node_ss_mani_eng` 真执行 + `_EXTERNAL_LOC`
  + 能力清单 `capability_levels.py::L4-C15`
- 标定产物: `models/manifold_engine.npz` (真跑引擎轨迹拟合)
- 基准证据: `reports/manifold_engine_bench.json` · `reports/canvas_level_audit_*.json`

---

## 一、功能实现 (按规格书逐项对照)

| 规格要求 | 实现 | 状态 |
|---|---|---|
| 编码器 Encoder: x∈R^N → z∈R^n | `class Encoder` — **PCA 真拟合** (numpy SVD, 真分解) + 可选 fiber_bundle 丛映射提升 | ✅ 真实现 |
| 流形投影器 Projector: z → p∈M | `class ManifoldProjector` — 按类型真投影 (球面归一化 / SU(2) 群元素 / SO(3) 正交化+det 修正 / SE(3) R+t / 环面 mod 2π) 并返回**约束违例** | ✅ 真实现 |
| 度量计算器 Metric: d(p,q) | `class MetricCalculator` — 弧长(球面) / Fubini–Study(SU2) / 测地角(SO3) / Killing 近似(SE3) / 周期欧氏(环面); 切线梯度 = 数值中心差分 + **切空间投影** | ✅ 真实现 |
| 导航器 Navigator: 测地线 γ | `class Navigator` — 大圆 slerp / 群指数映射 / 螺旋运动 (SE3: slerp R + lerp t) / 最短环绕(环面); `step()` 走切向量 | ✅ 真实现 |
| 反馈闭环 Feedback: 有界修正 | `class FeedbackLoop` — 增益+平滑+**硬限幅**(单次 ≤ max_step), 实测超大残差被限到 0.05 | ✅ 真实现 |
| 流形类型 > 10 种 | `MANIFOLD_REGISTRY` 共 **9 种**: 7 ready (euclidean/sphere/torus/so3/se3/su2/latent_flat) + 2 **如实标 planned** (calabi_yau / hyperbolic, 写明缺什么) | ⚠️ 7/9 (不造假) |
| API: project/navigate/feedback/query | 全部真实现 (+ `gradient_flow()` / `step()` / `latency_report()` / `spec_check()` / `registry_table()`) | ✅ |
| 延迟 <10ms / 投影 <1ms / 测地线 <50ms / >100Hz | **实测**: 端到端 **0.056ms** · 投影 **0.019ms** · 测地线T=16 **0.24ms** · 上限 **≈3500Hz** | ✅ 全达标 |
| 精度: 约束误差<1% · 测地距离<5% · 定位<0.1mm · 力控<0.1N | 约束违例实测 **1.1e-16**; 其余三项需真机才能给 → **未标, 不抄规格书** | ⚠️ 待真机 |
| 鲁棒性: SNR>10dB · 异常检测>99% · 恢复<100ms · 72h | 有异常标志(投影改动量阈值)与有界恢复; **>99%/72h 未测** | ⚠️ 待长跑 |

## 二、复用既有真件 (不另起炉灶, 符合仓库"零回退"纪律)

| 组件 | 复用来源 |
|---|---|
| SU(2) 群 (群乘/逆/exp∘log/Bloch/Fubini–Study 距离) | `left_right/state_space/su2.py` |
| SO(3)/SE(3) (四元数 slerp / log/exp / R↔quat) | `manifold/lie_intent.py` |
| 势函数 Φ (接触 V、性能 V_p/η) | `manifold/manifold_layer.py` (Contact/PerformanceManifold) |
| 丛提升 (lift/联络) | `manifold/fiber_bundle.py` |
| 安全限幅 | 复用既有 `capability_stack.py` 口径 (动作界 ±1 + 标定界) |

## 三、实测数字 (真跑引擎 160 步轨迹, `tools/manifold_engine_bench.py`)

- 延迟: 编码 0.002ms · 投影 0.019ms · 梯度 0.013ms · 测地线(T=16) 0.24ms · 反馈 0.008ms · **端到端 0.056ms/帧**
- 精度: **约束违例 max 1.1e-16** · 测地线终点误差 0 · 测地线长度 1.53 (起始态→收敛态)
- 势能: Φ 0.9595 → 0.0 (**向收敛态收敛**, 收敛帧占比 0.506)
- 解码器 (岭回归, 带动作界限幅): 训练段逐维相关 **0.826 / 0.940 / 0.924 / 0.757**;
  **未见段 R² 为负** → 只在标定分布内可信, 跨段须重标定 (评估铁律)
- 自检: 7 个 ready 流形全部通过 (度量公理/测地线端点/反馈限幅/约束违例), calabi_yau 如实拒答

### 踩到并修掉的真 bug (都进了自检)
1. **潜维不足静默退化**: 8 维潜空间喂 SO(3) 会 `eye(3)` 静默退化 → 改**补齐并显式标注** (`latent_padded`)。
2. **SE(3) 点切分错误**: 12 维点 (R9+t3) 直接 `reshape(3,3)` → `ValueError`; 改 `[:9]` 并加维数断言。
3. **残差语义混淆**: 原"残差"把"原始潜向量范数与半径之差"当约束违例 (对球面恒 1.0+) →
   拆成 **约束违例**(投影后 ‖约束(p)‖≈0, 验投影器) 与 **投影改动量**(‖p−z‖, 做置信/异常)。
4. **反馈维数不匹配**: 传感器残差 8 维直接加到 16 维流形点上 → 广播错误; 改**显式对齐**(截断/补零+标注)。
5. **解码器外推发散**: 无界岭回归在未见帧预测幅值 3.05 (真值 ≤1.0) → 全段 R² 从 +0.561 掉到 **−3.55**;
   加**动作界标定+限幅**后幅值 1.10 ≈ 真值 1.0。

## 四、画布集成 (L4 输入与输出的中间)

`tools/canvas_add_manifold_engine.py` — 落地前 6 条硬断言, 全部通过:
1. **居中**: L4 行前向输入前沿 x=**4690** < 新节点 x=**7500** < 输出前沿 x=**10016** (中点 7353, 偏差 147)
2. **空档**: 新节点落在同行带最大横向空档 (4690, 10016) 内 (独立校验, 防"自选一对方便的前沿")
3. **零重叠**: 与 70 个既有节点无重叠 · 行带内 · 坐标全 int
4. **接线 10 条全前向无重复**: 入 5 (传感器融合/SU(2)统一状态/标定层/潜空-流形/阶段专家MOE)
   → 出 5 (INTACT 意图解码器 / 流形专家预测器 / 接触流形 / 性能流形 / 动作调制器)
5. 幂等 (已存在则跳过)
6. 完备性终检通过: 节点 71 · 连线 162 · 孤岛 0 · 断头 7 全合法终端 · 悬空 3 全数据源 · 重叠 0

档位级审计: 新节点定级 **R2-档位级真接** (注册 ✅ / 源码映射有效 ✅ / 10 连线) · 全图 **真缺口 0**。

## 五、灰度纪律 (与全仓库一致)

- 当前姿态 = **只读旁路**: 每帧真跑, 结论进 `_SS_STATE["mani_eng"]` 与日志, **不下发动作**。
- 接管动作的前置 (缺一不可): ① 解码器跨段重标定 (现只在标定分布内可信) ② 同口径 A/B 证明**不回退**
  ③ 老倪授权。**未证明提升不得进默认档**。

## 六、复现

```bash
# 自检 (群公理/测地线/反馈限幅/planned 拒答)
PYTHONPATH=src ./gui-venv311/bin/python src/lerobot/manifold/manifold_engine.py --selftest
# 标定 (真跑引擎轨迹 → models/manifold_engine.npz)
PYTHONPATH=src MUJOCO_GL=egl ./gui-venv311/bin/python src/lerobot/manifold/manifold_engine.py --calibrate
# 实测基准 (延迟/精度/收敛)
./gui-venv311/bin/python tools/manifold_engine_bench.py
# 画布接线 (dry-run 先看断言, --apply 落地; 必须先停 studio)
./gui-venv311/bin/python tools/canvas_add_manifold_engine.py --apply
# 档位级验收 + 完备性
./gui-venv311/bin/python tools/canvas_level_audit.py && ./gui-venv311/bin/python tools/canvas_completeness_check.py
# GUI 安全启停 (避免 pkill 自杀; venv 在仓库根不在 tools/gui)
bash tools/studio_ctl.sh {status|stop|start|restart}
```
