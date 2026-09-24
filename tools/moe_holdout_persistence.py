#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧪 moe_holdout_persistence.py — 把 "MOE 一步预测 vs 持久基线" 在**同源留出集**上再量一次

为什么: 2026-09-24 引擎流实测 MOE o_hat MAE 0.0121 ≫ 持久基线 0.00042 (差 29×)。
若同源留出集上 MOE 反而优于持久基线 ⇒ 差异来自**域**(引擎布局/节拍 vs 采采集分布),
而不是模型本身失效 —— 这是"评估必须训练同源"铁律在引擎侧的第二次实证。

口径: 与 stage_moe_backbone.py 留出评估逐项一致 (2000 样本, rng(0), px float/255, mem=0)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.environ.setdefault("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache")
os.environ.setdefault("OMP_NUM_THREADS", "6")

SWM = "/home/ubuntu/stable-wm-cache"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="moe", choices=["moe", "dense"])
    ap.add_argument("--ckpt", default="")
    ap.add_argument("--data", default=f"{SWM}/datasets/v6_holdout_rand.h5")
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    if not a.ckpt:
        a.ckpt = (f"{SWM}/checkpoints/stage_moe/moe.pt" if a.model == "moe"
                  else f"{SWM}/checkpoints/dense_sub25k_600/unified.pt")
    if not a.out:
        a.out = os.path.join(ROOT, "reports", f"{a.model}_holdout_vs_persist.json")

    import h5py
    import torch
    from transformers import AutoModel
    from stage_moe_backbone import StageMoE, stage_from_ctx
    from joint_unified_backbone import MODEL

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    trunk = AutoModel.from_pretrained(MODEL, dtype=torch.float32).vision_model
    if a.model == "moe":
        net = StageMoE(trunk, freeze=1).to(dev)
    else:
        from joint_unified_backbone import Unified, to_img
        net = Unified(trunk, freeze=1).to(dev)
    sd = torch.load(a.ckpt, map_location="cpu", weights_only=False)
    if isinstance(sd, dict) and "model" in sd and not any(k.startswith("trunk.") for k in sd):
        sd = sd["model"]
    r = net.load_state_dict(sd, strict=False)
    net.eval()
    print(f"🧬 [{a.model}] 加载 {os.path.basename(a.ckpt)} (missing={len(r.missing_keys)})", flush=True)

    f = h5py.File(a.data, "r")
    N = int(f["observation"].shape[0])
    idx = np.sort(np.random.default_rng(0).choice(N, size=min(a.n, N), replace=False))
    O = np.asarray(f["observation"][idx], dtype=np.float32)
    ON = np.asarray(f["observation"][np.minimum(idx + 1, N - 1)], dtype=np.float32)
    PX = np.asarray(f["pixels"][idx], dtype=np.uint8)
    SP = stage_from_ctx(np.asarray(f["skill_ctx"][idx]))
    f.close()

    d_moe, d_per, acc, n = [], [], 0, 0
    t0 = time.time()
    for s in range(0, len(idx), a.batch):
        e = min(len(idx), s + a.batch)
        o = torch.from_numpy(O[s:e]).to(dev)
        on = torch.from_numpy(ON[s:e]).to(dev)
        sp = torch.from_numpy(SP[s:e]).to(dev)
        mem = torch.zeros(e - s, 13, device=dev)
        if a.model == "moe":
            px = torch.from_numpy(PX[s:e]).to(dev).float().div(255.0).permute(0, 3, 1, 2)
            with torch.no_grad():
                out = net(px, o, None, mem, sp, hard=True)
            oh, ex = out["o_hat"], out["expert_id"]
        else:
            px = to_img(PX[s:e]).to(dev)                     # dense 训练侧口径: /255 + (x-0.5)/0.5
            with torch.no_grad():
                out = net(px, o, None, mem)
            oh, ex = out["obs_hat"], None
        d_moe.append((oh - on).abs().mean(1).cpu().numpy())
        d_per.append((o - on).abs().mean(1).cpu().numpy())
        if ex is not None:
            acc += int((ex == sp.argmax(1)).sum())
        n += e - s
    dm, dp = np.concatenate(d_moe), np.concatenate(d_per)
    res = {"model": a.model, "data": os.path.basename(a.data), "n": int(n), "elapsed_s": round(time.time() - t0, 1),
           "one_step_mae_model": round(float(dm.mean()), 6),
           "one_step_mae_moe": round(float(dm.mean()), 6),   # 兼容旧键名
           "one_step_mae_persist": round(float(dp.mean()), 6),
           "ratio_moe_over_persist": round(float(dm.mean() / dp.mean()), 3),
           "gate_stage_acc_truth_prior": (round(acc / max(n, 1), 4) if a.model == "moe" else None)}
    print(json.dumps(res, ensure_ascii=False, indent=1))
    with open(a.out, "w") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)
    print(f"📄 {a.out}")
    print("HOLDOUT_PERSIST_DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
