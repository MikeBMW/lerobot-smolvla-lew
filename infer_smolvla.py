#!/usr/bin/env python3
"""加载 lerobot/smolvla_base 预训练模型并推理"""
import os, sys, torch
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["WANDB_MODE"] = "disabled"
sys.path.insert(0, "src")

from lerobot.policies.smolvla import SmolVLAConfig, SmolVLAPolicy

DEVICE = "mps" if torch.backends.mps.is_available() else "cpu"
MODEL_ID = "lerobot/smolvla_base"

print(f"🚀 加载预训练模型: {MODEL_ID}")
print(f"   设备: {DEVICE}")

# 加载
policy = SmolVLAPolicy.from_pretrained(MODEL_ID).to(DEVICE)
policy.eval()

total = sum(p.numel() for p in policy.parameters())
trainable = sum(p.numel() for p in policy.parameters() if p.requires_grad)
print(f"🧠 参数: {total:,} total | {trainable:,} trainable")

# 查看配置
cfg = policy.config
print(f"\n📋 模型配置:")
print(f"   VLM: {cfg.smolvlm_name}")
print(f"   Action: {cfg.action_model_type}")
print(f"   obs_steps: {cfg.n_obs_steps}, chunk: {cfg.chunk_size}")
print(f"   image_size: {cfg.siglip_image_size}")
print(f"   hidden: {cfg.action_hidden_size}, layers: {cfg.action_num_layers}")
print(f"   features: input={list(cfg.input_features.keys())} output={list(cfg.output_features.keys())}")

# 获取输入形状
for name, feat in cfg.input_features.items():
    print(f"   input {name}: {feat.type.value} {feat.shape}")
for name, feat in cfg.output_features.items():
    print(f"   output {name}: {feat.type.value} {feat.shape}")

# 合成测试数据推理
print(f"\n🔮 推理测试...")
dummy_batch = {}
for name, feat in cfg.input_features.items():
    shape = list(feat.shape)
    if feat.type.value == "VISUAL":
        dummy_batch[name] = torch.randn(1, *shape).to(DEVICE)
    else:
        dummy_batch[name] = torch.randn(1, *shape).to(DEVICE)

with torch.no_grad():
    result = policy.predict(dummy_batch)
print(f"   预测动作: shape={result.shape if hasattr(result,'shape') else len(result)}")
print(f"   值: {result[0][:5].tolist() if hasattr(result,'__getitem__') else result}")

print(f"\n✅ 预训练模型推理成功!")
