# 🧬 Z-MAX L4 纤维丛联络层设计 (动作丛 → 接触丛 → DiT)

> 需求 (老倪 2026-09-15): 「把 INTACT 意图解码器的 predictor 预测的 z 潜空间, 输出到流形专家预测器;
> 这个流形是个**动作丛 (action bundle / 纤维丛)**, 然后进一步进到**接触流形, 也是一个接触丛**;
> 你来设计映射关系, 应用纤维丛的映射联络关系。因为**是光模块的插拔, 所以对性能流形没啥作用,
> 但主力还是接触流形有作用**。最后进入 DiT 生成轨迹。要让**每条 L4 的线条, 都有实际的数据**。
> 注意**不能降低 L2 和 L3 的性能, 你要叠加, 增强 L4 的能力**。」

## 1. 丛结构 (全部量来自真实链路, 无占位值)

| 丛 | 底空间 B | 纤维 | 在本任务中的角色 |
|---|---|---|---|
| 动作丛 A | 任务相位/进度 (阶段 s, 插入进度 e∥) | 执行/意图矢量 (引擎参考 `u_ff`, 夹爪 1 维) | L2 解析链给出**参考水平场** (canonical) |
| 潜空间丛 Z | 同上 | `z ∈ R^192` — `z_t = encode(obs 滑窗)`、`z_goal = encode(goal)`、**`z_pred = predictor(z_t, a)`** | L4 世界模型的"预测潜空间" (新增导出) |
| 接触丛 C | 同上 | `F_C ⊂ R^6` = [进度 e∥, 法向偏离 e⊥, V=½‖e‖², V̇=−e·v, 切向速度, 法向速度] | ⭐ **主力** (插拔任务成败由接触约束决定) |
| 性能丛 P | 同上 | `F_P ⊂ R^6` = [η 耦合效率, δ⊥, δ_axial, δ⊥(x,y,z)] | ⚠️ **次要**: 插拔不优化耦合代价 → `w_perf = 0` (只跑只记录, 不注入) |

## 2. 映射与联络 (三个可测几何量)

* **丛映射 (pullback)** `Φ: Z → F_C`, 标定式 `Φ(z) = W·z + W_q·φ(PCA₈(z))`
  * 线性项 `W` = 联络系数 (1-形式); 二次项 `W_q` 让**曲率可非零** (线性联络曲率恒 0 —— 这是判据, 见 §4)
  * 标定: ridge + **留一交叉验证 (LOO)**, 逐维 R² + null 基线; 闸值 `R²_loso ≥ 0.30 且 null < 0.10`
* **水平提升 (horizontal lift)**: `h_z = Φ(z_pred) − Φ(z_t)` —— 沿"预测潜空间方向"的协变导数 (一步)
* **几何联络 (canonical, 无需标定)**: `h_geo` = 沿当前前馈参考的**单位步长几何预报**在 `F_C` 上的增量
* **挠率/张力**: `T = h_Z^C − h_geo^C`; `κ_tor = ‖T‖`, `cos∠ = ⟨h_Z^C, h_geo^C⟩/(‖·‖‖·‖)`
  * 语义: 世界模型的预测与几何是否同向 (同向 ⇒ 预测可信, 可加权注入)
* **曲率 (交换子 / 和乐)**: `Ω = Φ(z_t+δ_a+δ_g) − Φ(z_t+δ_a) − Φ(z_t+δ_g) + Φ(z_t)`,
  `δ_a = z_pred − z_t` (动作方向), `δ_g = z_goal − z_t` (目标方向)
  * `Ω ≠ 0 ⇔ 两个方向的平行移动不交换 ⇔ 接触约束下丛不平凡` (自由空间应 ≈ 0)

## 3. 下游接线 (只产条件/参考, 不写执行量)

