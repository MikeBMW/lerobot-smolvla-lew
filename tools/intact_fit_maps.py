# -*- coding: utf-8 -*-
"""🧮 两个拟合 (共用同一份配对数据 reports/intact_pair_*.npz)

--mode action  Step 1 标定: 官方 10 维动作 chunk → 本引擎 u_ff 4 维 (仿射/岭回归)
                 产出 models/intact_action_map.json (W/b + 逐轴 R²/MAE + 溯源)
                 **红线**: 拟合质量差就如实写低分, 不拿"能跑"当"对得上"。

--mode decode  Step 2 探针: INTACT 潜空间 192 维 → 本引擎流形真值 6 维 (可解码性)
                 判据: 逐维 R² + CCA 典型相关 + 打乱标签 null 对照
                 结论只有两种: 可解码 (可以接流形) / 不可解码 (先做 z 对齐映射, 不硬接)

口径 (2026-09-12 修正, 第一版踩坑):
  · **留一轮交叉验证 (LOSO)**: n 少时单次切分会被分布漂移支配 → 每轮当测试集, 其余训练,
    报 mean±std; 同时用打乱标签的 null 作对照 (null 应 ≈0/负)。
  · **先降维再回归**: 192 维 z + 266 样本 → p≈n, 岭回归 train R² 高得离谱、test 全负
    (第一版实测: train 0.43~0.98 / test −16~−0.05), CCA 也必然 ≈1.0。
    修正: z 先做 **PCA(训练折内拟合, 16 维)**, 再回归/CCA → 检验才有意义。
  · 常数维 (std≈0, 如某轮 eta 恒 1.0) 直接跳过并标注, 不参与中位数。

用法:
  gui-venv311/bin/python tools/intact_fit_maps.py --mode decode
  gui-venv311/bin/python tools/intact_fit_maps.py --mode action
"""
import argparse
import glob
import json
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANI_NAMES = ["progress", "risk", "V", "eta", "rem", "dperp"]
ACTION_NAMES = ["dx", "dy", "dz", "gripper"]


def r2(y_true, y_pred, min_std=1e-6, rel_std=1e-4):
    """R²; 近常值真值 (如某轮 eta 恒 1.0) → NaN, 不参与中位数。
    两道闸: 绝对 (std<1e-6) + **相对** (std < 1e-4·|mean|) —— 实测 eta 值 ~1.0 且 std~1e-5,
    只看绝对闸会漏 (算出 −1e7 的假极端值)。"""
    y_true = np.asarray(y_true, float)
    s, m = float(y_true.std()), abs(float(y_true.mean()))
    if s < min_std or s < rel_std * m:
        return float("nan")
    ss_res = float(np.sum((y_true - y_pred) ** 2))
    ss_tot = float(np.sum((y_true - y_true.mean(axis=0)) ** 2))
    return 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else float("nan")


def fit_ridge(X, Y, alpha=1e-2):
    X = np.asarray(X, float)
    Y = np.asarray(Y, float)
    mx, my = X.mean(axis=0), Y.mean(axis=0)
    Xc, Yc = X - mx, Y - my
    W = np.linalg.solve(Xc.T @ Xc + alpha * np.eye(Xc.shape[1]), Xc.T @ Yc)
    return W, my - mx @ W


def pca_fit(X, k):
    """训练折内拟合 PCA, 返回 (mean, components [k,d], explained_ratio)。"""
    mu = X.mean(0)
    U, S, Vt = np.linalg.svd(X - mu, full_matrices=False)
    k = min(k, Vt.shape[0], X.shape[0] - 1)
    var = (S ** 2) / max(1, X.shape[0] - 1)
    er = var[:k] / var.sum() if var.sum() > 0 else np.zeros(k)
    return mu, Vt[:k], er


def cca_corr(X, Y, k=6):
    n = X.shape[0]
    Xc = (X - X.mean(0)) / (X.std(0) + 1e-9)
    Yc = (Y - Y.mean(0)) / (Y.std(0) + 1e-9)
    Ux, Sx, _ = np.linalg.svd(Xc, full_matrices=False)
    Uy, Sy, _ = np.linalg.svd(Yc, full_matrices=False)
    Xw = Ux[:, Sx > Sx.max() * 1e-8] * np.sqrt(n)
    Yw = Uy[:, Sy > Sy.max() * 1e-8] * np.sqrt(n)
    s = np.linalg.svd((Xw.T @ Yw) / n, compute_uv=False)
    return [round(float(v), 4) for v in s[:k]]


