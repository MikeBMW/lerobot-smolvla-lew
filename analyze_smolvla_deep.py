#!/usr/bin/env python3
"""
SmolVLA 深度分析: base vs metaworld 对比
"""
import torch, json, time, os, sys
import numpy as np
from collections import defaultdict

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"设备: {device}")

from lerobot.policies.smolvla import SmolVLAPolicy

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase 1: 加载模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
models = {}

print("\n" + "="*60)
print("Phase 1: 加载模型")
print("="*60)

# Base (已缓存)
t0 = time.time()
models["base"] = SmolVLAPolicy.from_pretrained("lerobot/smolvla_base")
models["base"].to(device).eval()
print(f"  ✅ base: {time.time()-t0:.1f}s")

# MetaWorld 官方微调 (下载)
t0 = time.time()
try:
    models["metaworld"] = SmolVLAPolicy.from_pretrained("lerobot/smolvla_metaworld")
    models["metaworld"].to(device).eval()
    print(f"  ✅ metaworld: {time.time()-t0:.1f}s")
except Exception as e:
    print(f"  ⚠️ metaworld下载失败: {e}, 用本地checkpoint")
    ckpt = "outputs/smolvla_metaworld/checkpoints/000300/pretrained_model"
    models["metaworld"] = SmolVLAPolicy.from_pretrained(ckpt, local_files_only=True)
    models["metaworld"].to(device).eval()
    models["metaworld_name"] = "ours"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase 2: 参数统计
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n" + "="*60)
print("Phase 2: 参数统计")
print("="*60)

for name, m in models.items():
    total = sum(p.numel() for p in m.parameters())
    trainable = sum(p.numel() for p in m.parameters() if p.requires_grad)
    print(f"\n  [{name}]")
    print(f"    总参数: {total/1e6:.0f}M")
    print(f"    可训练: {trainable/1e6:.0f}M ({100*trainable/total:.1f}%)")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase 3: 权重分布分析
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n" + "="*60)
print("Phase 3: 权重分布分析")
print("="*60)

def weight_stats(model, name):
    """分析模型权重分布"""
    stats = {}
    for n, p in model.named_parameters():
        if p.requires_grad and p.numel() > 1000:
            w = p.data.float()
            stats[n] = {
                "mean": w.mean().item(),
                "std": w.std().item(),
                "min": w.min().item(),
                "max": w.max().item(),
                "norm": w.norm().item(),
            }
    return stats

# 对比 Expert 部分
for comp_name in ["base", "metaworld"]:
    m = models[comp_name]
    expert_params = {}
    for n, p in m.named_parameters():
        if "lm_expert" in n and p.requires_grad:
            expert_params[n.split("lm_expert.")[-1]] = p.data.float()
    
    if expert_params:
        total_norm = sum(p.norm().item() for p in expert_params.values())
        print(f"\n  [{comp_name}] Expert 模块:")
        print(f"    参数量: {sum(p.numel() for p in expert_params.values())/1e6:.1f}M")
        print(f"    总L2范数: {total_norm:.1f}")
        # 各层权重范数
        print(f"    层权重范数 (前5层):")
        for key in sorted(expert_params.keys())[:5]:
            print(f"      {key}: norm={expert_params[key].norm().item():.2f}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase 4: VLM输出对比
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n" + "="*60)
print("Phase 4: VLM冻结验证")
print("="*60)

for name, m in models.items():
    frozen = sum(1 for p in m.parameters() if not p.requires_grad)
    trainable = sum(1 for p in m.parameters() if p.requires_grad)
    print(f"  [{name}] 冻结层: {frozen}, 可训练层: {trainable}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase 5: 推理对比 (相同输入)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n" + "="*60)
print("Phase 5: 推理对比 (随机输入)")
print("="*60)

from lerobot.datasets import LeRobotDataset
from lerobot.utils.constants import OBS_LANGUAGE_TOKENS, OBS_LANGUAGE_ATTENTION_MASK
from lerobot.policies.smolvla.modeling_smolvla import resize_with_pad
from transformers import AutoTokenizer
from torch.utils.data import DataLoader

# 用MetaWorld真实数据
ds = LeRobotDataset("lerobot/metaworld_mt50", episodes=[0])
loader = DataLoader(ds, batch_size=1, shuffle=True)
batch = next(iter(loader))
batch = {k: v.to(device) if isinstance(v, torch.Tensor) else v for k, v in batch.items()}

tokenizer = AutoTokenizer.from_pretrained(models["base"].config.vlm_model_name)
encoded = tokenizer("complete the task", return_tensors="pt", padding="max_length",
                    max_length=48, truncation=True)

ib = {
    "observation.image": batch["observation.image"],
    "observation.state": batch["observation.state"],
    OBS_LANGUAGE_TOKENS: encoded["input_ids"].to(device),
    OBS_LANGUAGE_ATTENTION_MASK: encoded["attention_mask"].to(torch.bool).to(device),
}

results = {}
for name, m in models.items():
    t0 = time.time()
    with torch.no_grad():
        # base模型需要3摄像头，复制单路
        if "observation.images.camera1" in m.config.image_features:
            img = ib["observation.image"]
            ib_infer = {
                "observation.images.camera1": img,
                "observation.images.camera2": img,
                "observation.images.camera3": img,
                "observation.state": ib["observation.state"],
                OBS_LANGUAGE_TOKENS: ib[OBS_LANGUAGE_TOKENS],
                OBS_LANGUAGE_ATTENTION_MASK: ib[OBS_LANGUAGE_ATTENTION_MASK],
            }
        else:
            ib_infer = ib
        actions = m.predict_action_chunk(ib_infer)
    results[name] = {
        "time": time.time() - t0,
        "shape": list(actions.shape),
        "min": actions.min().item(),
        "max": actions.max().item(),
        "mean": actions.mean().item(),
        "std": actions.std().item(),
    }

for name, r in results.items():
    print(f"\n  [{name}]")
    print(f"    耗时: {r['time']*1000:.0f}ms")
    print(f"    输出: {r['shape']}")
    print(f"    范围: [{r['min']:.4f}, {r['max']:.4f}]")
    print(f"    均值: {r['mean']:.4f} ± {r['std']:.4f}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase 6: 总结
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n" + "="*60)
print("Phase 6: 总结")
print("="*60)

if "metaworld_name" in models:
    print(f"\n  metaworld 使用本地checkpoint (未加载预训练权重, 200步微调)")

# 释放
for m in models.values():
    del m
torch.cuda.empty_cache()
print(f"\n  GPU已释放: {torch.cuda.memory_allocated()/1e9:.2f}GB")
print("\n✅ 分析完成")
