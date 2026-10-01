---
name: lora-train-merge-discipline
description: Use when training/merging LoRA adapters. 梯度到齐闸+折叠精度闸。
---

# LoRA 训练与合并纪律

## 何时用
训练 LoRA、把 LoRA 折进基座、或做"LoRA 到底有没有用"的 A/B 之前。适用于自研 `lora_inject`(B 零初始化) 与 peft 两类。

## 铁律一: 训完必查**每条适配器都收到梯度**(否则等于没训)
B 零初始化 ⇒ 没收到梯度的适配器**永远保持 0** ⇒ 该模块行为**一点没变**。
判据(第一次 backward 后立刻断言, 不通过就报错退出):
```python
named = [(n, p) for n, p in model.named_parameters() if '.lora_A' in n or '.lora_B' in n]
zero = [n for n, p in named if p.grad is None or float(p.grad.abs().max()) == 0]
assert not zero, f"这些适配器没收到梯度(等于没训): {zero[:5]} 共{len(zero)}"
```
**实测教训**: L3 SmolVLA 注入 256 层, 训完只有 text_model 的 128 层非零,
**lm_expert(动作专家) 的 128 层 ΔW 精确为 0** ⇒ 策略行为那半一个参数没动 ⇒
"LoRA 没提升"的真因是**训偏了**, 不是模型不行、不是合并没做。
⇒ 目标模块名能命中 ≠ 该模块在**损失图**里。动作头/专家若被 `no_grad`/detach/precomputed target 绕过, 适配器就是死的。

## 铁律二: 折叠前先算**精度账**, 低精度基座上折叠可能等于抹掉
折叠 = `W' = W + s·(B@A)`(s=alpha/r)。把结果落回基座 dtype 时:
```
折叠噪声 / 信号 ≈ (基座 eps) / (‖ΔW‖/‖W‖)
bf16 eps = 2^-8 ≈ 3.9e-3     fp16 eps ≈ 9.8e-4     fp32 ≈ 1.2e-7
```
实训值: ‖ΔW‖/‖W‖ 中位 **2.17e-04** vs bf16 eps **3.9e-3** ⇒ 噪声**约为信号的 18 倍** ⇒
折进 bf16 **把 LoRA 贡献整片抹掉**, 且产物看起来"正常"(不报错) ⇒ 极易被当成"LoRA 无效"。
⇒ **判据**: 先量 `‖ΔW‖/‖W‖` 的中位与最大; 若 < 基座 eps ⇒ **禁止**折进该 dtype:
保持适配器路径加载, 或升到 fp32/fp16 折叠(代价: 体积/显存)。

## 折叠工具的两道硬校验(缺一拒绝落盘)
1. **非 LoRA 张量逐位不变** —— 用**原始字节** sha256(`t.view(torch.uint8)`, bfloat16 不能 `.numpy()` 直转),
   证明只动了该动的键;
2. **ΔW == s·B@A** —— fp32 上**逐位相等**; 低精度基座改成量化误差判据并**打印误差量级**。
自证: 写完**回读**新文件逐键比对 + 键集合与目标形态(普通 `nn.Linear`, 去掉 `.base.`)一致。

## 键名坑(lerobot/SmolVLA safetensors)
LoRA 包装后原 Linear 存成 `<prefix>.base.weight`, 适配器 `<prefix>.lora_A/B`(A=[r,in], B=[out,r]);
"合并部署"语义 = 还原成普通 Linear ⇒ 输出键应为 `<prefix>.weight`/`.bias`(去掉 `.base.`),
否则标准加载器**不认**(会把权重当未知键丢掉 ⇒ 零动作)。
`merge_lora_ckpt.py`/`post_lora_merge.sh` 只吃 INTACT 那种 `.pt`; safetensors 用 `lora_merge_safetensors.py`。

## A/B 之前的三问
- 适配器**训过**吗(铁律一)?
- 部署侧**真加载**了适配器或折叠产物吗(自证 `trained=True`/加载回读)?
- 对照组与实验组**除了该变量都相同**吗(同数据/同 seed/同帧/同口径)?
三问任一为否 ⇒ A/B 结论**无效**, 不得写成"无提升"。
