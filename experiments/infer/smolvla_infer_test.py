#!/usr/bin/env python3
"""
SmolVLA 本地推理实验
模型: lerobot/smolvla_base (SmolVLM2-500M + Action Expert)
用法: conda run -n lerobot python smolvla_infer_test.py
"""

import sys
import time
import torch
import numpy as np
from PIL import Image

def main():
    print("=" * 60)
    print("SmolVLA 推理实验")
    print("=" * 60)

    # Step 1: 加载模型
    print("\n[1/4] 加载预训练模型 lerobot/smolvla_base ...")
    t0 = time.time()

    from lerobot.policies.smolvla import SmolVLAPolicy

    policy = SmolVLAPolicy.from_pretrained("lerobot/smolvla_base")
    policy.eval()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    policy.to(device)

    print(f"   ✅ 加载完成 ({time.time()-t0:.1f}s)")
    print(f"   设备: {device}")
    print(f"   模型名: {policy.name}")

    # Step 2: 查看模型结构
    print(f"\n[2/4] 模型信息")
    config = policy.config
    print(f"   VLM: {config.vlm_model_name}")
    print(f"   冻结视觉: {config.freeze_vision_encoder}")
    print(f"   训练专家: {config.train_expert_only}")
    print(f"   动作块: {config.chunk_size}步")
    print(f"   动作维度: {config.max_action_dim}")
    print(f"   状态维度: {config.max_state_dim}")
    print(f"   注意力模式: {config.attention_mode}")
    print(f"   输入特征: {list(config.input_features.keys())}")
    print(f"   输出特征: {list(config.output_features.keys())}")

    # 统计参数量
    total_params = sum(p.numel() for p in policy.parameters())
    trainable = sum(p.numel() for p in policy.parameters() if p.requires_grad)
    print(f"   总参数: {total_params/1e6:.1f}M")
    print(f"   可训练: {trainable/1e6:.1f}M ({100*trainable/total_params:.1f}%)")

    # GPU 内存
    if device == "cuda":
        mem = torch.cuda.memory_allocated() / 1e9
        print(f"   GPU内存占用: {mem:.2f} GB")

    # Step 3: 构造虚拟输入
    print(f"\n[3/4] 构造虚拟输入...")
    batch_size = 1

    # 图像特征 (随机噪声模拟)
    img_features = {}
    for key in config.image_features:
        # 生成随机图像 (3, 512, 512)
        fake_img = torch.randn(batch_size, 3, 512, 512, device=device)
        img_features[key] = fake_img
        print(f"   图像 [{key}]: {fake_img.shape}")

    # 状态 (全零)
    state = torch.zeros(batch_size, config.max_state_dim, device=device)
    print(f"   状态: {state.shape}")

    # 语言token (需要 tokenizer，先跳过用空tensor)
    from lerobot.utils.constants import OBS_LANGUAGE_TOKENS, OBS_LANGUAGE_ATTENTION_MASK
    # 用 tokenizer 编码一个简单指令
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(policy.config.vlm_model_name)
    text = "pick up the object and place it in the bin"
    encoded = tokenizer(text, return_tensors="pt", padding="max_length",
                        max_length=policy.config.tokenizer_max_length, truncation=True)
    lang_tokens = encoded["input_ids"].to(device)
    lang_mask = encoded["attention_mask"].to(torch.bool).to(device)
    print(f"   语言token: {lang_tokens.shape}, mask: {lang_mask.shape}")

    batch = {
        **img_features,
        "observation.state": state,
        OBS_LANGUAGE_TOKENS: lang_tokens,
        OBS_LANGUAGE_ATTENTION_MASK: lang_mask,
    }

    # Step 4: 推理
    print(f"\n[4/4] 推理...")
    t0 = time.time()

    with torch.no_grad():
        actions = policy.predict_action_chunk(batch)

    elapsed = time.time() - t0
    print(f"   ✅ 推理完成 ({elapsed:.2f}s)")
    print(f"   输出动作: {actions.shape}")
    print(f"   动作范围: [{actions.min().item():.4f}, {actions.max().item():.4f}]")
    print(f"   动作均值: {actions.mean().item():.4f}")
    print(f"   动作标准差: {actions.std().item():.4f}")

    print("\n" + "=" * 60)
    print("✅ 实验成功！SmolVLA 推理流程跑通")
    print("=" * 60)

if __name__ == "__main__":
    main()
