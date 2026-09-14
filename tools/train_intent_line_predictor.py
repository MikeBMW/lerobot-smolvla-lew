# -*- coding: utf-8 -*-
"""🧠 train_intent_line_predictor.py — 流形专家预测器 (含意图口) 离线训练 + LOSO 评估

数据: reports/intact_pair_*.npz (13 个文件 / 12 个回合组 / 1935 有效帧) —— **逐帧同源**:
  z_t(192, INTACT 潜) · chunk(8,8, INTACT 动作块) · delta(192, δ=z_goal−z_t 意图) · mani6(6, 引擎流形真值) · u_ff(4, 引擎前馈真值)

训练两条互相独立的杆 (老倪口径: 每条杆单独同口径对照):
  · 预测器 (流形专家): (z_t, a=chunk[0,:4], [δ]) → mani6        ← 意图口 = 可选条件
  · 动作头:            mani6 → u_ff (4)                          ← 供引擎直连线末端

评估: **LOSO 按回合组留出** (12 折), 逐维 R² / 中位绝对误差 / TOL 成功率;
      同一折、同一初始化下跑 意图口 关/开 两遍 → ΔR² 就是"意图是否真提升"的硬数字。

产物: checkpoints/manifold_predictor/intent_line.pt
      {predictor, head, scaler{...}, meta{loso 指标/口径}}  ← 引擎 _il_init 直接可加载 (ready=True)
      报告 reports/intent_line_predictor_<ts>.json

用法: OMP_NUM_THREADS=4 ./gui-venv311/bin/python tools/train_intent_line_predictor.py [--epochs 250]
"""
from __future__ import annotations

import argparse
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

TOL = np.array([0.03, 0.01, 0.01, 0.05, 0.015, 0.015])   # 与 v4 训练脚本同一判据 (可对齐历史数字)
NAMES = ["progress", "risk", "V", "eta", "rem", "dperp"]


def load_data() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, list]:
    Z, M, A, D, U, G = [], [], [], [], [], []
    for p in sorted(glob.glob(os.path.join(ROOT, "reports", "intact_pair_*.npz"))):
        d = np.load(p, allow_pickle=True)
        if "mani6" not in d.files:
            continue
        m = d["mani6"]
        ok = np.isfinite(m).all(1) & np.isfinite(d["z_t"]).all(1) & np.isfinite(d["delta"]).all(1)
        if not ok.any():
            continue
        b = os.path.basename(p)
        if b.startswith("intact_pair_ft_seed"):
            g = "ft" + re.search(r"ft_seed(\d+)", b).group(1)
        else:
            g = "s" + re.search(r"seed(\d+)", b).group(1)
        Z.append(d["z_t"][ok]); M.append(m[ok]); A.append(d["chunk"][ok][:, 0, :4])
        D.append(d["delta"][ok])
        U.append(d["u_ff"][ok] if "u_ff" in d.files and d["u_ff"].shape[0] == len(m) else
                 np.full((int(ok.sum()), 4), np.nan, np.float32))
        G += [g] * int(ok.sum())
    return (np.concatenate(Z), np.concatenate(M), np.concatenate(A),
            np.concatenate(D), np.concatenate(U), G)


