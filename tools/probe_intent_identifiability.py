# -*- coding: utf-8 -*-
"""🔍 probe_intent_identifiability.py — L4 潜空间到底能不能"吐可用的意图"?

背景 (2026-09-14 夜): 直连线原设计 = z_t(192)+δ → 流形专家预测器 → 流形 6 维。实测 (LOSO 按回合组留出)
**R² 全负** → 与 decoder 早先"z_t→流形6维 LOSO R²≤0, 不可标定"的结论一致。于是要回答一个更基础的问题:

  Q: INTACT 潜空间 z_t 里**有没有任务空间几何** (即"往哪走")? 有 ⇒ 给 L4 加一个**几何意图头**,
     L4 就能吐下层能用的意图 (符合老倪原则); 没有 ⇒ 直连线的意图必须由可观测信号给 (别指望 δ)。

四路对照 (同一批数据, LOSO 按回合组留出, 全部同口径):
  T1  z_t(192)     → Δxyz = goal_p − peg       (任务空间位移, 3 维)    ← 关键: 意图可辨识性
  T2  z_t(192)     → mani6 (6 维)                                     ← 复现"不可标定"
  T3  几何 z_geo(9) → mani6                                           ← 反证: 几何**能**预测流形 (z7 路线的前提)
  T4  线性 ridge probe: z_t → Δxyz                                     ← 排除"只是 MLP 太弱"

数据: reports/intact_pair_*.npz (逐帧同源: z_t / mani6 / obs43 / stage)
      obs 结构 (引擎 43 维): [0:3]=hand x, [3]=grip, [4:7]=v, [7:10]=peg, [10:13]=goal_p, ...
输出: reports/intent_identifiability_<ts>.json
用法: OMP_NUM_THREADS=4 ./gui-venv311/bin/python tools/probe_intent_identifiability.py
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys
import time

import numpy as np

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, os.path.join(ROOT, "src"))


def load():
    Z, M, O, G = [], [], [], []
    for p in sorted(glob.glob(os.path.join(ROOT, "reports", "intact_pair_*.npz"))):
        d = np.load(p, allow_pickle=True)
        if "mani6" not in d.files:
            continue
        m, o, z = d["mani6"], d["obs39"], d["z_t"]
        ok = (np.isfinite(m).all(1) & np.isfinite(z).all(1) & np.isfinite(o).all(1)
              & (np.abs(m).max(1) > 1e-6))
        if not ok.any():
            continue
        b = os.path.basename(p)
        g = ("ft" + re.search(r"ft_seed(\d+)", b).group(1)) if b.startswith("intact_pair_ft_seed") \
            else ("s" + re.search(r"seed(\d+)", b).group(1))
        Z.append(z[ok]); M.append(m[ok]); O.append(o[ok]); G += [g] * int(ok.sum())
    return np.concatenate(Z), np.concatenate(M), np.concatenate(O), np.array(G)


def r2(pred, gt):
    ss = ((gt - pred) ** 2).sum(0)
    st = ((gt - gt.mean(0)) ** 2).sum(0)
    return 1.0 - ss / np.maximum(st, 1e-12)


def main() -> int:
    import torch
    from torch import nn
    Z, M, O, G = load()
    groups = sorted(set(G.tolist()))
    peg, goal_p, hand = O[:, 7:10], O[:, 10:13], O[:, 0:3]
    dz = goal_p - peg                                   # 任务空间位移 (意图的物理定义)
    geo = np.concatenate([peg, goal_p, hand, O[:, 3:4]], 1)   # 9 维几何 (含夹爪)
    print(f"═══ 意图可辨识性探针 ═══  {len(Z)} 帧 / {len(groups)} 组 {groups}")
    print(f"  Δz=goal−peg: 范数 均值 {np.linalg.norm(dz,axis=1).mean():.4f} m · "
          f"分维 std {np.round(dz.std(0),4).tolist()}")

    def mlp_r2(X: np.ndarray, Y: np.ndarray, eps: int = 250, hid: int = 128) -> tuple[np.ndarray, list]:
        """LOSO 按回合组留出; 返回 (逐维 R² 均值, 逐折 R²)。"""
        folds = []
        for g in groups:
            te = G == g
            tr = ~te
            if te.sum() < 20 or tr.sum() < 200:
                continue
            mu, sd = X[tr].mean(0), np.where(X[tr].std(0) < 1e-8, 1.0, X[tr].std(0))
            ym, ys = Y[tr].mean(0), np.where(Y[tr].std(0) < 1e-8, 1.0, Y[tr].std(0))
            Xn = ((X - mu) / sd).astype(np.float32)
            Yn = ((Y - ym) / ys).astype(np.float32)
            torch.manual_seed(7)
            net = nn.Sequential(nn.Linear(X.shape[1], hid), nn.SiLU(),
                                nn.Linear(hid, hid), nn.SiLU(), nn.Linear(hid, Y.shape[1]))
            opt = torch.optim.AdamW(net.parameters(), lr=2e-3, weight_decay=1e-4)
            sch = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=eps)
            xt = torch.from_numpy(Xn[tr]); yt = torch.from_numpy(Yn[tr])
            n = len(xt)
            for _ in range(eps):
                net.train()
                perm = torch.randperm(n)
                for i in range(0, n, 128):
                    b = perm[i:i + 128]
                    opt.zero_grad()
                    nn.functional.mse_loss(net(xt[b]), yt[b]).backward()
                    opt.step()
                sch.step()
            net.eval()
            with torch.inference_mode():
                p = net(torch.from_numpy(Xn[te])).numpy() * ys + ym
            folds.append(r2(p, Y[te]))
        return (np.mean(folds, 0), folds)

    def ridge_r2(X: np.ndarray, Y: np.ndarray, lam: float = 10.0) -> np.ndarray:
        folds = []
        for g in groups:
            te, tr = G == g, ~(G == g)
            if te.sum() < 20 or tr.sum() < 200:
                continue
            mu, sd = X[tr].mean(0), np.where(X[tr].std(0) < 1e-8, 1.0, X[tr].std(0))
            Xn = (X - mu) / sd
            Xa = np.concatenate([Xn[tr], np.ones((int(tr.sum()), 1))], 1)
            W = np.linalg.solve(Xa.T @ Xa + lam * np.eye(Xa.shape[1]), Xa.T @ Y[tr])
            Xb = np.concatenate([Xn[te], np.ones((int(te.sum()), 1))], 1)
            folds.append(r2(Xb @ W, Y[te]))
        return np.mean(folds, 0)

    rep = {"ts": time.strftime("%F %T"), "frames": int(len(Z)), "groups": groups,
           "dz_std": np.round(dz.std(0), 5).tolist(),
           "dz_norm_mean": round(float(np.linalg.norm(dz, axis=1).mean()), 5)}
    for tag, X, Y, names in (
            ("T1_zt→Δxyz(任务空间位移)", Z, dz, ["dpx", "dpy", "dpz"]),
            ("T2_zt→mani6(复现不可标定)", Z, M, ["progress", "risk", "V", "eta", "rem", "dperp"]),
            ("T3_几何(9)→mani6(反证几何可行)", geo, M, ["progress", "risk", "V", "eta", "rem", "dperp"]),
            ("T3b_几何(9)→Δxyz", geo, dz, ["dpx", "dpy", "dpz"])):
        mx, folds = mlp_r2(X, Y)
        rep[tag] = {"r2_per_dim": [round(float(v), 4) for v in mx], "dim_names": names,
                    "r2_mean": round(float(np.mean(mx)), 4), "n_folds": len(folds)}
        print(f"  {tag:34s} R²均值 {np.mean(mx):+.3f}  逐维 {np.round(mx,3).tolist()}")
    rp = ridge_r2(Z, dz)
    rep["T4_ridge_zt→Δxyz(线性对照)"] = {"r2_per_dim": [round(float(v), 4) for v in rp],
                                        "r2_mean": round(float(np.mean(rp)), 4)}
    print(f"  {'T4_ridge(线性) z_t→Δxyz':34s} R²均值 {np.mean(rp):+.3f}  逐维 {np.round(rp,3).tolist()}")
    op = os.path.join(ROOT, "reports", f"intent_identifiability_{time.strftime('%Y%m%d_%H%M%S')}.json")
    json.dump(rep, open(op, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n→ {os.path.relpath(op, ROOT)}")
    print("判读: T1 明显>0 ⇒ L4 可加几何意图头 (z_t→Δxyz) 直接给下层用; T1≈0 且 T3 高 ⇒ "
          "意图改由几何/可观测信号给, 别用 δ。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
