# -*- coding: utf-8 -*-
"""诊断: 全局单维单尺度对齐为何不过闸 → 是否为"分阶段语义"问题
口径与 tools/calib_intact_action_map.py 完全一致 (first 聚合, Spearman 选维, 单变量最小二乘解尺度),
只加一个变量: **按引擎阶段分组** 拟合/评价。

输出:
  1) 全局 (现口径) 每轴 |ρ|max 与 嵌套5折 OOF R²
  2) 分阶段 每轴 |ρ|max
  3) 阶段条件 (stage-aware) 嵌套5折 OOF R² —— 每折在训练折上按阶段重选维/尺度
用: MUJOCO_GL=egl ./gui-venv311/bin/python tools/diag_intact_stage_align.py --pairs 'reports/intact_pair_ft_seed*.npz'
"""
from __future__ import annotations

import argparse
import glob
import json
import os

import numpy as np
from scipy.stats import spearmanr

AXES = ["x", "y", "z", "gripper"]
GATED = ["x", "y", "z"]


def load(pattern):
    C, U, S, src = [], [], [], []
    for f in sorted(glob.glob(pattern)):
        z = np.load(f, allow_pickle=True)
        c, u, s = z["chunk"], z["u_ff"], z["stage"]
        n = min(len(c), len(u), len(s))
        ok = np.isfinite(u[:n]).all(1) & np.isfinite(c[:n]).all((1, 2))
        C.append(c[:n][ok]); U.append(u[:n][ok]); S.append(np.asarray(s[:n], dtype=object)[ok])
        src.append(os.path.basename(f))
    return np.concatenate(C), np.concatenate(U), np.concatenate(S), src


def fit_axis(D, ua, min_rho):
    if float(np.std(ua)) <= 1e-6 or len(ua) < 8:
        return 0, 0.0, 0.0, False
    r = np.nan_to_num([spearmanr(D[:, j], ua)[0] for j in range(D.shape[1])])
    j = int(np.argmax(np.abs(r)))
    c = D[:, j]
    var = float(np.dot(c - c.mean(), c - c.mean()))
    k = float(np.dot(c - c.mean(), ua - ua.mean()) / var) if var > 1e-12 else 0.0
    return j, k, float(r[j]), bool(abs(r[j]) >= min_rho)


def build_map(D, U, stages, sel_stages, min_rho):
    """返回 {stage: {ax: (dim, scale)}}"""
    m = {}
    for st in sel_stages:
        mask = np.ones(len(stages), bool) if st == "__global__" else (stages == st)
        if mask.sum() < 12:
            continue
        m[st] = {}
        for ai, ax in enumerate(AXES):
            if ax == "gripper":
                m[st][ax] = (0, 0.0)
                continue
            j, k, rho, ok = fit_axis(D[mask], U[mask, ai], min_rho)
            m[st][ax] = (j, k if ok else 0.0)
    return m


