# -*- coding: utf-8 -*-
"""🌌 train_mani_geo_predictor.py — 流形专家预测器 (几何 z7 路线, 含几何意图口 A/B)

路线依据 (2026-09-14 夜, 两次实证):
  · z_t(192)+δ → 流形 6 维: LOSO R² 全负 ⇒ 作废 (见 reports/intent_line_predictor_*.json)
  · 几何 9 维 → 流形 6 维: 4/6 维 R² 强正 ⇒ 几何路线成立 (见 reports/intent_identifiability_*.json)
  ⇒ 本训练 = (z7, 引擎动作) → 流形 6 维; 意图口用**几何意图** m = target − peg_head (3 维), 不是 latent δ。

评估: **留一 seed 折** (clean/jitter 同 seed 同折) · 逐维 R² (均值/中位) · TOL 成功率;
      同折同初始化跑 意图关/开 两遍 ⇒ ΔR² = 几何意图口的真实增益 (老倪口径: 每条杆单独对照)。

产物: checkpoints/manifold_predictor/mani_geo.pt
      {predictor, head, scaler, meta{loso_r2_mean,...}}   ← 引擎质量闸按 meta.loso_r2_mean ≥0.30 判 ready
      报告 reports/mani_geo_predictor_<ts>.json

用法: OMP_NUM_THREADS=4 ./gui-venv311/bin/python tools/train_mani_geo_predictor.py
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

import numpy as np

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, os.path.join(ROOT, "src"))
TOL = np.array([0.03, 0.01, 0.01, 0.05, 0.015, 0.015])
NAMES = ["progress", "risk", "V", "eta", "rem", "dperp"]


def r2(p, g):
    ss = ((g - p) ** 2).sum(0)
    st = ((g - g.mean(0)) ** 2).sum(0)
    return 1.0 - ss / np.maximum(st, 1e-12)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.path.join(ROOT, "data", "manifold_geo_v1.npz"))
    ap.add_argument("--epochs", type=int, default=220)
    ap.add_argument("--batch", type=int, default=256)
    ap.add_argument("--hidden", type=int, default=192)
    ap.add_argument("--layers", type=int, default=3)
    ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--out", default=os.path.join(ROOT, "checkpoints", "manifold_predictor", "mani_geo.pt"))
    ap.add_argument("--skip-loso", action="store_true")
    a = ap.parse_args()
    import torch
    from torch import nn
    from lerobot.manifold.predictor_layer import WorldModelPredictor
    _lew = os.path.join(ROOT, "src", "lerobot", "policies", "smolvla_lew")
    if _lew not in sys.path:
        sys.path.insert(0, _lew)
    from state_space_action_head import StateSpaceActionHead

    d = np.load(a.data, allow_pickle=True)
    Z = d["z"].astype(np.float32)                     # (n,7)
    A = d["a"].astype(np.float32)                     # (n,4) 引擎真实下发动作
    M = d["m"].astype(np.float32)                     # (n,6) 流形真值
    MI = (d["target"].astype(np.float32) - d["peg"].astype(np.float32))   # (n,3) 几何意图
    SEED = np.array([re.search(r"s(\d+)", str(s)).group(1) for s in d["seed"]])
    uid = np.array([f"{s}|{k}" for s, k in zip(d["split"], d["seed"])])
    print(f"═══ 流形专家预测器 (几何 z7 路线) ═══")
    print(f"数据 {len(Z)} 帧 · {len(set(uid.tolist()))} 组 / {len(set(SEED.tolist()))} seed 折")
    print(f"  z7{Z.shape} · a{A.shape} · mani6{M.shape} · 几何意图(Δ=target−peg){MI.shape}"
          f" 阈值 |Δ| 中位 {np.median(np.linalg.norm(MI,axis=1)):.4f}")
    tz = lambda x: torch.from_numpy(np.asarray(x, np.float32))

    def sc_fit(X):
        return X.mean(0).astype(np.float32), np.where(X.std(0) < 1e-8, 1.0, X.std(0)).astype(np.float32)

    def run(variant: str, tr, te, sc, eps, hid, layers, seed=7):
        mdim = MI.shape[1] if variant == "on" else 0
        torch.manual_seed(seed)
        pred = WorldModelPredictor(z_dim=Z.shape[1], act_dim=4, manifold_dim=6,
                                  hidden_dim=hid, num_layers=layers, m_dim=mdim)
        head = StateSpaceActionHead(input_dim=6, action_dim=4, chunk_size=1)
        zn = lambda X: (X - sc["z_mu"]) / sc["z_sd"]
        an = lambda X: (X - sc["a_mu"]) / sc["a_sd"]
        mn = lambda X: (X - sc["m_mu"]) / sc["m_sd"]
        dn = lambda X: (X - sc["d_mu"]) / sc["d_sd"]
        ztr, atr, mtr = tz(zn(Z[tr])), tz(an(A[tr])), tz(mn(M[tr]))
        dtr = tz(dn(MI[tr])) if variant == "on" else None
        opt = torch.optim.AdamW(pred.parameters(), lr=a.lr, weight_decay=1e-5)
        sch = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=eps)
        n = len(tr)
        for _ in range(eps):
            pred.train()
            perm = torch.randperm(n)
            for i in range(0, n, a.batch):
                b = perm[i:i + a.batch]
                opt.zero_grad()
                out = pred(ztr[b], atr[b], (dtr[b] if variant == "on" else None))
                nn.functional.mse_loss(out["manifold"], mtr[b]).backward()
                opt.step()
            sch.step()
        pred.eval()
        with torch.inference_mode():
            out = pred(tz(zn(Z[te])), tz(an(A[te])), (tz(dn(MI[te])) if variant == "on" else None))
            mp = out["manifold"].numpy() * sc["m_sd"] + sc["m_mu"]
            gain = float(out.get("intent_gain") or 0.0)
        # 动作头: 流形真值 → 引擎动作 (专家监督), 供引擎直连线末端
        mu_, su_ = sc["u_mu"], sc["u_sd"]
        opt2 = torch.optim.AdamW(head.parameters(), lr=3e-3, weight_decay=1e-5)
        mht, uht = tz(mn(M[tr])), tz((A[tr] - mu_) / su_)
        for _ in range(250):
            opt2.zero_grad()
            nn.functional.mse_loss(head(mht), uht.reshape(-1, 1, 4)).backward()
            opt2.step()
        head.eval()
        with torch.inference_mode():
            up = head(tz(mn(mp))).numpy().reshape(-1, 4) * su_ + mu_
        e = np.abs(mp - M[te])
        return {"r2_per_dim": [round(float(x), 4) for x in r2(mp, M[te])],
                "r2_mean": round(float(np.mean(r2(mp, M[te]))), 4),
                "mae_per_dim": [round(float(x), 5) for x in e.mean(0)],
                "tol_succ": round(float((e <= TOL).all(1).mean()), 4),
                "intent_gain": round(gain, 6),
                "head_mae": round(float(np.abs(up - A[te]).mean()), 5),
                "head_r2_mean": round(float(np.mean(r2(up, A[te]))), 4)}, {"pred": pred, "head": head}

    folds = []
    if not a.skip_loso:
        for s in sorted(set(SEED.tolist())):
            te = np.where(SEED == s)[0]; tr = np.where(SEED != s)[0]
            if len(te) < 50 or len(tr) < 500:
                continue
            zm, zs = sc_fit(Z[tr]); am, as_ = sc_fit(A[tr]); mm, ms = sc_fit(M[tr]); dm, ds = sc_fit(MI[tr])
            um, us = A[tr].mean(0), np.where(A[tr].std(0) < 1e-8, 1.0, A[tr].std(0))
            sc = {"z_mu": zm, "z_sd": zs, "a_mu": am, "a_sd": as_, "m_mu": mm, "m_sd": ms,
                  "d_mu": dm, "d_sd": ds, "u_mu": um.astype(np.float32), "u_sd": us.astype(np.float32)}
            off, _ = run("off", tr, te, sc, a.epochs, a.hidden, a.layers)
            on, _ = run("on", tr, te, sc, a.epochs, a.hidden, a.layers)
            row = {"fold": f"s{s}", "n_test": int(len(te)), "off": off, "on": on,
                   "dR2": round(on["r2_mean"] - off["r2_mean"], 4),
                   "d_tol": round(on["tol_succ"] - off["tol_succ"], 4)}
            folds.append(row)
            print(f"[s{s}] n={row['n_test']:5d} R²(off)={off['r2_mean']:+.3f} R²(on)={on['r2_mean']:+.3f} "
                  f"ΔR²={row['dR2']:+.3f} TOL(off)={off['tol_succ']:.3f} TOL(on)={on['tol_succ']:.3f} "
                  f"headMAE={on['head_mae']:.4f}", flush=True)

    zm, zs = sc_fit(Z); am, as_ = sc_fit(A); mm, ms = sc_fit(M); dm, ds = sc_fit(MI)
    um, us = A.mean(0), np.where(A.std(0) < 1e-8, 1.0, A.std(0))
    sc_all = {"z_mu": zm, "z_sd": zs, "a_mu": am, "a_sd": as_, "m_mu": mm, "m_sd": ms,
              "d_mu": dm, "d_sd": ds, "u_mu": um.astype(np.float32), "u_sd": us.astype(np.float32)}
    allr = np.arange(len(Z))
    loso_r2 = round(float(np.mean([f["on"]["r2_mean"] for f in folds])), 4) if folds else None
    loso_med = round(float(np.median([f["on"]["r2_mean"] for f in folds])), 4) if folds else None
    # 最终模型用"过闸口径"的变体: 意图有增益才开
    use_intent = bool(folds and np.mean([f["dR2"] for f in folds]) > 0.01)
    final, mdl = run("on" if (use_intent or not folds) else "off", allr, allr, sc_all,
                     a.epochs, a.hidden, a.layers)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    torch.save({"predictor": mdl["pred"].state_dict(), "head": mdl["head"].state_dict(),
                "scaler": {k: np.asarray(v, np.float32) for k, v in sc_all.items()},
                "meta": {"kind": "mani_geo", "input_kind": "z7", "intent_kind": "geo_disp(target−peg)",
                         "variant": "on" if use_intent else "off",
                         "loso_r2_mean": loso_r2, "loso_r2_median": loso_med,
                         "loso_intent_dR2": (round(float(np.mean([f["dR2"] for f in folds])), 4)
                                             if folds else None),
                         "frames": int(len(Z)), "groups": int(len(set(uid.tolist()))),
                         "ts": time.strftime("%F %T")}}, a.out)
    rep = {"ts": time.strftime("%F %T"), "data": os.path.relpath(a.data, ROOT), "frames": int(len(Z)),
           "tol": TOL.tolist(), "dim_names": NAMES, "folds": folds,
           "summary": {} if not folds else {
               "r2_off_mean": round(float(np.mean([f["off"]["r2_mean"] for f in folds])), 4),
               "r2_on_mean": round(float(np.mean([f["on"]["r2_mean"] for f in folds])), 4),
               "r2_on_median": loso_med,
               "dR2_intent_mean": round(float(np.mean([f["dR2"] for f in folds])), 4),
               "intent_win_folds": int(sum(1 for f in folds if f["dR2"] > 0)),
               "n_folds": len(folds),
               "tol_on_mean": round(float(np.mean([f["on"]["tol_succ"] for f in folds])), 4),
               "head_mae_on_mean": round(float(np.mean([f["on"]["head_mae"] for f in folds])), 5),
               "r2_per_dim_on": [round(float(x), 4) for x in
                                 np.mean([f["on"]["r2_per_dim"] for f in folds], 0)],
               "r2_per_dim_on_median": [round(float(x), 4) for x in
                                        np.median([f["on"]["r2_per_dim"] for f in folds], 0)],
           }, "ckpt": os.path.relpath(a.out, ROOT), "ckpt_meta": json.loads(json.dumps(
               {k: v for k, v in torch.load(a.out, map_location="cpu", weights_only=False)["meta"].items()}))}
    op = os.path.join(ROOT, "reports", f"mani_geo_predictor_{time.strftime('%Y%m%d_%H%M%S')}.json")
    json.dump(rep, open(op, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n═══ LOSO 汇总 ═══"); print(json.dumps(rep["summary"], ensure_ascii=False, indent=1))
    print(f"→ ckpt {rep['ckpt']} (meta.loso_r2_mean={loso_r2})\n→ 报告 {os.path.relpath(op, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