```
INTACT-JEPA (子进程)
  └─ z_t / z_goal / z_pred  ──桥(npz, 白名单透传)──▶ 引擎
       ├─ ① 丛映射 A: z_pred → ẑ7 (R^7)  →  流形专家预测器 WorldModelPredictor(ẑ7, a, m)  → 预测流形 6 维
       │      (预测器的架构与训练权重**一字未改**; 换的只是"喂什么进去": 当场几何 z7 → 预测潜空间拉回)
       ├─ ② 联络: h_z / κ_tor / cos∠ / Ω  →  DiT 条件 token
       │      c_fiber = [ δ̂(192 单位化) ⊕ ĥ_z(6 归一化) ⊕ (κ_tor, cos∠, ‖Ω‖) ]   (200 维)
       │      经 `action_head.apply_l4_cond` 同一 token 机制进 DiT (维度自适应, 叠加在既有 δ 通道之外)
       └─ ③ 性能丛 Φ_p(z_pred): 只记录 (w_perf = 0)
                                  ▼
              DiT 生成轨迹 (同一颗 smolvla_lew DiT, 不是另写模型)
                                  ▼
              u_int ──(能力栈收缩投影)──▶ 引擎 u_ff 槽 ──L2 唯一出口(sched.decide+safety.saturate)──▶ 执行
```

## 4. 纪律 (零回退 + 诚实拒绝)

1. **环境守卫**: `SS_L4_FIBER` 不设 → `_l4_fiber_line` 首行即 `return None` ⇒ 逐位与改造前相同 (L2/L3 不受影响)。
2. **未标定/未过闸**: 线路**照跑** (采数 + 计数 + 来源标注), 但 `w=0` 不注入 —— 拒绝 + 计数, 不写死映射。
3. **未标定也要采数**: 否则"没标定→没采数→永远标不了"死锁 (本次已修)。
4. **唯一执行出口不变**: `u_ff ← proj_{U_L2}((1−w)·u_ff + w·u_int)`, 越界夹紧并记账; `sched.decide` 计数恒为 1。
5. **判据可自检**: `fiber_bundle.py` 自带 selftest —— 线性 Φ 的曲率必须 = 0, 二次 Φ 的曲率必须 > 0 (证伪"曲率是摆设")。

## 5. 改动清单 (2026-09-15)

| 文件 | 改动 |
|---|---|
| `tools/intact_worker.py` | 新增 **z_pred / z_pred_last / z_pred_seq** 导出: 截获 `model.predict` + (零搜索 direct 不调 predictor 时) 用模型自己的 `predict()` 逐位复刻 `rollout_one_step` 推演整个 chunk |
| `src/lerobot/policies/intact/runtime/model_adapter.py` | npz 白名单加 z_pred 三键 (之前被**桥这一层**丢掉 → 下游永远拿不到) |
| `src/lerobot/manifold/fiber_bundle.py` | **新增**: 丛结构 + 丛映射 Φ/Φ_geo/A/Φ_p + 水平提升 + 挠率 + 曲率 + 条件向量 + selftest |
| `tools/gui/state_space_sim_real.py` | 新增 `_fc/_fiber_truth/_l4_fiber_line/_fiber_truth_at/_fiber_z7_geo/dump_fiber_data/fiber_line_summary`; 调用点在解码器之后; 流形专家预测器 z 输入改走 `ẑ7`; DiT 条件叠加; 逐帧列 8 个 |
| `tools/fit_fiber_map.py` | **新增**: 用真实样本拟合 `models/intact_fiber_map.json` (LOO R² 闸) |
| `tools/probe_l4_callchain.py` | 新增场景 `L4line` / `L4audit`; 采数落盘; 纤维丛取证段 ③c; 零回退 trace hash; 审计 json |
| `tools/audit_l4_edges.py` | **新增**: L4 区**每条边**的运行时数据流判定 (有数据 / 未接管 / 死线) |
| `tools/verify_fiber_zero_regression.py` | **新增**: 同 seed 每臂独立进程 × (L2/L3/L4) 的逐位零回退验证 |

## 6. 报告口径 (三段分开, 不许一句"打通了"盖过)

* **接线段**: 逐条给计数/hash/夹紧量 (可复现命令)
* **质量段**: Φ/曲率/挠率的 LOO R² 与真实数值; 未过闸就写"不注入"
* **闭环段**: 未跑闭环就写"未跑" (本轮只做接线 + 标定 + 零回退)
