# L4 卡点定量归因：为什么门闸总否决 —— dy 轴 (2026-09-22)

老倪的 KPI-1 = 逐轴 `|corr| ≥ 0.5`（L2 收口闸按逐轴判，一轴不过就整体 veto）。
本文把"模型动作进不了 env"从**印象**钉成**可判决的结论**，全部只读数据。

## 一、判闸逐轴结果（同源 teacher-forced 回放 · 同帧同权重只切能力通道）

工具：`tools/intact_replay_check_v4.py`（`--device cpu` 可跑；**已加自动回退**，无 GPU 时先打印根因再回落）
数据：`optical_insert_v5_disturb.h5` · 权重：在役 `intact_goal_optical_insert_v6r11_s3072/weights_epoch_2.pt`

```
帧偏移k   MAE     常数基线  赢常数   p_dx    p_dy    p_dz   p_grip
   0    0.0260   0.0538    True   0.562   0.306   0.909   0.887     (60 clips)
   1    0.0257   0.0554    True   0.836  -0.098   0.838   0.890
   ...
  30 clips 复跑同形: p_dx 0.56~0.84 · p_dz 0.61~0.91 · p_grip 0.63~0.96
                   **p_dy 全程 -0.16 ~ +0.31 (多数 |·|<0.16)**
```
⇒ **dx / dz / grip 离线都过 0.5，唯独 dy 不过** —— 而门闸要求三轴全过。
⇒ 这不是"接线/口径"问题（同一份回放里 dx/dz 是好的），是**模型学不到 dy**。

## 二、为什么学不到：dy 在数据里既"瘦"又"不可从观测推断"

工具：`tools/ana_l4_dy.py`（只读 h5）· 两份数据（v5 149,100 帧 / v6 87,150 帧）结论一致：

| 轴 | std | 活跃帧占比 `\|a\|>0.05` | 最优单维观测 corr | 最优单维 R² | 判读 |
|---|---|---|---|---|---|
| dx | 0.074~0.077 | **48~49%** | 0.32~0.33 | **0.10~0.11** | 有信息可学 |
| **dy** | 0.036~0.037 | **12%** | **0.15~0.18** | **0.02~0.03** | **观测里几乎没有该轴的信息** |
| dz | 0.044~0.046 | 14~16% | 0.45~0.46 | **0.20~0.21** | 有信息可学 |
| grip | 0.371~0.382 | 83~84% | — | — | 阶段驱动，好学 |

另：三轴一阶自相关都 **0.95~0.98** ⇒ 动作被慢变成分主导；判闸里的"高 corr"有相当部分来自慢趋势，
而不是逐帧的真实控制量 —— 这也是为什么离线 0.9 的 dz 到 live 只剩 -0.35（自回归闭环里慢趋势被抖掉）。

## 三、结论与修法（不是"再训久一点"）

1. **根因 = 数据配方**：仿真 episode 生成器给的任务分布里，**横向(dy)纠偏行为几乎没有**
   （12% 活跃、且与观测基本无关）⇒ 老师的 dy 本身接近噪声 ⇒ 任何模型都学不出，门闸必然否决。
2. **修法（数据侧，可执行）**：episode 生成器加**横向错位/干扰**让 dy 成为有意义的伺服量：
   - 模块/槽位 y 方向随机偏移 ±5~10mm（现有 `ep_jitter.dy_cm` 只有 ±1~5cm 的**整回合慢变**，需加仓内逐帧可达的错位）；
   - 或提高 yaw 扰动幅度，让对位段必须靠 dy 侧向纠偏；
   - 采集后**先跑本文两个工具做验收**（`p_dy ≥ 0.5` 才算配方改对），再谈续训。
3. **真机补充**：产线两个槽位 y 间距 **50mm**（`slot1 0.5026` / `slot2 0.4524`）—— 槽间转移天然是横向运动，
   真机采集会自带 dy 内容，是比仿真更干净的 dy 数据源。
4. **不要再做的事**：继续用同一份数据加轮次（dy 的信息量不会因为多训而出现）；或把门闸"放宽"到只看 dx。

## 四、复现命令

```bash
CACHE=/home/ubuntu/stable-wm-cache/datasets
# 逐轴判闸 (无 GPU 会自动回退 cpu)
CUDA_VISIBLE_DEVICES= INTACT_POLICY=intact_goal_optical_insert_v6r11_s3072/weights_epoch_2.pt \
  ./gui-venv311/bin/python tools/intact_replay_check_v4.py --skill on --clips 60 --repeats 1 \
  --out reports/intact_v4_v6r11_peraxis_on.json
# 数据侧归因 (两份 h5 一起看)
/home/ubuntu/INTACT-JEPA/.venv/bin/python tools/ana_l4_dy.py
```
产物：`reports/intact_v4_v6r11_peraxis_on.json`（逐轴 pearson + 每槽 MAE/常数基线）·
`reports/tmp_judge_autofallback_check.json`（回退自检）
