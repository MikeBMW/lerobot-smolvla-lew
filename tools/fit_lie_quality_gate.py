#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🛡 fit_lie_quality_gate.py — 质量闸: "上层提案是否真的优于 L2" (抬增益的前置判据)

老倪门槛: 未证明提升不得进默认档 ⇒ 增益抬升 (K>0) 之前必须先判"这一阶段上层是否比 L2 更对"。

判据 (全部用引擎真值样本, 不看引擎内部计数):
    任务几何梯度  g = unit(孔口 − 末端)         ← 减少接触势的物理"对"方向
    L4 提案方向   ξ̂_v = Φ_se3(Δz) 的平移部分   ← **LOSO 预测** (留一 seed, 不在拟合集上评估)
    L2 参考方向   ẋ_hand (真实执行速度)          ← 引擎实际下发方向 (L2 收口后的结果)
    cos_L4 = cos(ξ̂_v, g) · cos_L2 = cos(ẋ_hand, g)
    判定: cos_L4 > cos_L2 + margin(默认 0.05) → 该阶段 pass (允许 K>0)

输出 models/lie_quality_gate.json。引擎按阶段读它: 未过闸 ⇒ K 强制 0 (只记录不抬增益)。

用法: python tools/fit_lie_quality_gate.py
"""
from __future__ import annotations

import glob
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "src")]

from lerobot.manifold.lie_intent import LieIntentMap, quat_log, quat_relative  # noqa: E402

MARGIN = float(os.environ.get("SS_QUALITY_MARGIN", "0.05"))


def load():
    """→ X(Δz), Y_teacher(ξ_true), seed, stage, G(任务梯度), XD(执行速度)"""
    X, Y, SD, ST, G, XD = [], [], [], [], [], []
    paths = [p for p in sorted(glob.glob(os.path.join(ROOT, "reports", "lie_calib_s*.npz")))
             if os.path.isfile(p)]
    for p in paths:
        d = np.load(p, allow_pickle=True)
        if "ee_p" not in d:
            continue
        seed = int(os.path.basename(p).split("_s")[-1].split(".")[0])
        zt, zp, ee_p, hl_p, x_hist, stg = d["z_t"], d["z_pred"], d["ee_p"], d["hole_p"], d["x"], d["stage"]
        for i in range(len(zt) - 1):
            g = np.asarray(hl_p[i], float) - np.asarray(ee_p[i], float)
            ng = float(np.linalg.norm(g))
            if ng < 1e-9:
                continue
            du = quat_relative(d["ee_q"][i + 1], d["ee_q"][i])
            v = np.asarray(ee_p[i + 1], float) - np.asarray(ee_p[i], float)
            X.append(np.asarray(zp[i] - zt[i], float))
            Y.append(np.concatenate([quat_log(du), v]))
            SD.append(seed)
            ST.append(str(stg[i]))
            G.append(g / ng)
            XD.append(np.asarray(x_hist[i + 1], float) - np.asarray(x_hist[i], float))
    return (np.asarray(X, float), np.asarray(Y, float), np.asarray(SD, int),
            np.asarray(ST), np.asarray(G, float), np.asarray(XD, float))


def _cos(a, b):
    na, nb = np.linalg.norm(a, axis=1), np.linalg.norm(b, axis=1)
    ok = (na > 1e-9) & (nb > 1e-9)
    out = np.zeros(len(a))
    out[ok] = np.sum(a[ok] * b[ok], axis=1) / (na[ok] * nb[ok])
    return out


def main() -> int:
    X, Y, SD, ST, G, XD = load()
    if len(X) < 50:
        print(f"❌ 样本不足 ({len(X)})")
        return 2
    print(f"🛡 质量闸 — 样本 n={len(X)} · seed {sorted(set(SD.tolist()))} · margin={MARGIN}")

    # ── LOSO: 用其它 seed 拟合 Φ_se3, 预测本 seed 的 ξ (诚实: 预测不在拟合集上) ──
    pred = np.full((len(X), 6), np.nan)
    for s in sorted(set(SD.tolist())):
        te = SD == s
        tr = ~te
        if te.sum() < 5 or tr.sum() < 30:
            continue
        mm = LieIntentMap(gate=0.30, pca_dim=32)
        mm.fit(X[tr], Y[tr][:, :3], Y[tr])
        _, xi = mm.predict_batch(X[te])
        pred[te] = xi
    ok_rows = np.isfinite(pred).all(1)
    print(f"  LOSO 预测覆盖 {int(ok_rows.sum())}/{len(X)} 帧")

    cos_l4 = np.full(len(X), np.nan)
    cos_l4[ok_rows] = _cos(pred[ok_rows, 3:], G[ok_rows])
    cos_l2 = _cos(XD, G)

    print("── 逐阶段: 上层 (L4 ξ̂_v, LOSO) vs 执行层 (ẋ_hand) 与任务梯度的对齐 ──")
    print(f"  {'阶段':<8}{'n':>5}{'cos_L4':>10}{'cos_L2':>10}{'差':>10}  判定")
    gate = {}
    for st in sorted(set(ST.tolist())):
        m = (ST == st) & ok_rows
        if m.sum() < 20:
            print(f"  {st:<8}{int(m.sum()):>5}   (样本 <20, 不判)")
            continue
        c4, c2 = float(np.nanmean(cos_l4[m])), float(np.nanmean(cos_l2[m]))
        pas = bool(c4 > c2 + MARGIN)
        gate[st] = {"n": int(m.sum()), "cos_l4": round(c4, 4), "cos_l2": round(c2, 4),
                    "delta": round(c4 - c2, 4), "pass": pas}
        print(f"  {st:<8}{int(m.sum()):>5}{c4:>10.4f}{c2:>10.4f}{c4 - c2:>+10.4f}  "
              f"{'✅ 允许抬增益' if pas else '⛔ 只记录不抬 (上层不优于 L2)'}")
    c4a, c2a = float(np.nanmean(cos_l4[ok_rows])), float(np.nanmean(cos_l2[ok_rows]))
    gpass = bool(c4a > c2a + MARGIN)
    print(f"  {'全局':<8}{int(ok_rows.sum()):>5}{c4a:>10.4f}{c2a:>10.4f}{c4a - c2a:>+10.4f}  "
          f"{'✅' if gpass else '⛔'}")

    out = {"margin": MARGIN, "n": int(ok_rows.sum()), "stages": gate,
           "global": {"cos_l4": round(c4a, 4), "cos_l2": round(c2a, 4), "pass": gpass},
           "note": ("质量闸: 逐阶段判 上层提案方向 (Φ_se3(Δz) 的 LOSO 预测) 是否比执行层实际方向 "
                    "更贴近任务几何梯度 (孔口−末端); 未过闸阶段 K 强制 0 = 只记录不抬增益")}
    dst = os.path.join(ROOT, "models", "lie_quality_gate.json")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    _ok = [k for k, v in gate.items() if v["pass"]]
    print(f"── 落盘 {os.path.relpath(dst, ROOT)} (允许抬增益: {_ok or '无'}) ──")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
