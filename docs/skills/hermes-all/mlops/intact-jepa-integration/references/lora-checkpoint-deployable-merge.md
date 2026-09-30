# LoRA ckpt 可部署化: 包装键 → merge → 指针目录 → 自证 (2026-09-23 一手)

承接 SKILL.md §0 / §0b。这次事故的教训不是"LoRA 训练失败", 而是
**训练成功却加载不了 → 零动作 → A/B 各臂逐位相同 → 被读成"新权重没提升"**,
差点把一个可用/不可用的结论写进默认档决策。全过程与可复用工具记录如下。

## 1. 症状与假象

L4 INTACT LoRA 训练产物 `checkpoints/intact_goal_optical_insert_v6lora_200/`(243s, 200 步),
引擎里挂上后:

```
🧠 INTACT 意图-动作: 数据源=未设置 · 策略=direct(零搜索) · action_dim=4 · horizon=8 · trained=False
[seed1 direct ] done=False steps=450 插入末端=30.9mm 最小=0.1mm · peg-target 末端=156.0mm 最小=56.5mm · line(ran=0 …)
[seed1 line_w0] 同上逐位相同   [seed1 line_w1] 同上逐位相同
[seed2 analytic] 同上逐位相同   …
```

**假 A/B 指纹 (三合一)**: ① 各臂 done/steps/最小距逐位相同 ② `action_dim=4`(默认兜底) 而非 8
③ 日志只有 `trained=False`。见到任两条 → 先验权重加载, 再谈提升/回退。
(反例: 在役权重同一 A/B 里是 `action_dim=8 · trained=True`, 且 `line_w0/applied=0` 与 `direct` 一致、`line_w1` 才有 `applied>0`。)

## 2. 两层根因 (先后都要修)

**第一层 — 目录里不止一个 `.pt`** (官方 `load_pretrained(目录)` 要求恰好一个):
```
ValueError: Ambiguous checkpoint: multiple .pt files in …/intact_goal_optical_insert_v6lora_200.
            Specify the file directly.
```
产物目录当时有 `weights_epoch_1.pt` + `weights_merged.pt`(+ 我误加的软链)。
修: 另建**指针目录**(只放 `config.json` + 唯一 `weights.pt` 软链, 与在役 `intact_l4_current` 同构),
不要往产物目录里塞软链。

**第二层(真凶) — LoRA 适配器没 merge, 键名是包装名**:
```
RuntimeError: Error(s) in loading state_dict for JEPA:
   Missing key(s) in state_dict: "encoder.layers.0.attention.q_proj.weight", …
```
| 文件 | 键数 | 键形态 |
|---|---|---|
| 在役 `v6r11_s3072/weights_epoch_2.pt` | **323** | `encoder.layers.0.attention.q_proj.weight` |
| 新 LoRA `…v6lora_200/weights_epoch_1.pt` | **547** | `…q_proj.lora_A` / `.lora_B` / `…q_proj.base.weight` (224 个 lora/base) |
| 产物里的 `weights_merged.pt` | 323 | 干净, 但那是 **LoRA 之前的基座**, 不是本轮结果 |

## 3. 修法 (标准 LoRA merge, 与 `tools/lora_inject.py::merged_weight()` 同公式)

`W = W_base + (alpha / r) · (B @ A)` — L4 训练侧 `ZMAX_LORA_R=8`, `ZMAX_LORA_ALPHA=r*2=16` → **scaling 2.0**
(见 `tools/joint_train_all.py` 的 L4 段)。

```bash
cd /home/ubuntu/lerobot-smolvla-lew
# 单步 merge(产物目录原样保留, 输出新文件)
/home/ubuntu/INTACT-JEPA/.venv/bin/python tools/merge_lora_ckpt.py \
  --in  /home/ubuntu/stable-wm-cache/checkpoints/intact_goal_optical_insert_v6lora_200/weights_epoch_1.pt \
  --out /home/ubuntu/stable-wm-cache/checkpoints/intact_goal_optical_insert_v6lora_200/weights_merged_clean.pt \
  --r 8 --alpha 16
# 实测: 输入 547 键 → 输出 323 键 · lora_layers=112 merged=112 · 残留包装键 0

# 一键收尾: merge + 建指针目录 + worker 自证 (不过关退非 0)
bash tools/post_lora_merge.sh intact_goal_optical_insert_v6lora_200 intact_l4_v6lora_200 8 16
```
产物 / 指针布局:
```
checkpoints/intact_goal_optical_insert_v6lora_200/   config.json, weights_epoch_1.pt(原始), weights_merged_clean.pt
checkpoints/intact_l4_v6lora_200/                    config.json, weights.pt -> ../intact_goal_optical_insert_v6lora_200/weights_merged_clean.pt
```

## 4. 自证 (秒级, 比跑整链快得多)

用引擎同口径 (`task=pusht` + `INTACT_POLICY=<指针名>`, **不传 --ckpt**) 起 worker, 写 `{"cmd":"hello"}` 到 stdin:
```bash
INTACT_DEVICE=cpu INTACT_RUNTIME=root STABLEWM_HOME=/home/ubuntu/stable-wm-cache \
LOCAL_DATASET_DIR=/home/ubuntu/stable-wm-cache HF_HUB_OFFLINE=1 MUJOCO_GL=egl \
INTACT_POLICY=intact_l4_v6lora_200 \
/home/ubuntu/INTACT-JEPA/.venv/bin/python tools/intact_worker.py \
  --repo /home/ubuntu/INTACT-JEPA --task pusht --hf-repo INTACT-JEPA/INTACT --hf-rev paper-e5-goal-v1 \
  --policy direct --policy-name intact_l4_v6lora_200 --device cpu --runtime root
# stdin: {"cmd":"hello"}
```
- 修前: `{"trained": false, "dims": {}, "reason": "… Missing key(s) … q_proj.weight"}`
- 修后: `{"trained": true, "dims": {"action_dim": 8, "history_size": 3, "img_size": 224}}` ✅
- 注意 `reason` 里出现过 4 种完全不同的病: `Ambiguous checkpoint`(多 .pt) / `Missing key(s)`(未 merge) /
  `Cannot resolve '<名字>'`(名字没落在 `$STABLEWM_HOME/checkpoints/` 下) / `解包后仍找不到 …weights_epoch_5.pt`
  (既没 `--ckpt`/`INTACT_WEIGHTS` 也没指针目录, 回落论文资产包)。**只信 reason, 别猜。**
- 手册: worker 的探测命令 + `{"cmd":"hello"}` = 60 秒内可复现的"能不能加载"判据, 比跑 A/B 便宜两个数量级。

## 5. 流程改进 (已落地)

- `tools/fullpipe_chain.sh` 的 ②b 步: JOINT 训练后自动 `post_lora_merge.sh` → 以后每轮 LoRA 训练都产出可加载指针
- 任何 L4 策略 A/B / 判闸 / 换指针之前 **先过 §4 自证**, 两方都要 `trained=True · action_dim=8`
- 结论纪律不变: 单 seed 差异 <5% 属噪声 → 不能说提升也不能说回退; 未证明提升 → 不进默认档
