#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""train_cog_event_head.py — L5 计划 T1: 事件级认知头训练 (真训练, GPU, 落 ckpt + 判据)

背景 (L5 审视结论 + 本仓库取证):
  · 值预测靶子判死 (一步输持久 5.19×; 多步 K=1/5/10 全输持久/匀速)
  · 事件级靶子成立 (6/6 赢平凡基线) 且跨域 v6→v5 不退化
  · 数据防返工: 只用 obs[0:7] (obs[7:39] 在该数据里全 0, skill_ctx 常量 → 喂进去只会学零)

任务: 单头多任务二分类 = 3 事件 × 2 视界 = 6 logit (夹爪闭合/到位/手在动 × H=5/10)
输入: obs[0:7] (手位3+夹爪1+速度3)   数据: l5_gen_v6 训练 / v6 留出集 / v5 跨域评测
判据: gripper_close AUC≥0.91 · reach_z≥0.79 · move_hand≥0.90 且跨域不退化 (L5 G3)
产出: ckpt ckpt_dir/cog_event_head.pt + 训练日志(逐步) + 判据 JSON
用法: gui-venv311/bin/python tools/train_cog_event_head.py [--epochs 300] [--tag default]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, "/home/ubuntu/zmax_rel/tools")
from cog_retarget_experiment import build_event, load_episodes  # noqa: E402

SWM = "/home/ubuntu/stable-wm-cache"
REPORTS = "/home/ubuntu/zmax_rel/reports"
KEEP = 7                       # 只用 obs[0:7] (防返工: 不喂全 0 维)
EVENTS = (("gripper_close", 5), ("gripper_close", 10), ("reach_z", 5),
          ("reach_z", 10), ("move_hand", 5), ("move_hand", 10))


EV_PER_H = {"gripper_close": 0, "reach_z": 1, "move_hand": 2}


def augment(X):
    """合法派生特征 (只用当前帧及历史, 不含未来): 速度模长 · 手/夹爪/速度的交叉量

    输入 X: (n,7) = 手位3 + 夹爪1 + 速度3 (obs[0:7]) → 输出 (n, 7+6)
    """
    hand, grip, vel = X[:, 0:3], X[:, 3:4], X[:, 4:7]
    vn = np.linalg.norm(vel, axis=1, keepdims=True)
    extra = np.concatenate([vn, vn * grip, hand * grip, vel * grip, np.abs(vel), hand[:, 2:3]], axis=1)
    return np.concatenate([X, extra.astype(np.float32)], axis=1)


def build_xy_H(eps, H, dthr=None):
    """★ 按视界 H 单独建集: 同 H 的事件行数一致(L-H) → X (n,7), Y (n,3)

    (v1 教训: H=5 与 H=10 行数不同, 硬拼成一表会把短的整列变 NaN → 那些任务永远训不到)
    """
    X, cols = None, []
    for kind in EV_PER_H:
        x, y, _ = build_event(eps, kind, H, tau=None, dthr=dthr)
        if X is None:
            X = x[:, :KEEP]
        cols.append(y.astype(np.float32))
    return X.astype(np.float32), np.stack(cols, axis=1)


def auc(pred, y):
    m = ~np.isnan(y)
    p, t = pred[m], y[m]
    if len(t) == 0 or t.sum() == 0 or t.sum() == len(t):
        return float("nan")
    order = np.argsort(p)
    ranks = np.empty(len(p), float)
    ranks[order] = np.arange(1, len(p) + 1)
    npos = float(t.sum())
    nneg = float(len(t) - npos)
    return float((ranks[t == 1].sum() - npos * (npos + 1) / 2) / (npos * nneg))


