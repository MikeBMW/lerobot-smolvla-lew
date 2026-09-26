#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cog_retarget_experiment.py — ①-1 认知头"换靶子"实验 (多步 K=5/10 + 事件级)

背景 (已定档的负结果): 认知头原来预测「下一帧 39D 观测」, 在**同源留出集**上输给持久基线
  (dense_holdout_vs_persist.json: 一步 MAE 0.015417 vs 持久 0.002972 = 5.19×; 引擎流 29×)
  ⇒ 结论是"靶子定错", 不是模型不行。

本实验换靶子, 且**同表同口径**给出结论:
  · 多步: K ∈ {1,5,10} 预测 obs[t+K] (39D); 基线 = 持久(obs[t]) 与 匀速(obs[t]+Δobs)
  · 事件级(二分类, 视界 H ∈ {5,10}): ①到达事件(手到目标) ②夹爪闭合事件 ③阶段切换(子目标跳变)
    基线 = 平凡基线(恒报"无事件")
  · 划分: 按 variant_id 留出 (80 训练 / 20 留出, 同源不跨集) —— 老倪口径: 口径=训练同源零回退
  · 判据: 模型必须**赢同源基线**, 否则如实写"无提升"
数据: /home/ubuntu/stable-wm-cache/datasets/l5_v6_sub10k.h5 (100 段 × 100 帧, 引擎域, obs39/skill_ctx24)
用法: gui-venv311/bin/python tools/cog_retarget_experiment.py [--epochs 200] [--seeds 3]
"""
from __future__ import annotations

import argparse
import json
import os
import time

import numpy as np

ROOT = "/home/ubuntu/zmax_rel"
DATA = "/home/ubuntu/stable-wm-cache/datasets/l5_v6_sub10k.h5"
REPORTS = os.path.join(ROOT, "reports")


def load_episodes(path):
    """→ (eps: list of dict(obs,ctx,act,goal), meta) 按 variant_id 分段"""
    import h5py
    with h5py.File(path, "r") as f:
        obs = np.asarray(f["observation"], dtype=np.float32)
        ctx = np.asarray(f["skill_ctx"], dtype=np.float32) if "skill_ctx" in f else np.zeros((len(obs), 0), np.float32)
        act = np.asarray(f["action"], dtype=np.float32) if "action" in f else np.zeros((len(obs), 0), np.float32)
        goal = np.asarray(f["goal"], dtype=np.float32) if "goal" in f else obs.copy()
        vid = np.asarray(f["variant_id"]) if "variant_id" in f else np.zeros(len(obs), np.int64)
    eps = []
    for v in np.unique(vid):
        m = (vid == v)
        eps.append({"v": int(v), "obs": obs[m], "ctx": ctx[m], "act": act[m], "goal": goal[m]})
    eps.sort(key=lambda e: e["v"])
    return eps


def build_multistep(eps, K):
    """在段内取 (t, t+K) 对 → X=obs[t], Y=obs[t+K] (不跨段)"""
    X, Y, V = [], [], []
    for e in eps:
        L = len(e["obs"])
        if L <= K:
            continue
        X.append(e["obs"][:-K])
        Y.append(e["obs"][K:])
        V.append(np.full(L - K, e["v"]))
    if not X:
        return np.zeros((0, 39), np.float32), np.zeros((0, 39), np.float32), np.zeros(0)
    return np.concatenate(X), np.concatenate(Y), np.concatenate(V)


def build_event(eps, kind, H, tau=None, dthr=None):
    """段内事件标签: 未来 H 帧内是否发生 (t 处) → X=obs[t], y∈{0,1}"""
    X, y, V = [], [], []
    for e in eps:
        obs, goal = e["obs"], e["goal"]
        L = len(obs)
        if L <= H + 2:
            continue
        hand, grip = obs[:, 0:3], obs[:, 3]
        gsub = goal[:, 36:39] if goal.shape[1] >= 39 else goal[:, -3:]
        d_goal = np.linalg.norm(hand - goal[:, 10:13], axis=1) if goal.shape[1] >= 13 else np.zeros(L)
        d_sub = np.linalg.norm(np.diff(gsub, axis=0), axis=1) if L > 1 else np.zeros(0)
        if kind == "gripper_close":          # 真事件: 夹爪下穿 0.5 (每段一次)
            ev = np.zeros(L, bool)
            ev[1:] = (obs[1:, 3] < 0.5) & (obs[:-1, 3] >= 0.5)
        elif kind == "reach_z":              # 真事件: 手 z 进入该段末值 ±2mm (插入到位)
            z_end = float(obs[-1, 2])
            ev = np.abs(obs[:, 2] - z_end) < 0.002
        elif kind == "move_hand":            # 真事件: 手位移 > 1mm (在动)
            dh = np.linalg.norm(np.diff(hand, axis=0), axis=1)
            ev = np.zeros(L, bool)
            ev[1:] = dh > 0.001
        else:                                # 保留但标注: 子目标跳变 (本数据几乎不存在)
            ev = np.zeros(L, bool)
            ev[1:] = d_sub > (dthr if dthr is not None else 1e-6)
        lab = np.zeros(L, bool)
        for t in range(L - H):
            lab[t] = bool(ev[t + 1:t + 1 + H].any())
        keep = slice(0, L - H)
        X.append(obs[keep])
        y.append(lab[keep].astype(np.float32))
        V.append(np.full(L - H, e["v"]))
    if not X:
        return np.zeros((0, 39), np.float32), np.zeros(0, np.float32), np.zeros(0)
    return np.concatenate(X), np.concatenate(y), np.concatenate(V)


def auc_of(pred, y):
    """无 sklearn 依赖的秩和 AUC"""
    order = np.argsort(pred)
    ranks = np.empty(len(pred), float)
    ranks[order] = np.arange(1, len(pred) + 1)
    npos, nneg = float(y.sum()), float(len(y) - y.sum())
    if npos == 0 or nneg == 0:
        return float("nan")
    return float((ranks[y == 1].sum() - npos * (npos + 1) / 2) / (npos * nneg))


def train_mlp(Xtr, Ytr, Xte, task, epochs=200, seed=0, ctx_tr=None, ctx_te=None):
    """小 MLP (128-128) 在 GPU 上训练; 回归=39维输出, 分类=1 logit"""
    import torch
    torch.manual_seed(seed)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    if ctx_tr is not None and getattr(ctx_tr, "shape", (0, 0))[1] > 0:
        Xtr = np.concatenate([Xtr, ctx_tr], axis=1)
    if ctx_te is not None and getattr(ctx_te, "shape", (0, 0))[1] > 0:
        Xte = np.concatenate([Xte, ctx_te], axis=1)
    x = torch.tensor(Xtr, device=dev)
    xt = torch.tensor(Xte, device=dev)
    out_dim = 39 if task == "reg" else 1
    net = torch.nn.Sequential(torch.nn.Linear(x.shape[1], 128), torch.nn.ReLU(),
                              torch.nn.Linear(128, 128), torch.nn.ReLU(),
                              torch.nn.Linear(128, out_dim)).to(dev)
    opt = torch.optim.Adam(net.parameters(), lr=1e-3)
    yt = torch.tensor(Ytr, device=dev)
    lossf = torch.nn.MSELoss() if task == "reg" else torch.nn.BCEWithLogitsLoss()
    net.train()
    for _ in range(epochs):
        opt.zero_grad()
        out = net(x)
        loss = lossf(out, yt if task == "reg" else yt.view(-1, 1))
        loss.backward()
        opt.step()
    net.eval()
    with torch.no_grad():
        pred = net(xt)
    return (pred.cpu().numpy() if task == "reg" else pred.view(-1).cpu().numpy()), dev


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=DATA)
    ap.add_argument("--epochs", type=int, default=200)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--holdout-frac", type=float, default=0.2)
    ap.add_argument("--cross", default="", help="跨域评测数据集 (训练域→该域, ①-3)")
    a = ap.parse_args()

    eps = load_episodes(a.data)
    nv = len(eps)
    rng = np.random.RandomState(0)
    perm = rng.permutation(nv)
    n_ho = max(1, int(round(nv * a.holdout_frac)))
    ho = set(perm[:n_ho].tolist())
    tr_eps = [e for e in eps if e["v"] not in ho]
    ho_eps = [e for e in eps if e["v"] in ho]
    print("数据: %s | %d 段 (训练 %d / 留出 %d) | 每段帧数中位 %d" %
          (os.path.basename(a.data), nv, len(tr_eps), len(ho_eps), int(np.median([len(e["obs"]) for e in eps]))))

    res = {"ts": time.strftime("%F %T"), "data": os.path.basename(a.data), "n_variants": nv,
           "train_variants": len(tr_eps), "holdout_variants": len(ho_eps), "epochs": a.epochs, "seeds": a.seeds,
           "multistep": {}, "events": {}}

    # ── A) 多步 ──
    print("\n=== A) 多步预测 (同表: 模型 vs 持久 vs 匀速) ===")
    print("  %-6s %-10s %-12s %-12s %-12s %s" % ("K", "n_test", "模型R²", "持久R²", "匀速R²", "判据"))
    for K in (1, 5, 10):
        Xtr, Ytr, Vtr = build_multistep(tr_eps, K)
        Xte, Yte, Vte = build_multistep(ho_eps, K)
        if len(Xte) == 0:
            continue
        varmean = float(np.mean((Yte - Yte.mean(0)) ** 2))
        preds = []
        dev = "-"
        for s in range(a.seeds):
            p, dev = train_mlp(Xtr, Ytr, Xte, "reg", epochs=a.epochs, seed=s)
            preds.append(p)
        pm = np.mean(preds, axis=0)
        # 基线: 持久 = obs[t] (即该样本的输入); 匀速 = obs[t] + (obs[t]-obs[t-1])
        pers = Xte.copy()
        vel = []
        for e in ho_eps:
            L = len(e["obs"])
            if L <= K:
                continue
            o = e["obs"]
            d = np.diff(o, axis=0, prepend=o[:1])
            vel.append(o[:-K] + K * d[:-K])
        vel = np.concatenate(vel) if vel else pers
        r2 = lambda p, y, ym: float(1 - np.mean((p - y) ** 2) / max(float(np.mean((y - ym) ** 2)), 1e-12))
        r2m, r2p, r2v = r2(pm, Yte, Yte.mean(0)), r2(pers, Yte, Yte.mean(0)), r2(vel, Yte, Yte.mean(0))
        # ★ 有效子空间口径: 只用训练集里真有变化的维 (43D 里常量维会把基线抬到近满分, 不公平)
        sd = Xtr.std(0)
        sig = np.where(sd > 1e-6)[0]
        if len(sig) == 0:
            sig = np.arange(min(7, Yte.shape[1]))
        y2, pm2, ps2, vl2 = Yte[:, sig], pm[:, sig], pers[:, sig], vel[:, sig]
        r2m2, r2p2, r2v2 = r2(pm2, y2, y2.mean(0)), r2(ps2, y2, y2.mean(0)), r2(vl2, y2, y2.mean(0))
        win = r2m2 > max(r2p2, r2v2)
        res["multistep"]["K%d" % K] = {"n_test": int(len(Xte)), "sig_dims": len(sig),
                                       "r2_model": round(r2m, 4), "r2_persist": round(r2p, 4),
                                       "r2_vel": round(r2v, 4), "r2_model_sig": round(r2m2, 4),
                                       "r2_persist_sig": round(r2p2, 4), "r2_vel_sig": round(r2v2, 4),
                                       "mae_model": round(float(np.mean(np.abs(pm - Yte))), 6),
                                       "mae_persist": round(float(np.mean(np.abs(pers - Yte))), 6),
                                       "mae_vel": round(float(np.mean(np.abs(vel - Yte))), 6),
                                       "model_wins": bool(win), "device": dev}
        print("  %-6d %-10d %-12.4f %-12.4f %-12.4f %s   [有效维 %d 维: 模型 %.4f / 持久 %.4f / 匀速 %.4f]" %
              (K, len(Xte), r2m, r2p, r2v, "✅ 赢基线" if win else "❌ 输基线",
               len(sig), r2m2, r2p2, r2v2))

    # ── B) 事件级 ──
    print("\n=== B) 事件级真事件 (视界 H; 平凡基线=恒报无事件) ===")
    print("  %-14s %-6s %-9s %-12s %-12s %s" % ("事件", "H", "正例率", "模型AUC", "模型acc", "判据"))
    tr_obs = np.concatenate([e["obs"] for e in tr_eps])
    grip_med = float(np.median(tr_obs[:, 3]))
    d_goal_tr = np.linalg.norm(tr_obs[:, 0:3] - np.concatenate([e["goal"][:, 10:13] for e in tr_eps]), axis=1)
    tau = float(np.percentile(d_goal_tr, 10))
    for kind, dthr in (("gripper_close", grip_med), ("reach_z", None), ("move_hand", None)):
        for H in (5, 10):
            Xtr2, ytr2, _ = build_event(tr_eps, kind, H, tau=tau, dthr=dthr)
            Xte2, yte2, _ = build_event(ho_eps, kind, H, tau=tau, dthr=dthr)
            if len(Xte2) == 0 or yte2.sum() == 0 or yte2.sum() == len(yte2):
                print("  %-14s %-6d  (留出集无正/负例, 跳过)" % (kind, H))
                continue
            aucs, accs = [], []
            for s in range(a.seeds):
                p, dev = train_mlp(Xtr2, ytr2, Xte2, "cls", epochs=a.epochs, seed=s)
                # AUC (无 sklearn 依赖, 手算秩和)
                order = np.argsort(p)
                ranks = np.empty(len(p), float)
                ranks[order] = np.arange(1, len(p) + 1)
                npos, nneg = float(yte2.sum()), float(len(yte2) - yte2.sum())
                auc = (ranks[yte2 == 1].sum() - npos * (npos + 1) / 2) / (npos * nneg)
                aucs.append(auc)
                accs.append(float(((p > 0.0).astype(np.float32) == yte2).mean()))
            auc_m, acc_m = float(np.mean(aucs)), float(np.mean(accs))
            trivial_acc = float(max(yte2.mean(), 1 - yte2.mean()))
            win = (auc_m > 0.5 + 0.02) and (acc_m > trivial_acc)
            res["events"]["%s_H%d" % (kind, H)] = {"n_test": int(len(Xte2)), "pos_rate": round(float(yte2.mean()), 4),
                                                   "auc_model": round(auc_m, 4), "acc_model": round(acc_m, 4),
                                                   "acc_trivial": round(trivial_acc, 4), "model_wins": bool(win),
                                                   "thr": dthr}
            print("  %-14s %-6d %-9.3f %-12.4f %-12.4f %s" %
                  (kind, H, float(yte2.mean()), auc_m, acc_m, "✅ 赢平凡基线" if win else "❌ 无提升"))

    # ── C) 跨域复评 (①-3): 训练域 → --cross 域 ──
    if a.cross and os.path.isfile(a.cross):
        print("\n=== C) 跨域复评: 训练域 %s → 评测域 %s ===" %
              (os.path.basename(a.data), os.path.basename(a.cross)))
        ceps = load_episodes(a.cross)
        res["cross"] = {"train": os.path.basename(a.data), "test": os.path.basename(a.cross),
                        "events": {}}
        print("  %-14s %-6s %-10s %-12s %-12s %s" % ("事件", "H", "测试域正例率", "域内AUC", "跨域AUC", "判据"))
        for kind in ("gripper_close", "reach_z", "move_hand"):
            for H in (5, 10):
                Xtr3, ytr3, _ = build_event(tr_eps, kind, H, tau=tau, dthr=grip_med)
                Xte3, yte3, _ = build_event(ceps, kind, H, tau=tau, dthr=grip_med)
                if len(yte3) == 0 or yte3.sum() == 0 or yte3.sum() == len(yte3) or ytr3.sum() == 0:
                    print("  %-14s %-6d (测试域无正/负例或无正样例, 跳过)" % (kind, H))
                    continue
                aucs_in, aucs_x = [], []
                for sd_i in range(a.seeds):
                    # 域内基线: 让 20% 该域自身数据作留出
                    rng2 = np.random.RandomState(sd_i)
                    cv = sorted(set(c["v"] for c in ceps))
                    ho2 = set(rng2.permutation(cv)[:max(1, len(cv) // 5)].tolist())
                    in_tr = [c for c in ceps if c["v"] not in ho2]
                    in_te = [c for c in ceps if c["v"] in ho2]
                    Xi, yi, _ = build_event(in_tr, kind, H, tau=tau, dthr=grip_med)
                    Xj, yj, _ = build_event(in_te, kind, H, tau=tau, dthr=grip_med)
                    if len(Xj) and yj.sum() and yj.sum() < len(yj):
                        pi, _ = train_mlp(Xi, yi, Xj, "cls", epochs=a.epochs, seed=sd_i)
                        aucs_in.append(auc_of(pi, yj))
                    px_, _ = train_mlp(Xtr3, ytr3, Xte3, "cls", epochs=a.epochs, seed=sd_i)
                    aucs_x.append(auc_of(px_, yte3))
                ai = float(np.mean(aucs_in)) if aucs_in else float("nan")
                ax = float(np.mean(aucs_x))
                win = (ax > 0.5 + 0.02)
                res["cross"]["events"]["%s_H%d" % (kind, H)] = {
                    "pos_rate_test": round(float(yte3.mean()), 4), "auc_in_domain": round(ai, 4),
                    "auc_cross_domain": round(ax, 4), "cross_wins": bool(win)}
                print("  %-14s %-6d %-10.3f %-12.4f %-12.4f %s" %
                      (kind, H, float(yte3.mean()), ai, ax, "⚠️ 跨域仍>0.52" if win else "❌ 跨域失效(≤0.52)"))
        xs = [k for k, v in res["cross"]["events"].items() if v["cross_wins"]]
        print("  跨域结论: 赢的靶子 %s (空=事件头跨域失效, 需域内重训/域适应)" % (xs or "无"))
        res.setdefault("verdict", {})["cross_win"] = xs

    # ── 结论 ──
    ms_win = [k for k, v in res["multistep"].items() if v["model_wins"]]
    ev_win = [k for k, v in res["events"].items() if v["model_wins"]]
    res["verdict"] = {
        "multistep_win": ms_win, "event_win": ev_win,
        "conclusion": ("多步: 赢基线 %s; 事件级: 赢平凡基线 %s" % (ms_win or "无", ev_win or "无"))}
    os.makedirs(REPORTS, exist_ok=True)
    out = os.path.join(REPORTS, "cog_retarget_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    json.dump(res, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n结论: 多步赢基线 %s · 事件级赢平凡基线 %s" % (ms_win or "无", ev_win or "无"))
    print("取证: %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
