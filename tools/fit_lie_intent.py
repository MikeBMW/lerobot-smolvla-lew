#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧭 fit_lie_intent.py — 标定 "INTACT 意图 Δz(192) → 李代数" 的丛映射 Φ

教师标签 (全部引擎真值, 逐帧差分得到, 不写死几何):
    ω_true(t) ∈ su(2)≅R³  : 光模块/末端 相对旋转 ΔU = U_{t+1}U_t⁻¹ 的 log
    ξ_true(t) ∈ se(3)≅R⁶  : 同一帧间刚体运动 (ω, v), v = 位置增量
    e_true(t) ∈ se(3)≅R⁶  : 接触 twist = log(T_hole⁻¹·T_peg) (孔系表达的接触误差)

输入: 引擎真跑采的 npz (SS_L4_FIBER=1 + SS_L4_FIBER_DATA=... + SS_INTACT_EVERY=1)
输出: models/lie_intent_map.json (含 PCA 基 + W_su2/W_se3 + LOO R²/null 元数据)

用法: python tools/fit_lie_intent.py [reports/lie_calib_s*.npz ...]
"""
from __future__ import annotations

import glob
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "src")]

from lerobot.manifold.lie_intent import (LieIntentMap, contact_twist, contact_decompose,
                                        quat_log, quat_relative, se3_make, vec_hash)  # noqa: E402


def _pairs(paths: list[str]):
    """逐文件读样本 → (Δz, ω_true, ξ_true, e_true, stage)。只在**同文件内**做逐帧差分。"""
    X, Yw, Yx, Ye, ST = [], [], [], [], []
    for p in paths:
        d = np.load(p, allow_pickle=True)
        if "ee_p" not in d:
            print(f"  ⚠️ {os.path.basename(p)}: 无李群真值键 (旧采样) → 跳过")
            continue
        zt, zp = d["z_t"], d["z_pred"]
        ee_p, ee_q = d["ee_p"], d["ee_q"]
        pg_p, pg_q = d["peg_p"], d["peg_q"]
        hl_p, hl_q = d["hole_p"], d["hole_q"]
        st = d["stage"]
        n = len(zt)
        for i in range(n - 1):
            dz = zp[i] - zt[i]                                        # INTACT 意图 Δz
            # 帧间刚体运动 (末端): 旋转 + 平移
            du = quat_relative(ee_q[i + 1], ee_q[i])
            w_true = quat_log(du)                                     # su(2) ≅ R³
            v_true = (ee_p[i + 1] - ee_p[i]).astype(float)            # 平移 (m/步)
            # 光模块绕插拔轴的旋转 (SU(2) 意图的物理含义) —— 用同一个 du 的轴向分量
            e_tw = contact_twist(se3_make(pg_q[i], pg_p[i]), se3_make(hl_q[i], hl_p[i]))
            X.append(dz)
            Yw.append(w_true)
            Yx.append(np.concatenate([w_true, v_true]))
            Ye.append(e_tw)
            ST.append(str(st[i]))
    return (np.asarray(X, float), np.asarray(Yw, float), np.asarray(Yx, float),
            np.asarray(Ye, float), np.asarray(ST))


def main() -> int:
    args = sys.argv[1:]
    paths = args or sorted(glob.glob(os.path.join(ROOT, "reports", "lie_calib_s*.npz")))
    paths = [p for p in paths if os.path.isfile(p)]
    if not paths:
        print("❌ 无样本。先采:\n  SS_L4_FIBER=1 SS_L4_FIBER_DATA=reports/lie_calib_s0.npz "
              "SS_INTACT_EVERY=1 python tools/probe_l4_callchain.py L4audit 300")
        return 2
    print("🧭 李群意图标定 — 意图 Δz → su(2)/se(3)")
    for p in paths:
        print(f"  {os.path.basename(p)}: n={int(np.load(p)['n'][0])}")
    X, Yw, Yx, Ye, ST = _pairs(paths)
    if len(X) < 30:
        print(f"❌ 有效样本 {len(X)} < 30, 不够标定")
        return 2
    print(f"  逐帧成对样本 n={len(X)} · 阶段分布={ {s: int((ST == s).sum()) for s in set(ST.tolist())} }")
    print(f"  ‖Δz‖ 均值={np.linalg.norm(X, axis=1).mean():.4f} · "
          f"‖ω_true‖(rad/步) 均值={np.linalg.norm(Yw, axis=1).mean():.4f} · "
          f"‖v_true‖(mm/步) 均值={np.linalg.norm(Yx[:, 3:], axis=1).mean()*1000:.4f}")

    # ── Φ: Δz → su(2) / se(3) ──
    m = LieIntentMap(gate=0.30, pca_dim=32)
    res = m.fit(X, Yw, Yx)
    print("── 拟合 ──")
    for k, r in res.items():
        print(f"   Φ_{k}  dim={r['dim']}  R²={r['r2']:+.4f}  R²_loso={r['r2_loso']:+.4f}  "
              f"null={r['null']:+.4f}  逐维R²_loso={r['per_dim_loso']}")
    print(f"   ready={m.ready} (闸: R²_loso(se3) ≥ 0.30 且 null < 0.10)")

    # ── 接触 twist 的几何量 (真值, 供审计/势函数) ──
    _p, _l, _a = (np.asarray([contact_decompose(e) for e in Ye], float).T)
    print(f"── 接触 twist (孔系): 进度均值={np.mean(_p)*1000:+.2f}mm · 横向={np.mean(_l)*1000:.2f}mm · "
          f"姿态={np.rad2deg(np.mean(_a)):.2f}° ──")

    out = {"W_su2": m.W_su2.tolist(), "W_se3": m.W_se3.tolist(),
           "pca_mu": m.P["mu"].tolist(), "pca_V": m.P["V"].tolist(),
           "ready": bool(m.ready), "gate": 0.30, "ridge": m.ridge, "pca_dim": m.pca_dim,
           "meta": res, "n": len(X),
           "hash": vec_hash(np.concatenate([m.W_su2.ravel(), m.W_se3.ravel()])),
           "note": ("Φ: INTACT 意图 Δz(192) → su(2) 旋转意图 ω 与 se(3) 刚体意图 (ω,v) = "
                    "log(T_ee(t+1)·T_ee(t)⁻¹) 的教师标签; 教师全部引擎真值逐帧差分, 无写死几何"),
           "source_files": [os.path.basename(p) for p in paths]}
    dst = os.path.join(ROOT, "models", "lie_intent_map.json")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"── 落盘 {os.path.relpath(dst, ROOT)} (ready={m.ready}, hash={out['hash']}) ──")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