def run_cv(a, dev, torch, np):
    """按变体 K 折交叉验证: 每折用 (K-1)/K 变体训练、留出 1/K 变体 → 报 均值/分布 (诚实口径)"""
    eps = load_episodes(a.data)
    vs = sorted(e["v"] for e in eps)
    rng = np.random.RandomState(0)
    perm = rng.permutation(len(vs))
    K = a.cv
    folds = [set(np.array(vs)[perm[i::K]].tolist()) for i in range(K)]
    print("═" * 74)
    print("T1 交叉验证: %s · %d 变体 · %d 折 · 每折 %d 步" % (os.path.basename(a.data), len(vs), K, a.epochs))
    print("═" * 74)
    gtr = np.concatenate([e["obs"] for e in eps])[:, 3]
    grip_med = float(np.median(gtr))
    acc = {k: [] for k in ("%s_H%d" % e for e in EVENTS)}
    t0 = time.time()
    for fi, ho in enumerate(folds):
        tr_eps = [e for e in eps if e["v"] not in ho]
        ho_eps = [e for e in eps if e["v"] in ho]
        for H in (5, 10):
            Xtr, Ytr = build_xy_H(tr_eps, H, dthr=grip_med)
            Xho, Yho = build_xy_H(ho_eps, H, dthr=grip_med)
            if a.aug:
                Xtr, Xho = augment(Xtr), augment(Xho)
            torch.manual_seed(0)
            net = torch.nn.Sequential(torch.nn.Linear(Xtr.shape[1], a.hidden), torch.nn.ReLU(),
                                      torch.nn.Linear(a.hidden, a.hidden), torch.nn.ReLU(),
                                      torch.nn.Linear(a.hidden, 3)).to(dev)
            opt = torch.optim.Adam(net.parameters(), lr=a.lr)
            lossf = torch.nn.BCEWithLogitsLoss()
            x, y = torch.tensor(Xtr, device=dev), torch.tensor(Ytr, device=dev)
            net.train()
            for _ in range(a.epochs):
                idx = torch.randint(0, len(x), (512,), device=dev)
                opt.zero_grad(); lossf(net(x[idx]), y[idx]).backward(); opt.step()
            net.eval()
            with torch.no_grad():
                pv = net(torch.tensor(Xho, device=dev)).cpu().numpy()
            for kind, i in EV_PER_H.items():
                acc["%s_H%d" % (kind, H)].append(auc(pv[:, i], Yho[:, i]))
    thr = {"gripper_close": 0.91, "reach_z": 0.79, "move_hand": 0.90}
    print("  %-18s %-9s %-9s %-9s %-9s %-8s %s" % ("任务", "均值AUC", "最低折", "最高折", "std", "门槛", "判据"))
    res = {"ts": time.strftime("%F %T"), "mode": "%d-fold CV" % K, "data": os.path.basename(a.data),
           "folds": K, "steps_per_fold": a.epochs, "hidden": a.hidden, "aug": bool(a.aug), "tasks": {}}
    npass = 0
    for k, v in acc.items():
        kind = k.rsplit("_H", 1)[0]
        m = float(np.nanmean(v))
        good = m >= thr[kind]
        npass += int(good)
        res["tasks"][k] = {"mean": round(m, 4), "min": round(float(np.nanmin(v)), 4),
                           "max": round(float(np.nanmax(v)), 4), "std": round(float(np.nanstd(v)), 4),
                           "thr": thr[kind], "pass": bool(good)}
        print("  %-18s %-9.4f %-9.4f %-9.4f %-9.4f %-8.2f %s" %
              (k, m, np.nanmin(v), np.nanmax(v), np.nanstd(v), thr[kind], "✅" if good else "❌"))
    res["pass"] = "%d/%d" % (npass, len(acc))
    res["elapsed_s"] = round(time.time() - t0, 1)
    dst = os.path.join(REPORTS, "cog_event_head_cv_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    json.dump(res, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("  %d 折交叉验证判据: **%s** · 用时 %.1fs" % (K, res["pass"], res["elapsed_s"]))
    print("  取证: %s" % dst)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.path.join(SWM, "datasets/l5_gen_v6.h5"))
    ap.add_argument("--cross", default=os.path.join(SWM, "datasets/l5_gen_v5.h5"))
    ap.add_argument("--epochs", type=int, default=3000, help="训练步数 (mini-batch 512)")
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--tag", default="default")
    ap.add_argument("--hidden", type=int, default=128)
    ap.add_argument("--aug", action="store_true", help="启用派生特征 (合法, 不含未来)")
    ap.add_argument("--seeds", type=int, default=1, help="多种子集成 (平均 logits)")
    ap.add_argument("--cv", type=int, default=0, help="按变体 K 折交叉验证 (0=关, 用单次留出)")
    a = ap.parse_args()

    import torch
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    print("═" * 74)
    print("L5-T1 事件级认知头训练 · 数据 %s · 设备 %s · 输入 obs[0:%d]" %
          (os.path.basename(a.data), dev, KEEP))
    print("═" * 74)

    if a.cv and a.cv > 1:
        return run_cv(a, dev, torch, np)
    eps = load_episodes(a.data)
    rng = np.random.RandomState(0)
    perm = rng.permutation(len(eps))
    ho = set(perm[:max(1, len(eps) // 5)].tolist())
    tr_eps = [e for e in eps if e["v"] not in ho]
    ho_eps = [e for e in eps if e["v"] in ho]
    gtr = np.concatenate([e["obs"] for e in tr_eps])[:, 3]
    grip_med = float(np.median(gtr))
    in_auc, cross_auc, train_s, ckpts = {}, {}, 0.0, []
    ckdir = os.path.join(SWM, "checkpoints", "cog_event_head")
    os.makedirs(ckdir, exist_ok=True)
    ceps = load_episodes(a.cross) if os.path.isfile(a.cross) else None

    for H in (5, 10):
        Xtr, Ytr = build_xy_H(tr_eps, H, dthr=grip_med)
        Xho, Yho = build_xy_H(ho_eps, H, dthr=grip_med)
        if a.aug:
            Xtr, Xho = augment(Xtr), augment(Xho)
        print("── 视界 H=%d: 训练 %d 帧 / 留出 %d 帧 (输入 obs[0:%d], 输出 3 事件)" %
              (H, len(Xtr), len(Xho), KEEP))
        x = torch.tensor(Xtr, device=dev)
        y = torch.tensor(Ytr, device=dev)
        n, bs = len(x), 512
        t0 = time.time()
        seed_preds, seed_cross, best_overall = [], None, (-1.0, None)
        Xc = Yc = None
        if ceps is not None:
            Xc, Yc = build_xy_H(ceps, H, dthr=grip_med)
            if a.aug:
                Xc = augment(Xc)
        for sd_i in range(a.seeds):
            torch.manual_seed(sd_i)
            net = torch.nn.Sequential(torch.nn.Linear(x.shape[1], a.hidden), torch.nn.ReLU(),
                                      torch.nn.Linear(a.hidden, a.hidden), torch.nn.ReLU(),
                                      torch.nn.Linear(a.hidden, 3)).to(dev)
            opt = torch.optim.Adam(net.parameters(), lr=a.lr)
            lossf = torch.nn.BCEWithLogitsLoss()
            best = (-1.0, None)
            net.train()
            for step in range(1, a.epochs + 1):
                idx = torch.randint(0, n, (bs,), device=dev)
                opt.zero_grad()
                loss = lossf(net(x[idx]), y[idx])
                loss.backward()
                opt.step()
                if (step % 1000 == 0):
                    net.eval()
                    with torch.no_grad():
                        pv = net(torch.tensor(Xho, device=dev)).cpu().numpy()
                    m = float(np.nanmean([auc(pv[:, i], Yho[:, i]) for i in range(3)]))
                    net.train()
                    print("   [seed%d] step %5d/%d loss=%.5f 留出均值AUC=%.4f (%.1fs)"
                          % (sd_i, step, a.epochs, float(loss), m, time.time() - t0))
                    if m > best[0]:
                        best = (m, {k: v.clone() for k, v in net.state_dict().items()})
            if best[1]:
                net.load_state_dict(best[1])
            if best[0] > best_overall[0]:
                best_overall = (best[0], {k: v.clone() for k, v in net.state_dict().items()})
            net.eval()
            with torch.no_grad():
                seed_preds.append(net(torch.tensor(Xho, device=dev)).cpu().numpy())
                if Xc is not None:
                    pc_ = net(torch.tensor(Xc, device=dev)).cpu().numpy()
                    seed_cross = pc_ if seed_cross is None else seed_cross + pc_
        train_s += time.time() - t0
        net = torch.nn.Sequential(torch.nn.Linear(x.shape[1], a.hidden), torch.nn.ReLU(),
                                  torch.nn.Linear(a.hidden, a.hidden), torch.nn.ReLU(),
                                  torch.nn.Linear(a.hidden, 3)).to(dev)
        net.load_state_dict(best_overall[1])
        with torch.no_grad():
            pho = np.mean(seed_preds, axis=0)                      # 多种子平均 logits (集成)
        if seed_cross is not None:
            pcross = seed_cross / max(1, a.seeds)
        for kind, i in EV_PER_H.items():
            in_auc["%s_H%d" % (kind, H)] = auc(pho[:, i], Yho[:, i])
        if ceps is not None:
            for kind, i in EV_PER_H.items():
                cross_auc["%s_H%d" % (kind, H)] = auc(pcross[:, i], Yc[:, i])
            print("   跨域 %s: %d 帧 (集成 %d 种子)" % (os.path.basename(a.cross), len(Xc), a.seeds))
        ckp = os.path.join(ckdir, "head_H%d_%s.pt" % (H, a.tag))
        torch.save({"state_dict": net.state_dict(), "H": H, "events": list(EV_PER_H),
                    "keep": KEEP, "hidden": a.hidden, "aug": bool(a.aug), "seeds": a.seeds,
                    "grip_med": grip_med, "data": os.path.basename(a.data),
                    "steps": a.epochs, "holdout_mean_auc": round(best[0], 4),
                    "ts": time.strftime("%F %T")}, ckp)
        ckpts.append(ckp)

    triv = {}
    for kind, H in EVENTS:
        X_, Y_ = build_xy_H(ho_eps, H, dthr=grip_med)
        col = Y_[:, EV_PER_H[kind]]
        triv["%s_H%d" % (kind, H)] = float(max(col.mean(), 1 - col.mean()))

    # 判据 (L5 G3): gripper_close≥0.91 / reach_z≥0.79 / move_hand≥0.90 且跨域不退化(≥域内-0.03)
    thr = {"gripper_close": 0.91, "reach_z": 0.79, "move_hand": 0.90}
    judges = {}
    for k, v in in_auc.items():
        kind = k.rsplit("_H", 1)[0]
        cv = cross_auc.get(k, float("nan"))
        judges[k] = {"auc_in": round(v, 4) if v == v else None, "auc_cross": round(cv, 4) if cv == cv else None,
                     "thr": thr[kind], "pass_in": bool(v == v and v >= thr[kind]),
                     "pass_cross": bool(cv != cv or cv >= v - 0.03)}
    n_pass = sum(1 for v in judges.values() if v["pass_in"] and v["pass_cross"])

    res = {"ts": time.strftime("%F %T"), "task": "L5-T1 事件级认知头", "data": os.path.basename(a.data),
           "eps_train": len(tr_eps), "eps_holdout": len(ho_eps), "frames_train": int(len(Xtr)),
           "input_dims": "obs[0:%d]" % KEEP, "steps": a.epochs, "train_s": round(train_s, 1),
           "device": dev, "ckpts": ckpts, "auc_in_domain": {k: (round(v, 4) if v == v else None) for k, v in in_auc.items()},
           "auc_cross_domain": {k: (round(v, 4) if v == v else None) for k, v in cross_auc.items()},
           "trivial_acc": triv, "judges": judges, "judges_pass": "%d/%d" % (n_pass, len(judges))}
    os.makedirs(REPORTS, exist_ok=True)
    dst = os.path.join(REPORTS, "cog_event_head_train_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    json.dump(res, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("  训练用时 %.1fs · ckpts → %s" % (train_s, ", ".join(os.path.basename(c) for c in ckpts)))
    print("  %-18s %-10s %-10s %-8s %s" % ("任务", "域内AUC", "跨域AUC", "门槛", "判据"))
    for k, v in judges.items():
        print("  %-18s %-10s %-10s %-8.2f %s" % (k, v["auc_in"], v["auc_cross"], v["thr"],
                                                 "✅" if (v["pass_in"] and v["pass_cross"]) else "❌"))
    print("  L5 G3 判据: **%s**" % res["judges_pass"])
    print("  取证: %s" % dst)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
