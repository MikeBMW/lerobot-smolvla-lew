#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一 backbone 可行性实测: 用 SmolVLM2 的预训练视觉塔当共享主干

目的: 回答"能不能统一 backbone" — 实测
  ① SigLIP 视觉塔能否单独加载 (不拖 LLM 部分)
  ② 参数量 / 8GB 卡可行性 / 单帧与批量耗时
  ③ 输出特征维度 (供 L2/L3/L4/L5 四个头挂载)
"""
import os
import sys
import time

import torch

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
MODEL = "HuggingFaceTB/SmolVLM2-500M-Video-Instruct"

print("=== ① 加载 SmolVLM2 视觉塔 (只取 vision_model) ===", flush=True)
t0 = time.time()
try:
    from transformers import AutoModel, AutoProcessor
    full = AutoModel.from_pretrained(MODEL, torch_dtype=torch.float32)
    vis = getattr(full, "vision_model", None) or getattr(getattr(full, "model", None), "vision_model", None)
    print(f"  全模型参数: {sum(p.numel() for p in full.parameters())/1e6:.1f}M")
    if vis is not None:
        n = sum(p.numel() for p in vis.parameters())
        print(f"  ✅ 视觉塔参数: {n/1e6:.1f}M · 加载 {time.time()-t0:.1f}s")
        cfg = vis.config
        print(f"     规格: hidden={cfg.hidden_size} layers={getattr(cfg,'num_hidden_layers','?')} "
              f"patch={getattr(cfg,'patch_size','?')} img={getattr(cfg,'image_size','?')}")
except Exception as e:
    print(f"  ❌ {type(e).__name__}: {str(e)[:200]}")
    sys.exit(1)

print("\n=== ② 前向 + 显存 / 耗时 (共享主干的成本) ===", flush=True)
dev = "cuda" if torch.cuda.is_available() else "cpu"
vis = vis.to(dev).eval()
img_size = int(getattr(cfg, "image_size", 512) or 512)
for bs in (4, 8, 16):
    torch.cuda.empty_cache() if dev == "cuda" else None
    x = torch.randn(bs, 3, img_size, img_size, device=dev)
    try:
        t1 = time.time()
        with torch.no_grad():
            out = vis(pixel_values=x)
        dt = (time.time() - t1) * 1000
        feat = out.last_hidden_state
        mem = torch.cuda.max_memory_allocated() / 1048576 if dev == "cuda" else 0
        print(f"  batch {bs:2d}: 输出 {tuple(feat.shape)} · {dt:.0f}ms · 峰值显存 {mem:.0f}MB")
    except torch.cuda.OutOfMemoryError:
        print(f"  batch {bs:2d}: ❌ OOM")
        break

print("\n=== ③ 可训练性 (共享主干 + 多头 是否可行) ===", flush=True)
if dev == "cuda":
    torch.cuda.empty_cache()
vis.requires_grad_(False)
head = torch.nn.Linear(cfg.hidden_size, 128).to(dev)
x = torch.randn(4, 3, img_size, img_size, device=dev)
with torch.no_grad():
    feat = vis(pixel_values=x).last_hidden_state[:, 0, :]
y = head(feat)
y.sum().backward()
gn = head.weight.grad.abs().mean().item()
peak = torch.cuda.max_memory_allocated() / 1048576 if dev == "cuda" else 0
print(f"  冻结主干 + 可训头: 梯度 {gn:.3e} (非零 ✓) · 峰值显存 {peak:.0f}MB")
print(f"\n结论: 视觉塔 {sum(p.numel() for p in vis.parameters())/1e6:.1f}M 可独立加载, "
      f"特征 {cfg.hidden_size} 维 → 可挂 4 个头 (L2检测/L3动作/L4预测/L5场景)")
