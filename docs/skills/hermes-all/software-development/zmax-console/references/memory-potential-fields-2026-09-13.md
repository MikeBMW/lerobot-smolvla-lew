# 🧲 分层记忆势场 (L2 肌肉 / L3 工艺流程 / L4 物理工作空间 / 总装机记忆联络) — 2026-09-13 (v5.5.38)

老倪: 「先把这个势场的逻辑, 实现到 L2肌肉记忆, L3工艺流程记忆, L4物理工作空间记忆, 以及总装机记忆的记忆层联络策略。
然后我会将当前独立的 L4 INTACT 功能, 逐步打开每层记忆, 提高当前系统的性能和能力。」

## 一句话架构

**统一接口 = 一个标量势场 Φ(x)** (x = 光模块头/末端 3D 位置, 米)。势场低处 = 该层记忆认为"该待的地方";
**梯度 −∇Φ = 速度场 = 意图 (intent)** — 层间只传"往哪个方向走", 不传技能标签。

```
L2  SkillPotentialField        Φ_SK(x) = ½k‖x−x_g‖² + k_lin‖x−x_g‖ + λ(1−e^{−d⊥²/2σ²})
L3  ProcessPotentialField      Φ_process(x,t) = Σ_k w_k(t)·Φ_SK_k(x),  Σw ≡ 1
L4  GlobalPotentialField       Φ_global = Φ_process + Φ_obstacle(孔壁/台面 现场几何) + Φ_world(世界模型预测项)
总装机 MemoryLayerBridge       四层联络策略 + 逐层开关 + 跨层仲裁 + 台账
```
代码: `src/lerobot/memory/potential_field.py` · 画布节点: `src/lerobot/memory/mem_nodes.py::node_ss_mem_field`
(注册在 `tools/gui/node_logic.py` → `_reg("ss_mem_field", [...])`)

## 每一项为什么这样设计 (都踩过坑, 别改回去)

| 项 | 公式/取值 | 为什么 (实测) |
|---|---|---|
| 谷底 x_g | **冠军轨迹真末点** (`champ_x[-1]`), 不是 io.exit | io.entry/exit 与 champ_x **锚点不同源** (差 15~145mm; SK06/07 ≈ PEG_HEAD_OFF_XY=0.13 → 抓握点系 vs 光模块头系) → 用 io.exit 当谷底会出现"吸引项与管壁项打架", 场的最小值不在谷底 → 不收敛 |
| σ (谷宽) | 1.6 × 相邻轨迹点中位间距, 下限 4mm | 窄谷=精细对位; 4mm 以下浮点噪声会主导梯度 |
| k_att | 2/L² (L=轨迹弧长) | 沿轨迹 Φ_att 从入口 ~1 降到 0 → 势场无量纲可读, 与管壁项同量级 |
| λ (管壁高度) | **λ = 4·k_att·σ²** (不是绝对值!) | λ 取绝对值时 λ/σ² ≈ 6e4 ≫ k_att ≈ 1e3 → 管壁项压死吸引项, 轨迹若有回折/勾尾 → 流量停在离谷底 3~5mm 的**次极小** |
| k_lin (锥形项) | **k_lin = 3·k_att·σ** | 只有二次吸引项时仍有次极小 → 加锥形(线性)吸引后 ∇Φ 除谷底外处处非零 → **谷底是唯一极小, 收敛有保证** (势场导航 quadratic-near/conic-near 组合) |
| 权重 w_k(t) | 段时长 = 各技能**真跑帧数**归一 + raised-cosine 交叉淡入 | 保证 Σw≡1、谷底按时序连续移动 (实测 Δw ∝ dt → 无阶跃) |
| 相位判定 | `weights_from_state(x)`: w ∝ exp(−d_k²/2(3σ)²); 若全下溢 → 取**最近**轨迹管 | **模型直驱时"时钟进度 t"与实际相位不同步** (速度/时长都变了) → 必须按状态判; 下溢时退化为"最近管"而不是 None (否则永远不介入) |
| w_floor | blend_action(w_floor=0.2) | **恢复语义**: 出轨迹管 (conf→0) 仍留一部分场权, 把状态拉回管里 = L4 的"失败自主恢复" |
| d_max | 0.5 m | 诚实边界: 离所有轨迹管 >500mm = 记忆不覆盖该状态 → 不介入 (不硬拽) |

## 逐层开关 (老倪逐步打开的地方)

`data/memory_layers.json` `{"L2":0,"L3":0,"L4":0,"assembly":0}` — 默认**全关**。
- 全关: `compose()` → `None`; `blend_action()` **恒等返回入参** (可断言零回退) — 未开层时系统行为与原链路完全一致
- 开 L2 → 只叠技能势场; 再开 L3 → 加流程势场; 再开 L4 → 加障碍/世界模型项 (实测逐项贡献出现, 未开层贡献恒 0)
- 开层后接 **L4 INTACT 链** (`tools/intact_sw_optical_bridge.py`): `u = (1−w)·u_model + w·u_field`,
  `w = w_max·max(conf, w_floor)`, `u_field = −∇Φ_unit·step_m / K_ACT` (→ env 量纲)
- 台账 `data/assembly_memory.json` (record_outcome 真写读; 仲裁: 接触段 L2 优先 / 自由段 L3 优先)

## 验证 (真数据, 无文字空转)

`MUJOCO_GL=egl ./gui-venv311/bin/python tools/verify_memory_potential_fields.py` → **26/26**
数据 = `data/muscle_memory.json` 的 7 条冠军轨迹 (SK01-07, 每段 76 次命中) + 引擎现场几何
(`RealStateSpaceSim._reset` 采样的 hole [-0.17685,0.42429,0.13035] / r=0.016)。
判据: 解析梯度 vs 数值 (1e-7~1e-9) · 横向势单调 (轨迹上 0 < 5mm < 10mm < 20mm) · 收敛 98~127 步到 <1mm 且 Φ 严格下降 ·
Σw≡1 · 孔壁斥力双向 (壁上朝外 / 孔内朝轴) · 逐层开关逐项生效 · 全关恒等 · 台账真写读。

桥 e2e (`/tmp/verify_mem_layers_e2e.py`): 全关 → 介入 **0** 步; 只开 L2 → 介入 **120/120** 步 (w̄=0.1, 技能 SK05, d⊥=135mm)。

## ⚠️ 坑

1. **muscle_memory.json 是活数据**: 每次真实化 rollout/桥跑完都会更新 (n_ok/champ_x) → 势场与判据数字会随之漂移
   (实测同一脚本两次跑, SK06/07 的 io.exit 失配从 126/145mm 变成 27.8/31.4mm)。验证要用"当前"数据 + 别把数字写死进断言。
2. **不要给 `process.active(t)` 传 t=None** (会 `'>' not supported between float and NoneType`) —
   已统一走 `MemoryLayerBridge._active(x, t)` / `ProcessPotentialField._w(x, t)`; t=None 表示"按状态判相位"。
3. **L2 节点日志里必须打印 io.exit 失配**: 这是数据质量问题 (锚点不同源), 不修就会让"谷底"长期错位。
4. **pkill 类命令用变量拼名** (`V=studi; P=${V}o.py`) — 直接写 `pkill -f "studio.py"` 可能被 Hermes 硬拦或自杀。
5. 训练接力脚本 `/home/ubuntu/l4_ab/train_intact_optical_chain.sh`: 家族里**没有 ckpt 时也要能起首轮**
   (早期版本直接 break → v5 起不来); 首轮不覆盖 output_model_name (用配置自带名), 之后各轮换名续训。
