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
    ap.add_argument("--ckpt", default=f"{SWM}/checkpoints/stage_moe/moe.pt")
    ap.add_argument("--data", default=f"{SWM}/datasets/v6_holdout_rand.h5")
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--out", default=os.path.join(ROOT, "reports", "moe_holdout_vs_persist.json"))
    a = ap.parse_args()

    import h5py
    import torch
    from transformers import AutoModel
    from stage_moe_backbone import StageMoE, stage_from_ctx
    from joint_unified_backbone import MODEL

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    trunk = AutoModel.from_pretrained(MODEL, dtype=torch.float32).vision_model
    net = StageMoE(trunk, freeze=1).to(dev)
    sd = torch.load(a.ckpt, map_location="cpu", weights_only=False)
    r = net.load_state_dict(sd, strict=False)
    net.eval()
    print(f"🧬 加载 {os.path.basename(a.ckpt)} (missing={len(r.missing_keys)})", flush=True)

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
        px = torch.from_numpy(PX[s:e]).to(dev).float().div(255.0).permute(0, 3, 1, 2)
        o = torch.from_numpy(O[s:e]).to(dev)
        on = torch.from_numpy(ON[s:e]).to(dev)
        sp = torch.from_numpy(SP[s:e]).to(dev)
        mem = torch.zeros(e - s, 13, device=dev)
        with torch.no_grad():
            out = net(px, o, None, mem, sp, hard=True)
        d_moe.append((out["o_hat"] - on).abs().mean(1).cpu().numpy())
        d_per.append((o - on).abs().mean(1).cpu().numpy())
        # 阶段: 真值 = 先验 argmax; 门控 = expert_id
        truth = sp.argmax(1)
        acc += int((out["expert_id"] == truth).sum())
        n += e - s
    dm, dp = np.concatenate(d_moe), np.concatenate(d_per)
    res = {"data": os.path.basename(a.data), "n": int(n), "elapsed_s": round(time.time() - t0, 1),
           "one_step_mae_moe": round(float(dm.mean()), 6),
           "one_step_mae_persist": round(float(dp.mean()), 6),
           "ratio_moe_over_persist": round(float(dm.mean() / dp.mean()), 3),
           "gate_stage_acc_truth_prior": round(acc / max(n, 1), 4)}
    print(json.dumps(res, ensure_ascii=False, indent=1))
    with open(a.out, "w") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)
    print(f"📄 {a.out}")
    print("HOLDOUT_PERSIST_DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
