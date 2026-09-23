#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔍 MOE 门控分化诊断 —— 验证 7 个专家是否真按阶段分工（MOE 的核心假设）

若门控没分化（所有阶段路由到同一个专家）→ MOE 退化成单个密集头 = 改造失败。
判据:
  ① 阶段-专家 混淆矩阵: 每个阶段的样本主要路由到哪个专家? 是否**一一对应**?
  ② 路由熵: 每个阶段的平均路由分布熵 (越低越专一)
  ③ 有效专家数: 被实际使用的专家数 (应=7; <7 说明专家饿死)
"""
import argparse
import os
import sys

import numpy as np
import torch
import torch.nn.functional as F

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stage_moe_backbone import STAGES, NS, StageMoE, stage_from_ctx  # noqa: E402
from joint_unified_backbone import MODEL  # noqa: E402

SWM = "/home/ubuntu/stable-wm-cache"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default=f"{SWM}/checkpoints/stage_moe/moe.pt")
    ap.add_argument("--data", default=f"{SWM}/datasets/v6_holdout_rand.h5")
    ap.add_argument("--n", type=int, default=3000)
    a = ap.parse_args()

    import h5py
    from transformers import AutoModel
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    trunk = AutoModel.from_pretrained(MODEL, dtype=torch.float32).vision_model
    net = StageMoE(trunk, freeze=1)
    sd = torch.load(a.ckpt, map_location="cpu", weights_only=False)
    r = net.load_state_dict(sd, strict=False)
    net = net.eval().to(dev)
    print(f"🧬 MOE 已加载: {os.path.basename(os.path.dirname(a.ckpt))} (missing={len(r.missing_keys)})")

    f = h5py.File(a.data, "r")
    N = int(f["observation"].shape[0])
    idx = np.sort(np.random.default_rng(1).choice(N, size=min(a.n, N), replace=False))
    O = np.asarray(f["observation"][idx], dtype=np.float32)
    S = stage_from_ctx(np.asarray(f["skill_ctx"][idx]))          # (n,7) 阶段先验
    P = np.asarray(f["pixels"][idx], dtype=np.uint8)
    f.close()

    # 真阶段标签 = 先验 argmax
    y = S.argmax(1)
    # 路由
    routes, ent = [], []
    with torch.no_grad():
        for b0 in range(0, len(O), 64):
            b1 = min(len(O), b0 + 64)
            px = torch.from_numpy(P[b0:b1]).to(dev).float().div(255).permute(0, 3, 1, 2)
            o = torch.from_numpy(O[b0:b1]).to(dev)
            sp = torch.from_numpy(S[b0:b1]).to(dev)
            out = net(px, o, o, torch.zeros(b1 - b0, 13, device=dev), sp, hard=False)
            g = out["gate"]
            routes.append(g.argmax(1).cpu().numpy())
            ent.append((-(g * (g + 1e-9).log()).sum(1)).cpu().numpy())
    routes = np.concatenate(routes)
    ent = np.concatenate(ent)

    print("\n" + "=" * 78)
    print("🔍 门控分化诊断 (%d 样本 · %s)" % (len(O), os.path.basename(a.data)))
    print("=" * 78)
    print("  ① 阶段 → 专家 混淆矩阵 (行=真阶段, 列=专家, 值=样本数)")
    print("     阶段     " + "".join("E%-5d" % i for i in range(NS)) + "  主导专家  占比")
    ok = 0
    for s in range(NS):
        m = (y == s)
        if m.sum() == 0:
            print("     %-8s  (无样本)" % STAGES[s])
            continue
        row = np.bincount(routes[m], minlength=NS)
        top = int(row.argmax())
        share = row[top] / max(1, m.sum())
        ok += int(share > 0.5)
        print("     %-8s " % STAGES[s] + "".join("%-6d" % v for v in row) +
              "  E%-6d  %5.1f%%" % (top, share * 100))
    used = len(set(routes.tolist()))
    print("\n  ② 路由熵: 平均 %.3f (最大 %.3f; 越低越专一)" % (ent.mean(), np.log(NS)))
    print("  ③ 有效专家数: **%d / %d** %s" % (used, NS, "✅ 全用上" if used == NS else "⚠️ 有专家饿死"))
    print("  ④ 阶段-专家一一对应率: **%d/%d** %s" % (ok, NS, "✅ 分化成立" if ok >= NS - 1 else "❌ 未分化"))
    print("=" * 78)
    print("判据: 一一对应率 ≥6/7 且 有效专家=7 → MOE 分工成立（非退化）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