def fit_scaler(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mu = np.nanmean(x, 0)
    sd = np.nanstd(x, 0)
    sd = np.where((sd < 1e-8) | ~np.isfinite(sd), 1.0, sd)
    return mu.astype(np.float32), sd.astype(np.float32)


def r2(pred: np.ndarray, gt: np.ndarray) -> np.ndarray:
    ss = ((gt - pred) ** 2).sum(0)
    st = ((gt - gt.mean(0)) ** 2).sum(0)
    return 1.0 - ss / np.maximum(st, 1e-12)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=250)
    ap.add_argument("--batch", type=int, default=128)
    ap.add_argument("--hidden", type=int, default=192)
    ap.add_argument("--layers", type=int, default=2)
    ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--out", default=os.path.join(ROOT, "checkpoints", "manifold_predictor", "intent_line.pt"))
    ap.add_argument("--skip-loso", action="store_true")
    a = ap.parse_args()

    import torch
    from torch import nn
    from lerobot.manifold.predictor_layer import WorldModelPredictor
    _lew = os.path.join(ROOT, "src", "lerobot", "policies", "smolvla_lew")
    if _lew not in sys.path:
        sys.path.insert(0, _lew)
    from state_space_action_head import StateSpaceActionHead

    Z, M, A, D, U, G = load_data()
    groups = sorted(set(G))
    print(f"═══ 意图直连线训练 ═══")
    print(f"数据 {len(Z)} 帧 · {len(groups)} 个回合组 {groups}")
    print(f"  z_t{ Z.shape} · delta{D.shape} · a{A.shape} · mani6{M.shape} · u_ff{U.shape}"
          f" · u_ff 有效 {int(np.isfinite(U).all(1).sum())}")
    tz = lambda x: torch.from_numpy(np.asarray(x, np.float32))

    def make(variant: str, seed: int, zdim: int, mdim: int):
        """variant: 'off'(意图口关) / 'on'(意图口开, m=δ)。两变体同 seed → 同初始化 (同口径)。"""
        torch.manual_seed(seed)
        pred = WorldModelPredictor(z_dim=zdim, act_dim=4, manifold_dim=6,
                                  hidden_dim=a.hidden, num_layers=a.layers, m_dim=mdim)
        head = StateSpaceActionHead(input_dim=6, action_dim=4, chunk_size=1)
        return pred, head

    def run(variant: str, tr_idx, te_idx, seed: int, sc: dict):
        """训练 + 评估一个变体 (意图口 on/off 由 variant 决定)。返回 (指标, 模型)。"""
        zdim = Z.shape[1]
        mdim = D.shape[1] if variant == "on" else 0
        pred, head = make(variant, seed, zdim, mdim)
        zn = lambda x: ((x - sc["z_mu"]) / sc["z_sd"]).astype(np.float32)
        an = lambda x: ((x - sc["a_mu"]) / sc["a_sd"]).astype(np.float32)
        dn = lambda x: ((x - sc["d_mu"]) / sc["d_sd"]).astype(np.float32)
        mn = lambda x: ((x - sc["m_mu"]) / sc["m_sd"]).astype(np.float32)
        un = lambda x: ((x - sc["u_mu"]) / sc["u_sd"]).astype(np.float32)
        ztr, atr, dtr, mtr = tz(zn(Z[tr_idx])), tz(an(A[tr_idx])), tz(dn(D[tr_idx])), tz(mn(M[tr_idx]))
        opt = torch.optim.AdamW(pred.parameters(), lr=a.lr, weight_decay=1e-5)
        sch = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=a.epochs)
        n = len(tr_idx)
        for ep in range(a.epochs):
            pred.train()
            perm = torch.randperm(n)
            for i in range(0, n, a.batch):
                b = perm[i:i + a.batch]
                opt.zero_grad()
                mm = dtr[b] if variant == "on" else None
                out = pred(ztr[b], atr[b], mm)
                loss = nn.functional.mse_loss(out["manifold"], mtr[b])
                loss.backward()
                opt.step()
            sch.step()
        # 评估 (测试折, 未标准化回原量纲)
        pred.eval()
        with torch.inference_mode():
            mm = tz(dn(D[te_idx])) if variant == "on" else None
            out = pred(tz(zn(Z[te_idx])), tz(an(A[te_idx])), mm)
            mp = (out["manifold"].numpy() * sc["m_sd"] + sc["m_mu"])
            gain = float(out.get("intent_gain") or 0.0)
        gt = M[te_idx]
        e = np.abs(mp - gt)
        r2v = r2(mp, gt)
        ok = (e <= TOL).all(1)
        # 动作头: 用**预测流形** (闭环口径) 回归 u_ff
        uok = np.isfinite(U[te_idx]).all(1)
        head_r2 = head_mae = None
        if uok.any():
            opt2 = torch.optim.AdamW(head.parameters(), lr=3e-3, weight_decay=1e-5)
            htr = np.isfinite(U[tr_idx]).all(1)
            if htr.sum() > 32:
                mht, uht = tz(mn(M[tr_idx][htr])), tz(un(U[tr_idx][htr]))
                for _ in range(200):
                    opt2.zero_grad()
                    l = nn.functional.mse_loss(head(mht), uht.reshape(-1, 1, 4))
                    l.backward(); opt2.step()
                head.eval()
                with torch.inference_mode():
                    up = head(tz(mn(mp))).numpy().reshape(-1, 4) * sc["u_sd"] + sc["u_mu"]
                ut = U[te_idx][uok]
                head_r2 = float(np.mean(r2(up[uok], ut)))
                head_mae = float(np.abs(up[uok] - ut).mean())
        return ({"n_test": int(len(te_idx)), "r2_per_dim": [round(float(x), 4) for x in r2v],
                 "r2_mean": round(float(np.mean(r2v)), 4),
                 "mae_per_dim": [round(float(x), 5) for x in e.mean(0)],
                 "tol_succ": round(float(ok.mean()), 4),
                 "intent_gain": round(gain, 6),
                 "head_r2_xyz_mean": round(head_r2, 4) if head_r2 is not None else None,
                 "head_mae": round(head_mae, 5) if head_mae is not None else None},
                {"pred": pred, "head": head})

    folds = []
    if not a.skip_loso:
        for g in groups:
            te = np.array([i for i, x in enumerate(G) if x == g])
            tr = np.array([i for i, x in enumerate(G) if x != g])
            if len(te) < 20 or len(tr) < 200:
                continue
            sc = {"z_mu": fit_scaler(Z[tr])[0], "z_sd": fit_scaler(Z[tr])[1],
                  "a_mu": fit_scaler(A[tr])[0], "a_sd": fit_scaler(A[tr])[1],
                  "d_mu": fit_scaler(D[tr])[0], "d_sd": fit_scaler(D[tr])[1],
                  "m_mu": M[tr].mean(0), "m_sd": np.where(M[tr].std(0) < 1e-8, 1.0, M[tr].std(0)),
                  "u_mu": np.nanmean(U[tr], 0), "u_sd": np.where(np.nanstd(U[tr], 0) < 1e-8, 1.0,
                                                                 np.nanstd(U[tr], 0))}
            m_off, _ = run("off", tr, te, 7, sc)
            m_on, _ = run("on", tr, te, 7, sc)
            d = {"fold": g, "off": m_off, "on": m_on,
                 "dR2_mean": round(m_on["r2_mean"] - m_off["r2_mean"], 4),
                 "d_tol_succ": round(m_on["tol_succ"] - m_off["tol_succ"], 4)}
            folds.append(d)
            print(f"[{g}] n={m_off['n_test']:4d} R²(off)={m_off['r2_mean']:+.3f} "
                  f"R²(on)={m_on['r2_mean']:+.3f} ΔR²={d['dR2_mean']:+.3f} · "
                  f"TOL(off)={m_off['tol_succ']:.3f} TOL(on)={m_on['tol_succ']:.3f} · "
                  f"gain(on)={m_on['intent_gain']:.4f} · headR²={m_on['head_r2_xyz_mean']}", flush=True)

    # 最终模型: 全量训练 (报告 LOSO 数字为准; ckpt 供引擎加载)
    sc_all = {"z_mu": fit_scaler(Z)[0], "z_sd": fit_scaler(Z)[1],
              "a_mu": fit_scaler(A)[0], "a_sd": fit_scaler(A)[1],
              "d_mu": fit_scaler(D)[0], "d_sd": fit_scaler(D)[1],
              "m_mu": M.mean(0), "m_sd": np.where(M.std(0) < 1e-8, 1.0, M.std(0)),
              "u_mu": np.nanmean(U, 0), "u_sd": np.where(np.nanstd(U, 0) < 1e-8, 1.0, np.nanstd(U, 0))}
    allidx = np.arange(len(Z))
    _, mdl = run("on", allidx, allidx, 7, sc_all)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    torch.save({"predictor": mdl["pred"].state_dict(), "head": mdl["head"].state_dict(),
                "scaler": {k: np.asarray(v, np.float32) for k, v in sc_all.items()},
                "meta": {"kind": "intent_line", "variant": "on(m=δ)", "z_t": int(Z.shape[1]),
                         "m_dim": int(D.shape[1]), "frames": int(len(Z)), "groups": groups,
                         "metric": "LOSO 按回合组留出 · R²/TOL 见报告",
                         "ts": time.strftime("%F %T")}},
               a.out)
    rep = {"ts": time.strftime("%F %T"), "frames": int(len(Z)), "groups": groups,
           "tol": TOL.tolist(), "dim_names": NAMES,
           "loso_folds": folds,
           "loso_summary": {} if not folds else {
               "r2_off_mean": round(float(np.mean([f["off"]["r2_mean"] for f in folds])), 4),
               "r2_on_mean": round(float(np.mean([f["on"]["r2_mean"] for f in folds])), 4),
               "dR2_mean": round(float(np.mean([f["dR2_mean"] for f in folds])), 4),
               "dR2_win_folds": int(sum(1 for f in folds if f["dR2_mean"] > 0)),
               "n_folds": len(folds),
               "tol_off_mean": round(float(np.mean([f["off"]["tol_succ"] for f in folds])), 4),
               "tol_on_mean": round(float(np.mean([f["on"]["tol_succ"] for f in folds])), 4),
               "head_r2_mean": round(float(np.mean([f["on"]["head_r2_xyz_mean"] for f in folds
                                                    if f["on"]["head_r2_xyz_mean"] is not None])), 4),
               "r2_per_dim_on": [round(float(x), 4) for x in np.mean(
                   [f["on"]["r2_per_dim"] for f in folds], 0)],
           },
           "ckpt": os.path.relpath(a.out, ROOT)}
    op = os.path.join(ROOT, "reports", f"intent_line_predictor_{time.strftime('%Y%m%d_%H%M%S')}.json")
    json.dump(rep, open(op, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n═══ LOSO 汇总 ═══")
    print(json.dumps(rep["loso_summary"], ensure_ascii=False, indent=1))
    print(f"→ ckpt {rep['ckpt']}\n→ 报告 {os.path.relpath(op, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
