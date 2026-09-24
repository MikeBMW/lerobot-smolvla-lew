#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📊 按阶段拆解误差 —— 检验"阶段专家"核心假设

假设: 阶段分工应让**接触段**(下降/抓取/插入)误差显著低于密集版
     （因为一个密集头要同时拟合视觉认知与接触动力学）
判据: 若 MOE-prior 在接触段的误差 < 密集版 → 假设成立; 否则不成立

对比三个模型（同数据同留出）:
  · 密集 L4      (checkpoints/unified_orch_L4/unified.pt)
  · MOE-soft     (checkpoints/stage_moe_orch/moe.pt)   门控坍缩(容量版)
  · MOE-prior    (checkpoints/stage_moe_prior/moe.pt)  7/7 阶段分工
"""
import argparse
import os
import sys

import numpy as np
import torch
import torch.nn.functional as F

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stage_moe_backbone import STAGES, NS, StageMoE, stage_from_ctx  # noqa: E402
from joint_unified_backbone import MODEL, Unified  # noqa: E402

SWM = "/home/ubuntu/stable-wm-cache"
CONTACT = [2, 3, 6]          # 下降/抓取/插入 = 接触段
HOLDOUT = f"{SWM}/datasets/v6_holdout_rand.h5"


def load_holdout(n=3000, chunk=7):
    import h5py
    f = h5py.File(HOLDOUT, "r")
    N = int(f["observation"].shape[0])
    idx = np.sort(np.random.default_rng(0).choice(N, size=min(n, N), replace=False))
    O = np.asarray(f["observation"][idx], dtype=np.float32)
    A = np.stack([np.stack([np.asarray(f["action"][min(int(q) + k, N - 1)], dtype=np.float32)
                            for k in range(chunk)]) for q in idx])
    S = stage_from_ctx(np.asarray(f["skill_ctx"][idx]))
    P = np.asarray(f["pixels"][idx], dtype=np.uint8)
    f.close()
    return O, A, S, P


def eval_moe(ckpt, O, A, S, P, dev, route="prior"):
    from transformers import AutoModel
    trunk = AutoModel.from_pretrained(MODEL, dtype=torch.float32).vision_model
    net = StageMoE(trunk, freeze=1)
    net.load_state_dict(torch.load(ckpt, map_location="cpu", weights_only=False), strict=False)
    net = net.eval().to(dev)
    eo = np.zeros(len(O)); ea = np.zeros(len(O))
    with torch.no_grad():
        for b0 in range(0, len(O), 64):
            b1 = min(len(O), b0 + 64)
            px = torch.from_numpy(P[b0:b1]).to(dev).float().div(255).permute(0, 3, 1, 2)
            o = torch.from_numpy(O[b0:b1]).to(dev)
            sp = torch.from_numpy(S[b0:b1]).to(dev)
            out = net(px, o, o, torch.zeros(b1 - b0, 13, device=dev), sp, hard=False, route=route)
            eo[b0:b1] = (out["o_hat"] - o).abs().mean(1).cpu().numpy()
            ha = torch.from_numpy(A[b0:b1]).to(dev)
            ea[b0:b1] = (out["u"] - ha).abs().mean((1, 2)).cpu().numpy()
    del net
    torch.cuda.empty_cache()
    return eo, ea


def eval_dense(ckpt, O, A, S, P, dev):
    from transformers import AutoModel
    trunk = AutoModel.from_pretrained(MODEL, dtype=torch.float32).vision_model
    net = Unified(trunk, freeze=1)
    net.load_state_dict(torch.load(ckpt, map_location="cpu", weights_only=False), strict=False)
    net = net.eval().to(dev)
    eo = np.zeros(len(O)); ea = np.zeros(len(O))
    with torch.no_grad():
        for b0 in range(0, len(O), 64):
            b1 = min(len(O), b0 + 64)
            px = torch.from_numpy(P[b0:b1]).to(dev).float().div(255).permute(0, 3, 1, 2)
            o = torch.from_numpy(O[b0:b1]).to(dev)
            ha = torch.from_numpy(A[b0:b1]).to(dev)
            # Unified.forward(img, obs, act, mem) —— 评估 L4 时 act 传 0(避免泄漏)
            out = net(px, o, torch.zeros_like(ha), torch.zeros(b1 - b0, 13, device=dev))
            eo[b0:b1] = (out["obs_hat"] - o).abs().mean(1).cpu().numpy()
            ea[b0:b1] = (out["u"] - ha).abs().mean((1, 2)).cpu().numpy()
    del net
    torch.cuda.empty_cache()
    return eo, ea


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=3000)
    a = ap.parse_args()
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    O, A, S, P = load_holdout(a.n)
    y = S.argmax(1)
    print("=" * 84)
    print("📊 按阶段拆解误差 (n=%d · 接触段=%s)" % (len(O), ",".join(STAGES[i] for i in CONTACT)))
    print("=" * 84)

    models = [
        ("密集 L4", lambda: eval_dense(f"{SWM}/checkpoints/unified_orch_L4/unified.pt", O, A, S, P, dev)),
        ("MOE-soft(坍缩)", lambda: eval_moe(f"{SWM}/checkpoints/stage_moe_orch/moe.pt", O, A, S, P, dev, "soft")),
        ("MOE-prior(分工)", lambda: eval_moe(f"{SWM}/checkpoints/stage_moe_prior/moe.pt", O, A, S, P, dev, "prior")),
    ]
    res = {}
    for nm, fn in models:
        try:
            eo, ea = fn()
            res[nm] = (eo, ea)
            print("  ✅ %-16s 全局: 观测 %.4f 动作 %.4f" % (nm, eo.mean(), ea.mean()))
        except Exception as e:                                          # noqa: BLE001
            print("  ❌ %-16s %s: %s" % (nm, type(e).__name__, str(e)[:70]))

    print("\n  按阶段 (观测误差 / 动作误差):")
    hdr = "  %-10s" % "阶段" + "".join("%-22s" % nm for nm, _ in models)
    print(hdr)
    for s in range(NS):
        m = (y == s)
        if m.sum() == 0:
            continue
        row = "  %-10s" % STAGES[s]
        for nm, _ in models:
            if nm in res:
                row += "%-22s" % ("%.4f / %.4f" % (res[nm][0][m].mean(), res[nm][1][m].mean()))
            else:
                row += "%-22s" % "-"
        print(row + ("   ← 接触段" if s in CONTACT else ""))

    if len(res) >= 2 and "密集 L4" in res:
        print("\n  接触段汇总 (相对密集版的改善):")
        mc = np.isin(y, CONTACT)
        for nm, _ in models:
            if nm not in res or nm == "密集 L4":
                continue
            d_o = res["密集 L4"][0][mc].mean() - res[nm][0][mc].mean()
            d_a = res["密集 L4"][1][mc].mean() - res[nm][1][mc].mean()
            print("    %-16s 观测 %+.5f (%+.1f%%) · 动作 %+.5f (%+.1f%%)" %
                  (nm, d_o, 100 * d_o / max(1e-9, res["密集 L4"][0][mc].mean()),
                   d_a, 100 * d_a / max(1e-9, res["密集 L4"][1][mc].mean())))
        print("\n  判据: 分工版在**接触段**改善 > 容量版 → '阶段分工'假设成立")


if __name__ == "__main__":
    main()