def loso_by_group(X, Y, names, grp, alpha=1e-2, pca_k=16, label=""):
    folds = sorted(set(grp.tolist()))
    per = {nm: [] for nm in names}
    null = {nm: [] for nm in names}
    cca, er0, n_te, n_tr = None, None, 0, 0
    keep = [j for j in range(Y.shape[1]) if Y[:, j].std() > 1e-9]
    dropped = [names[j] for j in range(Y.shape[1]) if j not in keep]
    rng = np.random.default_rng(0)
    for g in folds:
        te = np.where(grp == g)[0]
        tr = np.where(grp != g)[0]
        if len(tr) < 20 or len(te) < 5:
            continue
        mu, comp, er = pca_fit(X[tr], pca_k)
        Xtr, Xte = (X[tr] - mu) @ comp.T, (X[te] - mu) @ comp.T
        W, b = fit_ridge(Xtr, Y[tr], alpha)
        Wn, bn = fit_ridge(Xtr, Y[tr][rng.permutation(len(tr))], alpha)      # null 对照
        n_tr, n_te = len(tr), len(te)
        for j in keep:
            # 该折测试集必须是"这一维真有变化"的折 (否则 R² 分母≈0 → −1e7 之类假极端值)
            _gstd = float(Y[:, j].std())
            _ms = max(1e-6, 0.1 * _gstd)
            per[names[j]].append(r2(Y[te, j], Xte @ W[:, j] + b[j], min_std=_ms))
            null[names[j]].append(r2(Y[te, j], Xte @ Wn[:, j] + bn[j], min_std=_ms))
        if cca is None:
            cca = cca_corr(Xtr, Y[tr][:, keep], k=min(6, len(keep)))
            er0 = er
    return {"per_dim": per, "null": null, "cca_first_fold": cca,
            "pca_explained": (er0[:6].round(4).tolist() if er0 is not None else None),
            "dropped_const_dims": dropped, "n_train": n_tr, "n_test": n_te, "folds": len(folds)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True, choices=["action", "action_z", "decode"])
    ap.add_argument("--data", default="", help="配对 npz 路径或 glob")
    ap.add_argument("--alpha", type=float, default=1e-2)
    ap.add_argument("--pca-k", type=int, default=16, help="z 先降到 k 维再回归 (防 p≈n 假高)")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    paths = sorted(glob.glob(a.data)) if a.data else sorted(
        glob.glob(os.path.join(ROOT, "reports", "intact_pair_*.npz")))
    if not paths:
        print("❌ 找不到配对数据 (先跑 tools/intact_pair_collect.py)")
        return 2
    Z, CH, UF, MN, ST, GRP = [], [], [], [], [], []
    for gi, p in enumerate(paths):
        d = np.load(p, allow_pickle=True)
        Z.append(d["z_t"]); CH.append(d["chunk"]); UF.append(d["u_ff"])
        MN.append(d["mani6"]); ST.append(d["stage"])
        GRP.append(np.full(len(d["z_t"]), gi, dtype=np.int64))
    z_t = np.concatenate(Z); chunk = np.concatenate(CH); u_ff = np.concatenate(UF)
    mani6 = np.concatenate(MN); stage = np.concatenate(ST); grp = np.concatenate(GRP)
    print(f"数据 {len(paths)} 轮 · 样本 {len(z_t)} · 阶段 {sorted(set(stage.tolist()))}")
    finite = np.isfinite(z_t).all(1) & np.isfinite(chunk.reshape(len(chunk), -1)).all(1)

    if a.mode in ("action", "action_z"):
        m = finite & np.isfinite(u_ff).all(1)
        if a.mode == "action":
            X, pk = chunk[m, 0, :], int(chunk.shape[-1])
            src_desc = f"官方 {chunk.shape[-1]} 维动作 chunk (零搜索输出)"
        else:
            X, pk = z_t[m], a.pca_k
            src_desc = f"INTACT 潜空间 z_t(192→PCA{a.pca_k})  [对照: 若动作无信息, 看潜空间是否还有]"
        Y = u_ff[m]
        if len(X) < 40:
            print(f"❌ 有效配对太少 ({len(X)}) → 不做标定")
            return 3
        res = loso_by_group(X, Y, ACTION_NAMES, grp[m], a.alpha, pca_k=pk)
        print(f"\n═══ Step1 标定: {src_desc} → 引擎 u_ff 4 维 (留一轮交叉验证) ═══")
        print(f"   轮数 {res['folds']} · 每折 train≈{res['n_train']} / test≈{res['n_test']}")
        meds = []
        for nm in ACTION_NAMES:
            v = [x for x in res["per_dim"][nm] if np.isfinite(x)]
            nv = [x for x in res["null"][nm] if np.isfinite(x)]
            if v:
                meds.append(float(np.mean(v)))
            print(f"   {nm:8s} R²={np.mean(v):+.3f}±{np.std(v):.3f} (折 {[round(x,2) for x in v]}) · "
                  f"null {np.mean(nv):+.3f} · 真值 std={Y[:, ACTION_NAMES.index(nm)].std():.5f}")
        med = float(np.median(meds)) if meds else float("nan")
        print(f"   中位均值 R² = {med:+.3f}  ← 只有这项高, INTACT 动作里才含本引擎可用信息")
        rec = {"ts": time.strftime("%F %T"), "mode": a.mode, "n": int(len(X)),
               "folds": res["folds"], "alpha": a.alpha, "pca_k": pk, "input": src_desc,
               "per_axis": res["per_dim"],
               "null": res["null"], "r2_mean_median": round(med, 4),
               "source": [os.path.basename(x) for x in paths],
               "caveat": "标定=从 INTACT 输出回归本引擎 u_ff; 不代表 INTACT 优于蒸馏 MLP; "
                         "是否启用由 Step1 三臂 A/B (成功率不回退) 决定"}
        out = a.out or os.path.join(ROOT, "reports",
                                    f"intact_calib_{a.mode}_{time.strftime('%Y%m%d_%H%M%S')}.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=2)
        if a.mode != "action" and med > 0.05:
            print(f"   ℹ️ {a.mode} 有信号 (中位 R²={med:+.3f}) 但形状不是 10→4 → 本轮不写 "
                  f"intact_action_map.json (需另做解码器模块)")
        W, b = fit_ridge(X, Y, a.alpha)   # 保留: 部署用全量重拟合
        if a.mode == "action" and med > 0.05:
            mp = os.path.join(ROOT, "models", "intact_action_map.json")
            os.makedirs(os.path.dirname(mp), exist_ok=True)
            with open(mp, "w", encoding="utf-8") as f:
                json.dump({"linear_W": W.tolist(), "linear_b": b.tolist(),
                           "r2_mean_median": round(med, 4), "per_axis": res["per_dim"],
                           "source": rec["source"], "n": int(len(X)),
                           "note": "tools/intact_fit_maps.py --mode action; 启用与否由 Step1 A/B 决定"},
                          f, ensure_ascii=False, indent=2)
            print(f"   → 映射写入 {mp} (中位 R²={med:+.3f} > 0.05 下限)")
        else:
            print(f"   ⚠️ 中位 R²={med:+.3f} ≤ 0.05 → **不写映射** (映射不出有效信息, 硬用=假接入)")
        print(f"   → 报告 {out}")
        return 0

    # ── decode ──
    m = finite & np.isfinite(mani6).all(1)
    X, Y = z_t[m], mani6[m]
    if len(X) < 60:
        print(f"❌ 有效配对太少 ({len(X)}) → 不做可解码性判定")
        return 3
    res = loso_by_group(X, Y, MANI_NAMES, grp[m], a.alpha, pca_k=a.pca_k)
    print(f"\n═══ Step2 可解码性: INTACT z_t(192→PCA{a.pca_k}) → 引擎流形真值 6 维 (留一轮) ═══")
    print(f"   轮数 {res['folds']} · 每折 train≈{res['n_train']} / test≈{res['n_test']} · "
          f"PCA 前6 解释率 {res['pca_explained']}")
    if res["dropped_const_dims"]:
        print(f"   ⚠️ 跳过常数维 (std≈0, 不可评): {res['dropped_const_dims']}")
    r2m = []
    for nm in MANI_NAMES:
        v = [x for x in res["per_dim"].get(nm, []) if np.isfinite(x)]
        nv = [x for x in res["null"].get(nm, []) if np.isfinite(x)]
        if not v:
            print(f"   {nm:9s} 跳过 (常数维)")
            continue
        r2m.append(float(np.mean(v)))
        print(f"   {nm:9s} R²={np.mean(v):+.3f}±{np.std(v):.3f} (折 {[round(x,2) for x in v]}) · "
              f"null={np.mean(nv):+.3f}")
    med = float(np.median(r2m)) if r2m else float("nan")
    cc = res["cca_first_fold"] or []
    # 「部分可解码」裁决: 逐维看 (均值 R²>0.3 且 null<0.1 才算有真信号)
    good = [nm for nm in MANI_NAMES
            if res["per_dim"].get(nm) and np.isfinite(np.mean(res["per_dim"][nm]))
            and np.mean(res["per_dim"][nm]) > 0.30 and np.mean(res["null"][nm]) < 0.10]
    print(f"   中位均值 R²={med:+.3f} · CCA 典型相关(首折训练)={cc}")
    print(f"   有真信号的维 (R²>0.3 且 null<0.1): {good or '无'}")
    if len(good) >= 4:
        verdict = f"**可解码** ({len(good)}/6: {good}) → 允许进 Step2 接流形"
    elif good:
        verdict = (f"**部分可解码** ({len(good)}/6: {good}; 其余维不可解) → 只允许这些维进流形, "
                   f"其余维先做 z→本工程潜空间对齐映射 (Procrustes/蒸馏), 不接受整体硬接")
    else:
        verdict = "**不可解码** → 不接流形; 先做 z→本工程潜空间对齐映射 (Procrustes/蒸馏)"
    print(f"   裁决: {verdict}")
    rec = {"ts": time.strftime("%F %T"), "mode": "decode", "n": int(len(X)), "folds": res["folds"],
           "alpha": a.alpha, "pca_k": a.pca_k, "pca_explained_top6": res["pca_explained"],
           "per_dim": res["per_dim"], "null": res["null"], "r2_mean_median": round(med, 4),
           "cca_first_fold": cc, "verdict": verdict,
           "source": [os.path.basename(x) for x in paths],
           "caveat": "相关性≠可用: 通过才允许接流形 (Step2 前置闸)"}
    out = a.out or os.path.join(ROOT, "reports", f"intact_decode_probe_{time.strftime('%Y%m%d_%H%M%S')}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)
    print(f"   → 报告 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
