#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧩➡️📦 把带 LoRA 适配器的训练 ckpt 合并成普通权重 (部署/评测口径)

老倪 (09-22): 「适配或增加 LoRA」—— 训完必须能**用**; LoRA 的部署口径是把低秩增量折进基座:

    W_eff = W_base + (alpha/r) · B @ A

本工具:
  ① 读 LoRA 训练产物 (state_dict 里含 `<prefix>.lora_A` / `<prefix>.lora_B` / `<prefix>.base.weight`)
  ② 逐层折叠 → 输出**与基座同结构**的普通权重 (键名 `<prefix>.weight`), 丢弃 lora_* 与 .base.* 键
  ③ 校验: 输出键集合必须与参考 ckpt (一般是 LoRA 的起点权重) 完全一致 —— 否则拒绝出文件
  ④ 落盘前打印: 折叠层数 / 每层增量范数 / 与基座的最大绝对改动 (证明"真改了哪里")

用法:
  /home/ubuntu/INTACT-JEPA/.venv/bin/python tools/lora_merge_ckpt.py \
      --ckpt <lora_ckpt.pt> --ref <起点ckpt.pt> --out <merged.pt> [--r 8 --alpha 16]
"""
from __future__ import annotations

import argparse
import os
import sys

import torch


def merge(ckpt: str, ref: str | None, out: str, r: int, alpha: int, verbose: bool = True) -> dict:
    sd = torch.load(ckpt, map_location="cpu", weights_only=False)
    if not isinstance(sd, dict):
        raise TypeError(f"ckpt 不是 state_dict: {type(sd)}")
    prefixes = sorted({k[: -len(".lora_A")] for k in sd if k.endswith(".lora_A")})
    if not prefixes:
        raise ValueError("该 ckpt 里没有 lora_A —— 不是 LoRA 训练产物 (或已合并过)")
    scaling = alpha / float(r)
    out_sd, deltas, missing_base = {}, [], []
    lora_keys = set()
    for p in prefixes:
        ka, kb, kw = p + ".lora_A", p + ".lora_B", p + ".base.weight"
        lora_keys |= {ka, kb}
        if kw not in sd:
            missing_base.append(p)
            continue
        w = sd[kw].float()
        A = sd[ka].float()
        B = sd[kb].float()
        if A.shape[0] != r and verbose:
            print(f"   ⚠️ {p}: lora_A 形状 {tuple(A.shape)} 与 --r {r} 不符, 仍按 --alpha/--r 缩放")
        d = scaling * (B @ A)
        out_sd[p + ".weight"] = (w + d).to(sd[kw].dtype)
        if p + ".base.bias" in sd:
            out_sd[p + ".bias"] = sd[p + ".base.bias"]
        deltas.append({"layer": p, "delta_absmax": round(float(d.abs().max()), 6),
                       "delta_norm": round(float(d.norm()), 6)})
    if missing_base:
        raise ValueError(f"{len(missing_base)} 层缺 base.weight (键名不符): {missing_base[:3]}")

    # 非 LoRA 层原样带过 (注意 .base.* 只在被 LoRA 包的层里, 其它层键名不变)
    for k, v in sd.items():
        if k in lora_keys or ".base.weight" in k or ".base.bias" in k:
            continue
        if k.endswith(".lora_A") or k.endswith(".lora_B"):
            continue
        out_sd.setdefault(k, v)

    report = {"ckpt": ckpt, "out": out, "n_layers_merged": len(deltas), "r": r, "alpha": alpha,
              "scaling": scaling, "n_keys_out": len(out_sd),
              "delta_max": max((d["delta_absmax"] for d in deltas), default=0.0),
              "delta_top5": sorted(deltas, key=lambda d: -d["delta_absmax"])[:5]}
    if ref and os.path.exists(ref):
        rsd = torch.load(ref, map_location="cpu", weights_only=False)
        if isinstance(rsd, dict):
            a, b = set(out_sd), set(rsd)
            report["ref"] = ref
            report["keys_only_in_out"] = sorted(a - b)[:5]
            report["keys_only_in_ref"] = sorted(b - a)[:5]
            report["key_set_match"] = (a == b)
            if a != b:
                raise ValueError(f"合并后键集合与参考不一致 (多 {len(a-b)} / 少 {len(b-a)}) → 拒绝出文件")
    torch.save(out_sd, out)
    report["out_mb"] = round(os.path.getsize(out) / 1e6, 1)
    if verbose:
        print(f"✅ 合并 {report['n_layers_merged']} 层 (scaling={scaling}) → {out} ({report['out_mb']} MB)")
        print(f"   最大单层增量 |Δ| = {report['delta_max']:.6f}; 键集合与参考一致: {report.get('key_set_match')}")
        for d in report["delta_top5"]:
            print(f"   · {d['layer']:<58} |Δ|max {d['delta_absmax']:.5f}  ‖Δ‖ {d['delta_norm']:.4f}")
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="LoRA ckpt → 普通权重 (部署口径)")
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--ref", default="", help="参考 ckpt (LoRA 起点), 用于校验键集合")
    ap.add_argument("--out", required=True)
    ap.add_argument("--r", type=int, default=8)
    ap.add_argument("--alpha", type=int, default=16)
    a = ap.parse_args()
    merge(a.ckpt, a.ref or None, a.out, a.r, a.alpha)
    return 0


if __name__ == "__main__":
    sys.exit(main())
