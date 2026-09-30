#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔬 diag_lie_lateral.py — 归因: 横向 (x) 分量 LOO R² 只有 0.06 是"采样阶段偏"还是"潜空间不含"。

全部在同一批真值样本上做 (无引擎):
  A) 逐维真值统计 (std + 逐阶段) —— 先看信号本身有没有幅度 (σ≈0 → R² 无意义)
  B) 逐阶段 LOO R² —— 某阶段 (下降/对位) 若横向可辨识 ⇒ 阶段混合造成的假低估
  C) 换意图口径: Δz_pred = z_pred−z_t  vs  Δz_goal = z_goal−z_t  vs  拼接
  D) 非线性检验: 线性 (PCA+ridge) vs +二次特征 ⇒ 二次显著抬升 = 非线性编码; 都低 = 信息不在
  E) 空对照: 打乱 Y 的 null R² (证明判据不是恒真)

用法: python tools/diag_lie_lateral.py
"""
from __future__ import annotations

import glob
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "src")]

from lerobot.manifold.lie_intent import quat_log, quat_relative  # noqa: E402

DIMS = ["ω_x", "ω_y", "ω_z", "v_x", "v_y", "v_z"]


def _loo_ridge(Z, Y, ridge=1e-2):
    n = len(Z)
    loo = np.zeros_like(Y)
    for i in range(n):
        m = np.ones(n, bool)
        m[i] = False
        Zi, Yi = Z[m], Y[m]
        W = np.linalg.solve(Zi.T @ Zi + ridge * np.eye(Zi.shape[1]), Zi.T @ Yi)
        loo[i] = Z[i] @ W
    sst = np.maximum(np.sum((Y - Y.mean(0)) ** 2, axis=0), 1e-12)
    return 1.0 - np.sum((Y - loo) ** 2, axis=0) / sst


def _pca(X, d=32):
    mu = X.mean(0, keepdims=True)
    Xc = X - mu
    d = max(1, min(d, Xc.shape[0] - 1, Xc.shape[1]))
    _, _, Vt = np.linalg.svd(Xc, full_matrices=False)
    return Xc @ Vt[:d].T


def _quad(Z, k=6):
    Zk = Z[:, :k]
    return np.concatenate([Z, (Zk[:, :, None] * Zk[:, None, :]).reshape(len(Z), -1)], axis=1)


def load():
    paths = [p for p in sorted(glob.glob(os.path.join(ROOT, "reports", "lie_calib_s*.npz")))
             if os.path.isfile(p)]
    dp, dg, Y, ST = [], [], [], []
    for p in paths:
        d = np.load(p, allow_pickle=True)
        if "ee_p" not in d:
            continue
        zt, zp, zg = d["z_t"], d["z_pred"], d["z_goal"]
        for i in range(len(zt) - 1):
            du = quat_relative(d["ee_q"][i + 1], d["ee_q"][i])
            w = quat_log(du)
            v = np.asarray(d["ee_p"][i + 1], float) - np.asarray(d["ee_p"][i], float)
            dp.append(zp[i] - zt[i])
            dg.append(zg[i] - zt[i])
            Y.append(np.concatenate([w, v]))
            ST.append(str(d["stage"][i]))
    return (np.asarray(dp, float), np.asarray(dg, float), np.asarray(Y, float),
            np.asarray(ST), len(paths))


def main() -> int:
    Xp, Xg, Y, ST, nf = load()
    print(f"🧭 横向归因 — {nf} 个文件 · 样本 {len(Y)}")
    if len(Y) < 30:
        print("❌ 样本不足")
        return 2
    rng = np.random.default_rng(0)

    # A) 逐维真值幅度 (全局 + 逐阶段)
    print("── A) 真值幅度 (每维 std; v 单位 mm, ω 单位 mrad) ──")
    hdr = "  ".join(f"{d:>12}" for d in DIMS)
    print(f"  全局  {hdr}")
    sc = np.array([1000.0] * 3 + [1000.0] * 3)
    print("  σ    " + "  ".join(f"{s:>12.4f}" for s in (Y * sc).std(0)))
    print(f"  均值0  " + "  ".join(f"{s:>12.4f}" for s in (Y * sc).mean(0)))
    for st in sorted(set(ST.tolist())):
        m = ST == st
        if m.sum() < 8:
            continue
        print(f"  [{st}] n={int(m.sum()):3d} " + "  ".join(
            f"{s:>12.4f}" for s in (Y[m] * sc).std(0)))

    # B/C/D) LOO R² 表
    Zp, Zg = _pca(Xp), _pca(Xg)
    Zc = np.concatenate([Zp, Zg], axis=1)
    print("── B/C/D) 逐维 LOO R² (线性=PCA32+ridge; +二次=再加前6主成分两两乘积) ──")
    print(f"  {'输入/口径':<22}" + "".join(f"{d:>9}" for d in DIMS))
    rows = [("Δz_pred (线性)", Zp, False), ("Δz_pred +二次", Zp, True),
            ("Δz_goal (线性)", Zg, False), ("Δz_goal +二次", Zg, True),
            ("Δz_pred⊕goal (线性)", Zc, False), ("Δz_pred⊕goal +二次", Zc, True)]
    for name, Z, q in rows:
        Zq = _quad(Z) if q else Z
        r2 = _loo_ridge(Zq, Y)
        print(f"  {name:<22}" + "".join(f"{v:>+9.3f}" for v in r2))
    # 空对照
    Ys = Y[rng.permutation(len(Y))]
    print(f"  {'null (打乱Y)':<22}" + "".join(f"{v:>+9.3f}" for v in _loo_ridge(Zp, Ys)))

    # B) 逐阶段 (用最佳线性输入)
    print("── B) 逐阶段 LOO R² (Δz_pred, 线性) ──")
    print(f"  {'阶段':<8}{'n':>5}" + "".join(f"{d:>9}" for d in DIMS))
    for st in sorted(set(ST.tolist())):
        m = ST == st
        if m.sum() < 25:
            print(f"  {st:<8}{int(m.sum()):>5}  (样本 <25, 跳过)")
            continue
        r2 = _loo_ridge(Zp[m], Y[m])
        print(f"  {st:<8}{int(m.sum()):>5}" + "".join(f"{v:>+9.3f}" for v in r2))

    # 结论行
    r2_lin = _loo_ridge(Zp, Y)
    r2_quad = _loo_ridge(_quad(Zp), Y)
    _ix = 3
    print("── 判定 ──")
    print(f"  v_x: 线性 {r2_lin[_ix]:+.3f} → 二次 {r2_quad[_ix]:+.3f} · "
          f"σ(v_x)={ (Y[:, _ix]*1000).std():.4f}mm/帧 · "
          f"最大逐阶段 {max(_loo_ridge(Zp[ST == st], Y[ST == st])[_ix] for st in set(ST.tolist()) if (ST == st).sum() >= 25):+.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
