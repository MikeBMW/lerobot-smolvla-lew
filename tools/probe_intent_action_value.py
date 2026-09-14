# -*- coding: utf-8 -*-
"""🎯 probe_intent_action_value.py — 二态意图 (m_local/m_goal) 对动作预测到底有没有用?

背景 (2026-09-14 夜, 接 ①):
  · z_t(192)+δ → 流形 6 维: LOSO R² 全负 (不可辨识, 与 decoder 早先结论一致) ⇒ 该输入选择作废;
  · 几何 z7 路线成立 (数据里 z7 与 predictor 同构口径);
  · data/intent_pairs_v1.npz 有 1799 帧 **(z7, m_local, m_goal, a_expert, stage)** —— 这正是"意图→专家动作"的监督对。

本探针 = 意图口价值的**唯一硬口径**: 同一 z7、同一初始化、同一划分, 只差"喂不喂二态意图":
  off:  z7            → a_expert(3)
  on :  z7 ⊕ [m_local, m_goal] → a_expert(3)
两种划分都给 (口径从宽到严):
  · 5 折随机 (帧级, 乐观上限: 同轨迹相邻帧可能泄漏)
  · 留一阶段 LOSO (严苛: 跨相位泛化, 插入/对位等未见过)
输出: reports/intent_action_value_<ts>.json
用法: OMP_NUM_THREADS=4 ./gui-venv311/bin/python tools/probe_intent_action_value.py
"""
from __future__ import annotations

import json
import os
import sys
import time

import numpy as np

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
DATA = os.path.join(ROOT, "data", "intent_pairs_v1.npz")


def r2(p, g):
    ss = ((g - p) ** 2).sum(0)
    st = ((g - g.mean(0)) ** 2).sum(0)
    return 1.0 - ss / np.maximum(st, 1e-12)


def main() -> int:
    import torch
    from torch import nn
    d = np.load(DATA, allow_pickle=True)
    Z = d["z"].astype(np.float32)
    MI = np.concatenate([d["m_local"], d["m_goal"]], 1).astype(np.float32)     # 二态意图 6 维
    Y = d["a_expert"].astype(np.float32)                                       # 专家动作 3 维
    ST = np.array([str(x) for x in d["stage"]])
    print(f"═══ 二态意图 → 专家动作 价值探针 ═══")
    print(f"数据 {len(Z)} 帧 · z7 {Z.shape} · 意图 {MI.shape} · 动作 {Y.shape}")
    print(f"  意图幅值: |m_local| 中位 {np.median(d['m_local_mag']):.4f} · 动作 std {np.round(Y.std(0),4).tolist()}")
    print(f"  阶段: { {s: int((ST==s).sum()) for s in sorted(set(ST.tolist()))} }")

    def train_eval(Xtr, Ytr, Xte, Yte, dim: int, eps=300, hid=128, seed=7):
        mu, sd = Xtr.mean(0), np.where(Xtr.std(0) < 1e-8, 1.0, Xtr.std(0))
        ym, ys = Ytr.mean(0), np.where(Ytr.std(0) < 1e-8, 1.0, Ytr.std(0))
        Xn, Yn = (Xtr - mu) / sd, (Ytr - ym) / ys
        Xe = (Xte - mu) / sd
        torch.manual_seed(seed)
        net = nn.Sequential(nn.Linear(dim, hid), nn.SiLU(),
                            nn.Linear(hid, hid), nn.SiLU(), nn.Linear(hid, 3))
        opt = torch.optim.AdamW(net.parameters(), lr=2e-3, weight_decay=1e-4)
        sch = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=eps)
        xt = torch.from_numpy(Xn.astype(np.float32)); yt = torch.from_numpy(Yn.astype(np.float32))
        n = len(xt)
        for _ in range(eps):
            net.train()
            perm = torch.randperm(n)
            for i in range(0, n, 256):
                b = perm[i:i + 256]
                opt.zero_grad()
                nn.functional.mse_loss(net(xt[b]), yt[b]).backward()
                opt.step()
            sch.step()
        net.eval()
        with torch.inference_mode():
            p = net(torch.from_numpy(Xe.astype(np.float32))).numpy() * ys + ym
        return r2(p, Yte), float(np.abs(p - Yte).mean())

    rep = {"ts": time.strftime("%F %T"), "n": int(len(Z)), "data": os.path.relpath(DATA, ROOT),
           "m_local_mag_median": float(np.median(d["m_local_mag"])), "schemes": {}}
    rng = np.random.default_rng(0)
    for scheme in ("5fold_random", "leave_one_stage_out"):
        rows = []
        if scheme == "5fold_random":
            idx = rng.permutation(len(Z))
            folds = np.array_split(idx, 5)
        else:
            folds = [np.where(ST == s)[0] for s in sorted(set(ST.tolist()))]
            folds = [f for f in folds if len(f) >= 30]
        for k, te in enumerate(folds):
            te = np.asarray(te)
            tr = np.setdiff1d(np.arange(len(Z)), te)
            if len(te) < 20 or len(tr) < 200:
                continue
            X_off = Z
            X_on = np.concatenate([Z, MI], 1)
            for tag, X in (("off", X_off), ("on", X_on)):
                r2v, mae = train_eval(X[tr], Y[tr], X[te], Y[te], dim=X.shape[1])
                rows.append({"fold": (int(k) if scheme == "5fold_random" else str(sorted(set(ST.tolist()))[k])),
                             "kind": tag, "r2": [round(float(v), 4) for v in r2v],
                             "r2_mean": round(float(np.mean(r2v)), 4), "mae": round(mae, 5)})
        off = [r for r in rows if r["kind"] == "off"]
        on = [r for r in rows if r["kind"] == "on"]
        rep["schemes"][scheme] = {
            "n_folds": len(off),
            "off_r2_mean": round(float(np.mean([r["r2_mean"] for r in off])), 4) if off else None,
            "on_r2_mean": round(float(np.mean([r["r2_mean"] for r in on])), 4) if on else None,
            "dR2": round(float(np.mean([b["r2_mean"] - a["r2_mean"] for a, b in zip(off, on)])), 4)
            if off and on else None,
            "win_folds": int(sum(1 for a, b in zip(off, on) if b["r2_mean"] > a["r2_mean"])),
            "off_mae": round(float(np.mean([r["mae"] for r in off])), 5) if off else None,
            "on_mae": round(float(np.mean([r["mae"] for r in on])), 5) if on else None,
            "rows": rows,
        }
        s = rep["schemes"][scheme]
        print(f"  [{scheme:22s}] n折={s['n_folds']} R²(off)={s['off_r2_mean']} R²(on)={s['on_r2_mean']} "
              f"ΔR²={s['dR2']} 赢折 {s['win_folds']}/{s['n_folds']} MAE {s['off_mae']}→{s['on_mae']}")
    op = os.path.join(ROOT, "reports", f"intent_action_value_{time.strftime('%Y%m%d_%H%M%S')}.json")
    json.dump(rep, open(op, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n→ {os.path.relpath(op, ROOT)}")
    print("判读: ΔR² 明显>0 且赢多折 ⇒ 二态意图口真有用 (可作直连线意图通道); ≈0/负 ⇒ 意图要换表示。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
