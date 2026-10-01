#!/usr/bin/env python3
"""LoRA 训练与否的**免基准**硬判据。
原理: lora_inject 对 B 做**零初始化**(标准 LoRA), W' = W + (alpha/r)*B@A。
      ⇒ 训练前所有 lora_B ≡ 0; 只要某个 lora_B 非零 ⇒ 该层**确实被梯度更新过**。
      这条不需要 init 文件做基准, 也绕开"B 零初始化 ⇒ 第一步 A 无梯度"的假阴性。
"""
import collections
import os
import sys

from safetensors.torch import load_file

os.chdir("/home/ubuntu/zmax_rel")
ckpt = sys.argv[1] if len(sys.argv) > 1 else "outputs/train/smolvla_lew_lora_200_r6/checkpoints/last/pretrained_model/model.safetensors"
sd = load_file(ckpt)


def fam(k: str) -> str:
    for key, name in ((".action_model.", "action_model(动作头)"), (".le_world_model.", "le_world_model(世界模型)"),
                      ("vision_model", "vision(视觉塔)"), ("lm_expert", "lm_expert(死模块)"),
                      ("vlm.model", "vlm.model(语言塔)"), ("text_model", "text_model(语言塔)")):
        if key in k:
            return name
    return "other"


st = collections.defaultdict(lambda: [0, 0, 0.0])      # B条数 / 非零B条数 / 最大|B|
for k, v in sd.items():
    if not k.endswith("lora_B"):
        continue
    m = float(v.float().abs().max())
    f = fam(k)
    st[f][0] += 1
    if m > 0:
        st[f][1] += 1
    st[f][2] = max(st[f][2], m)

print(f"   产物: {os.path.basename(os.path.dirname(os.path.dirname(ckpt)))}/{os.path.basename(ckpt)}")
tot = nz = 0
for f, (t, n, mx) in sorted(st.items()):
    tot += t
    nz += n
    print(f"   {f:<24} lora_B {t:>3} 条 · 非零 {n:>3} 条 · 最大|B| {mx:.6e}  ⇒ {'✅ 训练过' if n > 0 else '❌ 从未更新'}")
print(f"   ── 合计 {tot} 条 lora_B, {nz} 条非零 ⇒ {'✅ 全部模块族都被训练' if nz == tot else '⚠️ 有模块族未训练'}")
