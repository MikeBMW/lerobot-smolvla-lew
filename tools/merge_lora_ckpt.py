#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""merge_lora_ckpt.py — 把 LoRA 包装过的 ckpt 折叠回"原始命名"的可部署 state_dict

起因 (2026-09-23 实测): L4 LoRA 训练产物 weights_epoch_1.pt 里是 **包装后** 的键
  encoder.layers.0.attention.q_proj.lora_A / .lora_B / .base.weight   (547 键, 224 个 lora/base)
官方 root 运行时 (`swm.wm.utils.load_pretrained`) 只认原始命名:
  encoder.layers.0.attention.q_proj.weight                             (323 键)
→ 加载报 `Missing key(s) ... q_proj.weight` → worker 标 trained=False → 节点返回**零动作**
  → A/B 各臂数字逐位相同, 看着像"新权重没提升", 实为"根本没加载"。

本脚本做 LoRA 的标准 merge (§ 与 tools/lora_inject.py 的 merged_weight() 同一公式):
  W = W_base + (alpha / r) · (B @ A)
输出新文件 (绝不覆盖原产物), 然后用 `tools/intact_worker.py` 发 {"cmd":"hello"} 自证 trained=True。

用法:
  intact-venv/bin/python tools/merge_lora_ckpt.py \
      --in  <.../weights_epoch_1.pt> --out <.../weights_merged_clean.pt> --r 8 --alpha 16
"""
import argparse
import json
import os

import torch


def merge(sd: dict, r: int, alpha: float):
    scaling = float(alpha) / float(r)
    out, pairs, stats = {}, 0, {"lora_layers": 0, "base_only": 0, "kept": 0}
    prefixes = sorted({k[: -len(".lora_A")] for k in sd if k.endswith(".lora_A")})
    stats["lora_layers"] = len(prefixes)
    for k, v in sd.items():
        if k.endswith(".lora_A") or k.endswith(".lora_B"):
            continue                                   # 适配器本身不进导出
        if k.endswith(".base.weight") or k.endswith(".base.bias"):
            out[k.replace(".base.", ".")] = v          # 基座改名回原名
            stats["base_only"] += 1
            continue
        out[k] = v
        stats["kept"] += 1
    for pre in prefixes:
        w = out.get(pre + ".weight")
        A, B = sd.get(pre + ".lora_A"), sd.get(pre + ".lora_B")
        if w is None or A is None or B is None:
            continue
        w = w.to(torch.float32)
        delta = (B.to(torch.float32) @ A.to(torch.float32)) * scaling
        out[pre + ".weight"] = (w + delta).to(sd[pre + ".base.weight"].dtype)
        pairs += 1
    stats["merged"] = pairs
    stats["scaling"] = scaling
    return out, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", dest="dst", required=True)
    ap.add_argument("--r", type=int, default=8)
    ap.add_argument("--alpha", type=float, default=16.0)
    a = ap.parse_args()
    sd = torch.load(a.src, map_location="cpu", weights_only=False)
    if isinstance(sd, dict) and isinstance(sd.get("state_dict"), dict):
        sd = sd["state_dict"]
    print("输入: %s · 键数 %d" % (os.path.basename(a.src), len(sd)))
    merged, st = merge(sd, a.r, a.alpha)
    torch.save(merged, a.dst)
    print("输出: %s · 键数 %d" % (a.dst, len(merged)))
    print("merge 统计:", json.dumps(st, ensure_ascii=False))
    bad = [k for k in merged if "lora" in k.lower() or ".base." in k]
    print("残留包装键:", len(bad))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
