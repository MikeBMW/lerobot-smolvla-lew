#!/usr/bin/env python3
"""SmolVLA 模型结构可视化 — 子模块分析"""
import torch
from lerobot.policies.smolvla import SmolVLAPolicy

device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"设备: {device}")
print("加载模型...")

policy = SmolVLAPolicy.from_pretrained("lerobot/smolvla_base")
policy.to(device)
policy.eval()

model = policy.model  # VLAFlowMatching

print("\n" + "=" * 70)
print("SmolVLA 模型结构分析")
print("=" * 70)

def tree(module, prefix="", depth=0, max_depth=3):
    """递归打印模块树"""
    if depth > max_depth:
        return
    children = list(module.named_children())
    for i, (name, child) in enumerate(children):
        is_last = (i == len(children) - 1)
        connector = "└─" if is_last else "├─"
        params = sum(p.numel() for p in child.parameters())
        trainable = sum(p.numel() for p in child.parameters() if p.requires_grad)
        train_str = f" [{trainable/1e6:.1f}M/" if trainable != params else " ["
        train_str += f"{params/1e6:.1f}M]"
        line = f"{prefix}{connector} {name}: {child.__class__.__name__}{train_str}"
        print(line)
        new_prefix = prefix + ("   " if is_last else "│  ")
        tree(child, new_prefix, depth+1, max_depth)

# ── 1. 顶层结构 ──
print("\n【VLAFlowMatching 顶层】")
print(f"├─ vlm_with_expert: SmolVLMWithExpertModel")
print(f"└─ flow_matching_head / action_decoder...")
for name, child in model.named_children():
    params = sum(p.numel() for p in child.parameters())
    print(f"   ├─ {name}: {child.__class__.__name__} [{params/1e6:.1f}M]")

# ── 2. vlm_with_expert 详细结构 ──
print("\n【SmolVLMWithExpertModel 子结构】")
vxe = model.vlm_with_expert
for name, child in vxe.named_children():
    params = sum(p.numel() for p in child.parameters())
    trainable = sum(p.numel() for p in child.parameters() if p.requires_grad)
    t = f" [{trainable/1e6:.1f}M/{params/1e6:.1f}M]"
    print(f"├─ {name}: {child.__class__.__name__}{t}")

# ── 3. VLM 内部 ──
if hasattr(vxe, 'vlm'):
    print("\n【VLM (SmolVLM2-500M) 内部】")
    tree(vxe.vlm, max_depth=2)

# ── 4. Expert 内部 ──
if hasattr(vxe, 'expert'):
    print("\n【Action Expert 内部】")
    tree(vxe.expert, max_depth=2)

# ── 5. 完整模块列表 (含嵌入层) ──
print("\n【完整子模块列表 (>10K params)】")
for name, mod in model.named_modules():
    params = sum(p.numel() for p in mod.parameters())
    if params < 10000:
        continue
    trainable = sum(p.numel() for p in mod.parameters() if p.requires_grad)
    level = name.count('.')
    indent = "  " * level
    t = f"trainable={trainable/1e6:.1f}M" if trainable != params else ""
    print(f"{indent}{name.split('.')[-1]}: {mod.__class__.__name__} [{params/1e6:.1f}M] {t}")

# ── 6. 参数总结 ──
print("\n" + "=" * 70)
print("参数总结")
total = sum(p.numel() for p in model.parameters())
trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
frozen = total - trainable
print(f"  总参数:     {total/1e6:.1f}M")
print(f"  可训练:     {trainable/1e6:.1f}M ({100*trainable/total:.1f}%)")
print(f"  冻结(VLM):  {frozen/1e6:.1f}M ({100*frozen/total:.1f}%)")

# 内存
if device == "cuda":
    print(f"  GPU内存:    {torch.cuda.memory_allocated()/1e9:.2f} GB")

print("\n✅ 完成")
