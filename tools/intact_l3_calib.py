#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧮 第①步: 出 L4→L3 条件标定文件 models/intact_l3_map.json (真数据拟合, 不写死)

数据: reports/intact_pair_*.npz (每帧同源: INTACT 潜空间 z_t(192) + 引擎流形真值 6 维 mani6)
方法 (沿用 tools/intact_fit_maps.py 的判据, 不另立标准):
  · 留一轮交叉验证 (LOSO by 文件轮次): 每折 PCA(16, 折内拟合) → 岭回归 → **测试集** R²
  · null 对照: 打乱标签重跑同一流程 (真信号须显著高于 null)
  · 逐维闸: 测试 R² 均值 > 0.3 **且** null R² < 0.1 才允许进 L3 条件 (其余维置 0, 绝不硬接)
  · 部署映射 = 全量数据 raw z(192) → mani6 的岭回归 (与 decoder.py 的 W@z+b 口径一致)

输出: models/intact_l3_map.json (schema = IntactIntentDecoder 读的那份)
  {"l3_cond": {"w": (6,192), "b": (6,), "used_dims": [...], "r2_min": .., "null_r2": ..}, "meta": {...}}
用法: gui-venv311/bin/python tools/intact_l3_calib.py [--dry-run]
"""
from __future__ import annotations

import argparse
import glob
import importlib.util
import json
import os
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANI_NAMES = ["progress", "risk", "V", "eta", "rem", "dperp"]
R2_GATE, NULL_GATE = 0.30, 0.10


def _load_fit_tool():
    p = os.path.join(ROOT, "tools", "intact_fit_maps.py")
    spec = importlib.util.spec_from_file_location("_intact_fit_maps", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.path.join(ROOT, "reports", "intact_pair_*.npz"))
    ap.add_argument("--alpha", type=float, default=1e-2)
    ap.add_argument("--pca-k", type=int, default=16)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default=os.path.join(ROOT, "models", "intact_l3_map.json"))
    a = ap.parse_args()

    F = _load_fit_tool()
    paths = sorted(glob.glob(a.data))
    if not paths:
        print("❌ 找不到配对数据 (先跑 tools/intact_pair_collect.py)")
        return 2
    Z, MN, GRP, SRC = [], [], [], []
    for gi, p in enumerate(paths):
        d = np.load(p, allow_pickle=True)
        Z.append(d["z_t"]); MN.append(d["mani6"])
        GRP.append(np.full(len(d["z_t"]), gi, dtype=np.int64))
        SRC.append(os.path.basename(p))
    z = np.concatenate(Z); y = np.concatenate(MN); grp = np.concatenate(GRP)
    m = np.isfinite(z).all(1) & np.isfinite(y).all(1)
    z, y, grp = z[m], y[m], grp[m]
    print(f"配对数据: {len(paths)} 轮 · 有效样本 {len(z)} · z 维 {z.shape[1]} · 流形真值 {y.shape[1]}")

    res = F.loso_by_group(z, y, MANI_NAMES, grp, a.alpha, pca_k=a.pca_k)
    print(f"\n═══ 可解码性 (LOSO {res['folds']} 折 · 每折 train≈{res['n_train']} / test≈{res['n_test']}) ═══")
    used, per_dim = [], {}
    for j, nm in enumerate(MANI_NAMES):
        v = np.asarray([x for x in res["per_dim"][nm] if np.isfinite(x)], float)
        nv = np.asarray([x for x in res["null"][nm] if np.isfinite(x)], float)
        r2m = float(v.mean()) if v.size else float("nan")
        n2m = float(np.nanmean(nv)) if nv.size else float("nan")
        ok = np.isfinite(r2m) and r2m > R2_GATE and (not np.isfinite(n2m) or n2m < NULL_GATE)
        per_dim[nm] = {"r2_mean": round(r2m, 4), "null_mean": round(n2m, 4), "std": round(float(v.std()), 4) if v.size else None,
                       "ok": bool(ok)}
        print(f"   {nm:9s} R²={r2m:+.3f} (std {per_dim[nm]['std']}) · null {n2m:+.3f} · "
              f"真值std={y[:, j].std():.5f} → {'✅ 可解码(进条件)' if ok else '❌ 不可解码(置0)'}")
        if ok:
            used.append(nm)
    print(f"\n结论: 可解码 {len(used)}/6 → {used or '(无)'}  "
          f"(闸: 测试 R²>{R2_GATE} 且 null<{NULL_GATE}; 其余维置 0, 不接受整体硬接)")
    if not used:
        print("❌ 没有任何维过闸 → **不写标定文件** (硬接=假接入)")
        return 3

    # 部署映射: 全量 raw z → mani6 (与 decoder W@z+b 同口径), 只保留过闸维
    W_raw, b = F.fit_ridge(z, y, a.alpha)          # (192, 6), (6,)
    W6 = np.zeros((len(MANI_NAMES), z.shape[1]), dtype=np.float64)
    bt = np.zeros(len(MANI_NAMES), dtype=np.float64)
    for j, nm in enumerate(MANI_NAMES):
        if nm in used:
            W6[j] = W_raw[:, j]
            bt[j] = b[j]
    rec = {
        "l3_cond": {
            "w": W6.tolist(), "b": bt.tolist(), "used_dims": used,
            "r2_min": round(min(per_dim[nm]["r2_mean"] for nm in used), 4),
            "null_r2": round(max(per_dim[nm]["null_mean"] for nm in used), 4),
            "dim_names": MANI_NAMES,
        },
        "meta": {
            "ts": time.strftime("%F %T"), "tool": "tools/intact_l3_calib.py",
            "method": f"LOSO({res['folds']} 折) PCA({a.pca_k})→岭回归(alpha={a.alpha}) 测试集 R² + 打乱标签 null; "
                      f"部署映射 = 全量 raw z({z.shape[1]})→流形6 岭回归, 仅过闸维非零",
            "n_samples": int(len(z)), "n_rounds": len(paths),
            "per_dim": per_dim,
            "source": SRC,
            "caveat": "相关性 ≠ 可用: 本文件只把**可解码维**作为 L4→L3 条件通道; 是否提升任务成功率须由 "
                      "L4 A/B (同口径对照) 判定, 未证明提升不得作为默认接管依据",
        },
    }
    print(json.dumps({k: (v if k != "l3_cond" else {kk: (f"<{np.shape(vv)} 矩阵>" if kk == "w" else vv)
                                                   for kk, vv in v.items()})
                      for k, v in rec.items()}, ensure_ascii=False, indent=2)[:1200])
    if a.dry_run:
        print("(--dry-run: 不写文件)")
        return 0
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 写入 {os.path.relpath(a.out, ROOT)} · 过闸维 {used} · "
          f"R²_min={rec['l3_cond']['r2_min']} · null={rec['l3_cond']['null_r2']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