def oof_r2(C, U, stages, stage_aware, folds=5, seed=0, min_rho=0.30):
    N, H, D = C.shape
    A = C[:, 0, :]
    rng = np.random.default_rng(seed)
    idx = rng.permutation(N)
    pred = np.full((N, H, len(GATED)), np.nan, np.float32)
    gmap = build_map(A, U, stages, ["__global__"], min_rho)["__global__"]
    smaps = build_map(A, U, stages, sorted(set(stages)), min_rho) if stage_aware else None
    for te in np.array_split(idx, folds):
        tr = np.setdiff1d(idx, te)
        if stage_aware:
            trm = build_map(A[tr], U[tr], stages[tr], sorted(set(stages[tr])), min_rho)
            trm["__global__"] = build_map(A[tr], U[tr], stages[tr], ["__global__"], min_rho)["__global__"]
        else:
            trm = {"__global__": build_map(A[tr], U[tr], stages[tr], ["__global__"], min_rho)["__global__"]}
        for ax_i, ax in enumerate(GATED):
            j, k = trm["__global__"][ax]
            col = C[:, :, j] * k
            if stage_aware:
                for st in set(stages[te]):
                    sel = te[stages[te] == st]
                    jj, kk = trm.get(st, trm["__global__"])[ax]
                    col[sel] = C[sel, :, jj] * kk
            pred[te, :, ax_i] = col[te]
    Y = np.repeat(U[:, None, :len(GATED)], H, 1)
    per = {}
    for ax_i, ax in enumerate(GATED):
        y, p = Y[:, :, ax_i].ravel(), pred[:, :, ax_i].ravel()
        ss = ((y - y.mean()) ** 2).sum()
        per[ax] = float(1 - ((y - p) ** 2).sum() / ss) if ss > 0 else float("nan")
    y, p = Y.ravel(), pred.ravel()
    ss = ((y - y.mean()) ** 2).sum()
    return float(1 - ((y - p) ** 2).sum() / ss), per


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", default="reports/intact_pair_ft_seed*.npz")
    ap.add_argument("--min-rho", type=float, default=0.30)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    C, U, S, src = load(a.pairs)
    A = C[:, 0, :]
    print(f"═══ 诊断: 阶段条件对齐 vs 全局对齐 ═══  数据={len(src)} 文件 · N={len(C)} · chunk={C.shape[1:]}")
    print(f"   引擎 u_ff std: " + ", ".join(f"{ax}={U[:, i].std():.4f}" for i, ax in enumerate(AXES)))

    print("\n-- 1) 全局 (现口径) --")
    g = build_map(A, U, S, ["__global__"], a.min_rho)["__global__"]
    for ax in GATED:
        j, k = g[ax]
        rho = np.nan_to_num([spearmanr(A[:, d], U[:, AXES.index(ax)])[0] for d in range(A.shape[1])])
        print(f"   {ax}: d{j} × {k:+.5f}  |ρ|max={np.abs(rho).max():.3f}  {'PASS' if abs(rho).max() >= a.min_rho else 'FAIL(闸%.2f)' % a.min_rho}")
    r2g, perg = oof_r2(C, U, S, False, a.folds, a.seed, a.min_rho)
    print(f"   全局 嵌套{a.folds}折 OOF R² xyz={r2g:+.4f}  逐轴 " + ", ".join(f"{k}={v:+.3f}" for k, v in perg.items()))

    print("\n-- 2) 分阶段 每轴 |ρ|max (n≥12) --")
    stages = sorted(set(S))
    rows = []
    for st in stages:
        m = S == st
        if m.sum() < 12:
            continue
        line = [f"   {str(st)[:18]:20} n={int(m.sum()):4d}"]
        best = {}
        for ax in GATED:
            rho = np.nan_to_num([spearmanr(A[m][:, d], U[m][:, AXES.index(ax)])[0] for d in range(A.shape[1])])
            j = int(np.argmax(np.abs(rho)))
            best[ax] = (j, abs(rho[j]))
            line.append(f"{ax}=d{j}({abs(rho[j]):.2f})")
        rows.append((st, int(m.sum()), best))
        print("  ".join(line))

    print("\n-- 3) 阶段条件 (stage-aware) 嵌套 OOF R² --")
    r2s, pers = oof_r2(C, U, S, True, a.folds, a.seed, a.min_rho)
    print(f"   stage-aware OOF R² xyz={r2s:+.4f}  逐轴 " + ", ".join(f"{k}={v:+.3f}" for k, v in pers.items()))
    print(f"   对比 全局 {r2g:+.4f} → 阶段条件 {r2s:+.4f}   (闸 {0.20})")
    print(f"\n   结论: 全局{'过闸' if r2g >= 0.2 else '不过闸'} / 阶段条件{'过闸' if r2s >= 0.2 else '不过闸'}")
    out = {"pairs": src, "n": int(len(C)), "global": {"oof_r2_xyz": r2g, "per_axis": perg,
           "map": {k: list(v) for k, v in g.items()}},
           "stage_aware": {"oof_r2_xyz": r2s, "per_axis": pers,
                           "per_stage_best_rho": {str(s): {k: list(v) for k, v in b.items()} for s, n, b in rows},
                           "per_stage_n": {str(s): n for s, n, b in rows}}}
    p = f"reports/diag_intact_stage_align_{__import__('time').strftime('%Y%m%d_%H%M%S')}.json"
    json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"   → {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
