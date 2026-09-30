# -*- coding: utf-8 -*-
"""🎯 INTACT 动作 → 本引擎 u_ff 标定 (Step 1): 产出 models/intact_action_map.json

口径 (2026-09-12 修正, 老倪 Step 1 = "保留 INTACT 原生能力, 数据直接进, 输出 action 到前馈加速器"):
  ✗ 旧口径 (已判死): 官方动作 → **岭回归/线性回归** 拟合解析 u_ff
     → 5折样本外 R²: 全局 0.043, 分阶段 -0.63 (过拟合)。原因: 解析 u_ff 是分阶段状态机语义,
       用线性映射去拟合它 = 让 INTACT 蒸馏手写状态机, 不可达 → 不能据此判"INTACT 动作无用"。
  ✓ 新口径: **物理量纲对齐**。ActionAdapter 契约本来就是
       out[:, axis] = chunk[:, slice[axis]] · scale[axis]
     即"选维 + 每轴一个尺度(含符号)"; 标定 = 用真实配对数据**选出**哪个官方维度对应哪个轴,
     解出尺度 K = cov(c_j, u_a)/var(c_j) (单变量最小二乘, 令二者同尺度)。不模仿状态机。

诚实闸 (不过闸 → **不写文件**, adapter 继续拒绝映射; 不许把垃圾放进默认档):
  · 每轴 |Spearman ρ| ≥ --min-rho (默认 0.30), 且引擎该轴在数据里有信号 (std > 1e-6)
  · **嵌套 5 折样本外 R²** ≥ --min-r2 (默认 0.20): 每折在训练折上重选维度/尺度, 再在测试折打分
  · gripper 轴: 本引擎 u_ff[3] 恒 0 (夹爪归状态机, SS_INTACT 只接管 xyz) → 尺度 0.0,
    在 fit_metrics 显式标注 "不参与标定", **不计入闸** (不许假装标了, 也不许拿它卡闸)

用法:
  ./gui-venv311/bin/python tools/calib_intact_action_map.py \
      --pairs 'reports/intact_pair_ft_seed*.npz' --out models/intact_action_map.json [--dry-run]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time

import numpy as np
from scipy.stats import spearmanr

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
AXES_GATED = ["x", "y", "z"]                 # INTACT 接管轴 (gripper 归状态机)
ALL_AXES = ["x", "y", "z", "gripper"]


def load_pairs(pattern: str):
    files = sorted(glob.glob(pattern)) if any(c in pattern for c in "*?[") else [pattern]
    if not files:
        raise FileNotFoundError(f"没有匹配的配对文件: {pattern}")
    C, U, src, metas = [], [], [], []
    for f in files:
        z = np.load(f, allow_pickle=True)
        c, u = np.asarray(z["chunk"], np.float32), np.asarray(z["u_ff"], np.float32)
        n = min(len(c), len(u))
        ok = np.isfinite(u[:n]).all(1) & np.isfinite(c[:n]).all((1, 2))
        meta = z["meta"][0] if "meta" in z.files else {}
        meta = dict(meta) if not isinstance(meta, str) else {"raw": meta}
        print(f"  · {os.path.basename(f)}: 有效 {int(ok.sum())}/{n} · policy={meta.get('policy', '?')}"
              f" · obs_source={meta.get('obs_source', '?')}")
        if ok.sum() == 0:
            continue
        C.append(c[:n][ok]); U.append(u[:n][ok]); src.append(os.path.basename(f)); metas.append(meta)
    if not C:
        raise RuntimeError("所有配对文件都没有有效样本")
    return np.concatenate(C), np.concatenate(U), src, metas


def agg(chunk: np.ndarray, mode: str) -> np.ndarray:
    return chunk[:, 0, :] if mode == "first" else chunk.mean(1)


def fit_axis(Dtr: np.ndarray, ua: np.ndarray, min_rho: float):
    """返回 (best_dim, scale, rho, ok)。Dtr=[n,d] 聚合后的官方动作。"""
    if float(np.std(ua)) <= 1e-6:
        return None, 0.0, 0.0, False
    rhos = np.array([spearmanr(Dtr[:, j], ua)[0] for j in range(Dtr.shape[1])], float)
    rhos = np.nan_to_num(rhos)
    j = int(np.argmax(np.abs(rhos)))
    c = Dtr[:, j]
    var = float(np.dot(c - c.mean(), c - c.mean()))
    k = float(np.dot(c - c.mean(), ua - ua.mean()) / var) if var > 1e-12 else 0.0
    return j, k, float(rhos[j]), bool(abs(rhos[j]) >= min_rho)


def nested_oof(chunk, U, slices, scales, folds=5, seed=0):
    """嵌套 5 折: 每折训练折重选维度/尺度 → 测试折打分。返回 (pooled R², 每轴 R²)。"""
    N, H, D = chunk.shape
    rng = np.random.default_rng(seed)
    idx = rng.permutation(N)
    pred = np.full((N, H, len(ALL_AXES)), np.nan, np.float32)
    A = agg(chunk, G_AGG)
    for te in np.array_split(idx, folds):
        tr = np.setdiff1d(idx, te)
        sl, sc = {}, {}
        for ai, ax in enumerate(ALL_AXES):
            if ax == "gripper":
                sl[ax], sc[ax] = 0, 0.0
                continue
            j, k, rho, ok = fit_axis(A[tr], U[tr, ai], MIN_RHO)
            sl[ax], sc[ax] = (j if j is not None else 0), (k if ok else 0.0)
        M = np.stack([chunk[:, :, sl[ax]] * sc[ax] for ax in ALL_AXES], -1)
        pred[te] = M[te]
    Y = np.repeat(U[:, None, :], H, 1)
    per = {}
    for ai, ax in enumerate(ALL_AXES):
        y, p = Y[:, :, ai].ravel(), pred[:, :, ai].ravel()
        ss = ((y - y.mean()) ** 2).sum()
        per[ax] = float(1 - ((y - p) ** 2).sum() / ss) if ss > 0 else float("nan")
    all_true = Y[:, :, :len(AXES_GATED)].ravel()
    all_pred = pred[:, :, :len(AXES_GATED)].ravel()
    ss = ((all_true - all_true.mean()) ** 2).sum()
    return float(1 - ((all_true - all_pred) ** 2).sum() / ss), per


def main():
    global G_AGG, MIN_RHO
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", default="reports/intact_pair_ft_seed*.npz")
    ap.add_argument("--out", default=os.path.join(ROOT, "models", "intact_action_map.json"))
    ap.add_argument("--min-rho", type=float, default=0.30)
    ap.add_argument("--min-r2", type=float, default=0.20)
    ap.add_argument("--aggregate", default="first", choices=["first", "mean"])
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    G_AGG, MIN_RHO = a.aggregate, a.min_rho

    print(f"═══ INTACT → u_ff 标定 (物理量纲对齐, 非回归) · pairs={a.pairs} ═══")
    chunk, U, src, metas = load_pairs(a.pairs)
    N, H, D = chunk.shape
    pol = sorted({str(m.get("policy", "?")) for m in metas})
    rt = sorted({str(m.get("runtime", "?")) for m in metas})
    oss = sorted({str(m.get("obs_source", "?")) for m in metas})
    print(f"   配对 N={N} · chunk=[{H},{D}] · 权重={pol} · runtime={rt}")
    print(f"   观测来源={oss}")
    print("   引擎 u_ff 各轴 std: " + ", ".join(f"{ax}={U[:, i].std():.4f}" for i, ax in enumerate(ALL_AXES)))

    A = agg(chunk, a.aggregate)
    print(f"\n-- 每轴 × 官方 {D} 维 Spearman ρ (聚合={a.aggregate}, 全量) --")
    print("  轴        " + " ".join(f"d{j:<6}" for j in range(D)))
    stats = {}
    for ai, ax in enumerate(ALL_AXES):
        if float(np.std(U[:, ai])) <= 1e-6:
            stats[ax] = {"has_signal": False, "best_dim": None, "best_rho": 0.0,
                         "scale": 0.0, "rho_row": [0.0] * D}
            print(f"  {ax:<8} (引擎该轴 std≈0 → 不可标定)")
            continue
        rhos = np.nan_to_num([spearmanr(A[:, j], U[:, ai])[0] for j in range(D)])
        j = int(np.argmax(np.abs(rhos)))
        c = A[:, j]
        k = float(np.dot(c - c.mean(), U[:, ai] - U[:, ai].mean()) / max(np.dot(c - c.mean(), c - c.mean()), 1e-12))
        stats[ax] = {"has_signal": True, "best_dim": j, "best_rho": float(rhos[j]), "scale": k,
                     "rho_row": [round(float(x), 3) for x in rhos]}
        print(f"  {ax:<8} " + " ".join(f"{x:+.2f}  " for x in rhos))

    print("\n-- 选定 (选维 + 尺度) --")
    slices, scales, fails = {}, {}, []
    for ai, ax in enumerate(ALL_AXES):
        st = stats[ax]
        if ax == "gripper":
            slices[ax], scales[ax] = 0, 0.0
            print(f"  {ax:<8} 尺度 0.0 (不参与: u_ff[3] 恒 0, 夹爪归状态机)")
            continue
        slices[ax], scales[ax] = int(st["best_dim"]), float(st["scale"])
        flag = "" if abs(st["best_rho"]) >= a.min_rho else f"  ❌ |ρ|<{a.min_rho}"
        print(f"  {ax:<8} ← chunk d{st['best_dim']} × {st['scale']:+.5f}   "
              f"(|ρ|={abs(st['best_rho']):.3f}, 引擎轴std={U[:, ai].std():.4f}){flag}")
        if not st["has_signal"]:
            fails.append(f"{ax}: 引擎轴无信号")
        elif abs(st["best_rho"]) < a.min_rho:
            fails.append(f"{ax}: |ρ|={abs(st['best_rho']):.3f} < 闸 {a.min_rho}")

    r2, per = nested_oof(chunk, U, slices, scales)
    print(f"\n-- 嵌套5折样本外 R² (每折重选维/尺度) --")
    print("   逐轴: " + ", ".join(f"{k}={v:+.3f}" for k, v in per.items() if k in AXES_GATED))
    print(f"   xyz 合并 = {r2:+.4f}  (闸 {a.min_r2})")
    if fails:
        print("   ⚠️ 未过闸: " + " | ".join(fails))

    ok = (not fails) and r2 >= a.min_r2
    fit = {"aggregate": a.aggregate, "oof_r2_xyz_nested5fold": round(r2, 4),
           "oof_r2_per_axis": {k: round(v, 4) for k, v in per.items()},
           "n_samples": int(N), "chunk_dim": int(D), "horizon": int(H),
           "policy": pol, "runtime": rt, "obs_source": oss,
           "per_axis": {ax: {"best_dim": stats[ax]["best_dim"], "best_rho": stats[ax]["best_rho"],
                             "scale": round(float(scales[ax]), 7),
                             "engine_axis_std": round(float(U[:, i].std()), 6)}
                        for i, ax in enumerate(ALL_AXES)},
           "gripper_note": "u_ff[3] 本引擎恒 0 → gripper 由状态机接管, 尺度 0, 不计入闸",
           "verdict": "PASS 写入" if ok else "FAIL 拒绝写入 (adapter 继续拒绝映射)"}

    if not ok:
        print("\n❌ 标定未过闸 → **不写标定文件** (adapter 继续拒绝映射, 诚实)")
        if not a.dry_run:
            rep = os.path.join(ROOT, "reports",
                               f"intact_calib_map_{time.strftime('%Y%m%d_%H%M%S')}_FAIL.json")
            json.dump({"fit_metrics": fit, "fails": fails, "sources": src},
                      open(rep, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print(f"   失败留档: {rep}")
        return 1

    payload = {"slice": {k: int(v) for k, v in slices.items()},
               "scale": {k: round(float(v), 7) for k, v in scales.items()},
               "source": (f"tools/calib_intact_action_map.py · 数据={'+'.join(src)} · 权重={pol} · "
                          f"runtime={rt} · {time.strftime('%F %T')}"),
               "n_samples": int(N), "fit_metrics": fit}
    print("\n✅ 过闸 → 写出标定映射:")
    print(json.dumps(payload, ensure_ascii=False, indent=1)[:1400])
    if a.dry_run:
        print("(dry-run: 未写文件)")
        return 0
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump(payload, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"   → {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
