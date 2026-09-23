# ①-1 · L4 注入"被闸死"的根因与对齐层同口径 A/B — 2026-09-24

## 结论先行 (一句话)

「新 LoRA 不改指令」**不是 LoRA 的问题**：L4→引擎的**对齐层**（锥角截断 cos≥0.9 + 幅度封顶 1.2×，
标定文件 `models/l4_align_map.json` 早就是 ready）**只在 `SS_L4_ALIGN=1` 时才施加**，
而此前所有 A/B（含 09-23 那轮）都没开这个开关 ⇒ 原始提案（cos 中位 **−0.605**、幅度比中位 **5.8×**）
逐帧撞 L2 收口闸 ⇒ 0% 通过 ⇒ `u_ff` 与解析链逐位相同 ⇒ 看起来"LoRA 什么都没改"。

## 一、闸门内部量：开对齐前后（同 seed 0/1 · 90 步 · direct 臂 · 在役策略）

| 量 | 对齐 OFF (原始提案) | 对齐 ON |
|---|---|---|
| 闸门计数 (pass / 方向否决 / 幅值否决) | {−1: 64, −2: 26} / {−1: 23, −2: 59, 1: 8} | **{1.0: 90} / {1.0: 90} 全部通过** |
| cos 中位 (对齐前 → 后) | −0.459 / 0.542 | −0.605 → **0.963** · 0.603 → **0.900** |
| 幅度比中位 (>1.5× 帧数) | 5.17 / 5.83 (89/90 帧超标) | **0.864 / 0.848 (0/90 超标)** |
| L4 融合 blend / w_zero | 0 / 90 与 8 / 82 | **90 / 0 与 90 / 0** |

⇒ 对齐层把"方向系统性反向 + 幅度 5.8×"这两个**可标定的系统偏差**消掉，提案 100% 进得了闸。

## 二、闭环 A/B 同口径对照（seed 0/1/2 · 450 步 · 在役指针 `intact_l4_current`）

格式：done · 步数 · 插入末端 mm · 全程最小 peg↔目标 mm

| 臂 | seed0 | seed1 | seed2 |
|---|---|---|---|
| analytic (解析锚) | **True** 375 · 65.2 · 0.1 | False 450 · 30.9 · 0.1 | False 450 · 23.4 · 0.1 |
| direct·对齐 OFF | **True** 375 · 65.2 · 0.1 (=锚, 注入无效) | False 450 · **13.6** · 0.1 | False 450 · 21.2 · 0.1 |
| direct·对齐 ON | **True** 373 · 65.3 · 0.1 | False 450 · **27.7** · 0.0 | False 450 · 21.9 · 0.0 |
| line_w1·对齐 OFF | False 450 · 3.5 | False 450 · 22.1 | False 450 · 31.9 |
| line_w1·对齐 ON | False 450 · 35.9 | False 450 · 41.2 | False 450 · 29.3 |

（两次运行里 analytic 三个 seed 的数字**逐位一致** ⇒ 引擎确定性，口径可比。）

## 三、判据与结论（按老倪门槛：有提升才行，持平/回退不进默认档）

1. **回退被消除**：seed1 direct 从 13.6mm（比解析链差 56%）恢复到 27.7mm（与解析链 30.9 同级）⇒ 对齐层是**零回退修复**。
2. **未证明提升**：3 个 seed 的成功数与解析链相同（各 1/3）；插入末端与最小 peg↔目标全部落在解析链 ±10% 内
   ⇒ **不切在役指针、不进默认档**（与 09-23 的定档一致，但根因已从"LoRA inert"更正为"对齐层未开"）。
3. **值得下一轮做主实验**：`line_w1`(直连线注入) + 对齐 ON 在 seed1/seed2 明显好于 OFF（41.2 vs 22.1 / 29.3 vs 31.9），
   但仍是 0/3 成功，**不能宣称提升**；下一轮：直连线 + 对齐 + 提步数/提 lr 的同口径 A/B。

## 四、复现命令

```bash
SWM=/home/ubuntu/stable-wm-cache
BASE="INTACT_POLICY=intact_l4_current INTACT_DEVICE=cpu INTACT_RUNTIME=root STABLEWM_HOME=$SWM \
LOCAL_DATASET_DIR=$SWM INTACT_REPO=/home/ubuntu/INTACT-JEPA MUJOCO_GL=egl"
# 闸门内部量 (开对齐)
env SS_L4_ALIGN=1 $BASE ./gui-venv311/bin/python tools/diag_lora_du.py --seeds 0,1 --steps 90 --arms analytic,direct
# 闭环 A/B (关 / 开 各跑一次对比)
env            $BASE ./gui-venv311/bin/python tools/ab_intent_line_closedloop.py --seeds 0,1,2 --steps 450
env SS_L4_ALIGN=1 $BASE ./gui-venv311/bin/python tools/ab_intent_line_closedloop.py --seeds 0,1,2 --steps 450
```

## 五、纪律教训（写进技能）

**A/B 之前先核对"这条链上所有开关的默认值"**：本次因为 `SS_L4_ALIGN` 默认关，把"通路上游未开"误判成
"模型无效"，白跑了一轮 A/B 并写进了昨天的交接单。判据：任何"注入无效/零影响"的结论，先用
`diag_*` 打出**通路上逐级计数**（本帧提案 → 闸门 → blend）再下结论。
