# L3 SmolVLA LoRA 实例(2026-09-30 实测)

## 现状数值
- ckpt: `outputs/train/smolvla_lew_lora_200_r4/checkpoints/000200/pretrained_model/model.safetensors` (1.30 GB, 1417 键)
- 注入: 256 层 · targets q/k/v/o · exclude vision_model · 可训 2,785,280 / 627,945,784 = **0.4436%**
- 适配器分布: `text_model` 128 组**非零**(|B|max 3.16e-3~6.49e-3, 中位 4.35e-3) · `lm_expert` 128 组**精确为 0**
- 折叠账: ‖ΔW‖/‖W‖ 中位 2.17e-04 / 最大 2.516e-03; base=bfloat16(eps 3.9e-3) ⇒ 噪声/信号 ≈ 17.7 倍

## 命令
```bash
# 干跑(不落盘) —— 校验+报误差
./gui-venv311/bin/python tools/lora_merge_safetensors.py \
  --src outputs/train/smolvla_lew_lora_200_r4/checkpoints/000200/pretrained_model --r 8 --alpha 16 --dry
# 量适配器是否训过(零=没训)
./gui-venv311/bin/python -c "
import torch;from safetensors.torch import load_file
sd=load_file('<...>/model.safetensors')
z=[k[:-7] for k in sd if k.endswith('.lora_A') and k[:-7]+'.lora_B' in sd and sd[k[:-7]+'.lora_B'].float().abs().max()==0]
print('零适配器 %d/%d'%(len(z),len([k for k in sd if k.endswith('.lora_A')])))  # L3 实测 128/256
"
```

## 修复方向(未做)
1. 给自研 lora 通道加铁律一的梯度闸(仿 INTACT `train.py` 的 "received gradients" 断言, 那套检查只在 INTACT 仓库里);
2. 查 `lm_expert` 为何不在损失图(no_grad/detach/precomputed target/targets 命中但 forward 未走);
3. 重训后按铁律二决定**保持适配器路径**还是**升精度折叠**; bf16 折叠**不要**做。

## 相关文件
`tools/lora_merge_safetensors.py` · `tools/lora_inject.py`(:83 merged_weight, :153 lora_parameters) ·
`tools/post_lora_merge.sh`(INTACT 专用) · `tools/joint_train_all.py`(L3 通道, `--lora-l3 --l3-lora-engine local`)
