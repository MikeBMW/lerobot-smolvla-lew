# -*- coding: utf-8 -*-
"""🧠 train_stop_head.py — 训练"交权/停"判据 (⑤ m_stop) + LOSO 验证 (2026-09-15)

数据: data/stop_signal_v1.npz (collect_stop_data.py, 每帧 32 维 / 标签=该局最终失败)
口径: **留一 seed 交叉验证** (LOSO) — 不许用同一 seed 的帧同时训练与评估;
     报 AUC + 准确率, 并给"恒预测失败"的平凡基线对照 (失败帧占比 0.85 → 准确率不可信, 看 AUC)。
门槛: LOSO AUC ≥ 0.75 才认为判据有信息量; 否则如实报负结果, 不接线。
用法: gui-venv311/bin/python tools/train_stop_head.py
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
D = os.path.join(ROOT, "data", "stop_signal_v1.npz")
OUT = os.path.join(ROOT, "models", "stop_head_v1.pt")
REP = os.path.join(ROOT, "reports", "stop_head_train_20260915.json")


def auc(y, s):
    y = np.asarray(y, float); s = np.asarray(s, float)
    pos, neg = s[y > 0.5], s[y <= 0.5]
    if pos.size == 0 or neg.size == 0:
        return float("nan")
    order = np.argsort(s)
    ranks = np.empty_like(order, float)
    ranks[order] = np.arange(1, s.size + 1)
    # 并列取平均秩
    _, inv, cnt = np.unique(s, return_inverse=True, return_counts=True)
    for i, c in enumerate(cnt):
        if c > 1:
            m = inv == i
            ranks[m] = ranks[m].mean()
    return float((ranks[y > 0.5].sum() - pos.size * (pos.size + 1) / 2) / (pos.size * neg.size))


def main() -> int:
    import torch
    import torch.nn as nn
    z = np.load(D, allow_pickle=True)
    X, y, seed = z["X"], z["y"], z["seed"]
    print(f"数据 {X.shape} · 失败帧占比 {y.mean():.3f} · seeds {sorted(set(seed.tolist()))}")
    seeds = sorted(set(int(s) for s in seed.tolist()))
    rows = []
    oof = np.zeros(len(y))
    for ho in seeds:
        tr = seed != ho; te = seed == ho
        mu, sd = X[tr].mean(0), X[tr].std(0) + 1e-6
        Xtr = torch.tensor((X[tr] - mu) / sd, dtype=torch.float32)
        ytr = torch.tensor(y[tr], dtype=torch.float32).unsqueeze(1)
        Xte = torch.tensor((X[te] - mu) / sd, dtype=torch.float32)
        torch.manual_seed(0)
        net = nn.Sequential(nn.Linear(X.shape[1], 64), nn.ReLU(), nn.Linear(64, 32), nn.ReLU(),
                            nn.Linear(32, 1))
        opt = torch.optim.Adam(net.parameters(), lr=2e-3, weight_decay=1e-4)
        pw = torch.tensor([(y[tr] <= 0.5).sum() / max(1, (y[tr] > 0.5).sum())], dtype=torch.float32)
        lossf = nn.BCEWithLogitsLoss(pos_weight=pw)
        for _ in range(400):
            opt.zero_grad(); lossf(net(Xtr), ytr).backward(); opt.step()
        with torch.no_grad():
            p = torch.sigmoid(net(Xte)).numpy().ravel()
        oof[te] = p
        a = auc(y[te], p)
        acc = float(((p > 0.5) == (y[te] > 0.5)).mean())
        base = float(max((y[te] > 0.5).mean(), (y[te] <= 0.5).mean()))
        rows.append({"seed": ho, "auc": round(a, 4), "acc": round(acc, 4),
                     "trivial_acc": round(base, 4), "n": int(te.sum()),
                     "n_fail": int((y[te] > 0.5).sum())})
        print(f"  留出 seed{ho}: AUC={a:.4f} acc={acc:.3f} (平凡基线 {base:.3f}) n={int(te.sum())}")
    aucs = [r["auc"] for r in rows if not np.isnan(r["auc"])]
    print(f"\nLOSO AUC 均值 {np.mean(aucs):.4f} · 中位 {np.median(aucs):.4f} · "
          f"合并 OOF AUC {auc(y, oof):.4f}")
    ok = float(np.mean(aucs)) >= 0.75
    print(f"门槛 (≥0.75): {'通过 → 可接线' if ok else '未通过 → **不接线**, 如实报负结果'}")
    if ok:
        mu, sd = X.mean(0), X.std(0) + 1e-6
        Xa = torch.tensor((X - mu) / sd, dtype=torch.float32)
        ya = torch.tensor(y, dtype=torch.float32).unsqueeze(1)
        torch.manual_seed(0)
        net = nn.Sequential(nn.Linear(X.shape[1], 64), nn.ReLU(), nn.Linear(64, 32), nn.ReLU(),
                            nn.Linear(32, 1))
        opt = torch.optim.Adam(net.parameters(), lr=2e-3, weight_decay=1e-4)
        pw = torch.tensor([(y <= 0.5).sum() / max(1, (y > 0.5).sum())], dtype=torch.float32)
        lossf = nn.BCEWithLogitsLoss(pos_weight=pw)
        for _ in range(400):
            opt.zero_grad(); lossf(net(Xa), ya).backward(); opt.step()
        torch.save({"state_dict": net.state_dict(), "mu": mu, "sd": sd,
                    "feat_dim": int(X.shape[1]), "loso_auc_mean": float(np.mean(aucs)),
                    "label": "1=该局最终失败", "data": os.path.basename(D)}, OUT)
        print(f"✅ 权重 → {OUT}")
    json.dump({"ts": "2026-09-15", "data": os.path.basename(D), "n": int(len(y)),
               "fail_ratio": float(y.mean()), "loso": rows,
               "loso_auc_mean": float(np.mean(aucs)), "oof_auc": auc(y, oof),
               "gate_0p75_passed": bool(ok),
               "weights": OUT if ok else None}, open(REP, "w"), ensure_ascii=False, indent=1)
    print(f"→ {REP}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
