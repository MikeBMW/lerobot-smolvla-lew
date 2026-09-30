# L4 反归一化口径 bug 修复 + "模型为何不被采纳"定量归因 (2026-09-22)

## 一、修复的 bug: L4 反归一化统计与权重**不同源**

| 位置 | 原值 | 问题 |
|---|---|---|
| `tools/gui/simulink_module.py:12016`(GUI L4 装配) | `reports/zmax_action_stats.json` | 源自 `zmax_insert.h5` (n=18635) |
| `tools/probe_l4_callchain.py` / `fit_intact_action_frame.py` | 同上 | 同上 |
| `tools/diag_l4_stall.py` | 同上 | 同上 |

而权重侧的训练集是:
```
在役 intact_l4_current/weights.pt → intact_goal_optical_insert_v6r11_s3072/weights_epoch_2.pt
                                   ↳ train_config.yaml: name = optical_insert_v5_disturb.h5
本轮新训 intact_goal_optical_insert_v6d5_s3072  ↳ name = optical_insert_v6_disturb.h5
```
⇒ 运行时用 `zmax_insert` 的 mean/std 去反归一化 v5/v6 域权重 = **指令缩放全错** (dx std 0.153 vs 0.0742/0.0774 ≈ 2 倍)。
`intact_direct_rollout.py:48` 早有"必须同源"的注释、也有 `audit_stats()` 快速失败闸, 但**默认路径与 GUI 装配点没跟上**
→ 本轮改为**自动同源解析**:

```python
# tools/intact_direct_rollout.py
def resolve_stats(ckpt=None, root=ROOT) -> (path, reason):
    # 读 ckpt 的 train_config.yaml 里的 `name: *.h5` (训练集),
    # 再在 reports/*_action_stats.json 里挑 source 与之相同的那一份。
    # ★ 关键: 权重可能是「目录 + weights.pt 软链」形态 (intact_l4_current) → 必须跟随软链取真实目录。
```
实测:
```
INTACT_POLICY=intact_l4_current  → ✅ 同源: optical_insert_v5_action_stats.json ↔ 训练集 optical_insert_v5_disturb.h5
INTACT_POLICY=...v6d5_s3072      → ✅ 同源: optical_insert_v6_action_stats.json ↔ 训练集 optical_insert_v6_disturb.h5
```
调用点已改: GUI L4 装配 · probe_l4_callchain · diag_l4_stall (并在日志里打印解析理由, 不做静默回落)。

**修复效果 (同 seed=0, 200 步, 同一权重)**:
| 指标 | 修复前 (zmax 统计) | 修复后 (同源统计) |
|---|---|---|
| 模型动作逐维 std | 0.045 / 0.008 / 0.040 / 0.57 | **0.022 / 0.004 / 0.017 / 0.37** |
| 参考逐维 std | 0.070 / 0.054 / 0.027 / 0.0 | 同 |
| 闸「否决幅值」 | 0/200 | 0/200 |

## 二、真正挡住 L4 的是**模型动作方向**, 不是接线 (定量)

L4 直驱路实测 (200 步, 参考链驱动 + 模型每帧真推理 → off-policy 合法配对):
```
IntactNode 真推理 200/200 · L2 技能上下文 24 维逐帧构造 200/200 · 模型动作记录 200/200
L2 收口闸: veto_dir = 200/200 ← 全部因方向被否决; blend = 0; sim._direct_act = False
⇒ env 实际执行 = 参考(解析)链, 模型动作一次都没进 env
```
逐轴线性对齐判定 (`tools/fit_intact_action_frame.py`, 400 步配对, 在完整 8 维里搜最佳维):

| 引擎轴 | 最佳模型维 | corr | 判定 |
|---|---|---|---|
| dx | 1 | **0.370** | 🟡 弱相关 |
| dy | 3 | **-0.261** | 🟡 弱相关(反相) |
| dz | 4 | **-0.353** | 🟡 弱相关(反相) |
| gripper | 7 | **0.666** | ✅ 可对齐 |

**判决**: 不是"差一个逐轴线性映射"(那需要 |corr|≥0.5 且可解释), 而是**模型 xyz 输出与教师动作弱相关且部分反相**
→ 与 v5.5.37 变更记录里的旧结论一致 ("预测 std 仅教师 7~16%, 模型能力问题非接线问题")。
**⇒ 这是训练侧问题, 标定映射 (models/intact_action_map.json) 对它无效。**

## 三、由此得到可量化的优化 KPI (取代"感觉好点没有")

```
KPI-1  逐轴 |corr| (dx/dy/dz):  现状 0.37 / 0.26 / 0.35   → 目标 ≥0.5  (闸开始按 cos 融合)
KPI-2  闸采纳率 (blend/总步):    现状 0/200 = 0%           → 目标 >0%
KPI-3  sim._direct_act 非空:    现状 False                → 目标 True (模型动作真进 env)
KPI-4  (下游) 仿真插入成功率 + 3D 视图可见"插拔成功"
```
工具: `tools/fit_intact_action_frame.py <steps> <seed>` (跑完出 corr/R² 表 + 落盘配对 json)。
纪律: 每次改权重都**同 seed 同口径**重测这张表; 不许用"训练 loss 降了"替代。

## 四、本轮其余 L4 事实 (与上一份矩阵合并看)

- `u_ff_source = intact(chunk×K_ACT=0.5)`: L4→意图解码器的 u_ff 先验**可用**(不需要标定), 有据可查
  (证据文件 `reports/intact_l3_cond.json`)。
- `models/intact_l3_map.json` 缺 → **L3 条件向量通道**未标定, 但**有计数不写死**(诚实纪律)。
- 纤维丛层已标定 (contact r²_loso 0.471 · z7 丛 r²_loso 0.607, n=582, 真实引擎样本)。
- 引擎里 L3 SmolVLA 能真执行接入 (ckpt `outputs/train/smolvla_lew_v10_1h/checkpoints/004000`)。
