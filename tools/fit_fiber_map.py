#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧬 纤维丛联络标定 — 用真实采集的对偶数据拟合 Φ (潜空间丛 Z → 接触丛 C) 等映射。

数据来源: 引擎在 SS_L4_FIBER=1 + SS_L4_FIBER_DATA=<npz> 下每帧采的成对样本
  · z_t / z_pred (INTACT 世界模型 encode 与 **predictor 预测的下一步潜空间**)
  · contact  (接触丛真值 F_C(6): 切向进度/法向偏离/V/V̇/切向速度/法向速度)
  · z7_geo   (引擎几何潜空间 R7)
  · perf     (性能丛真值 F_P(6); 插拔任务次要)

产出: models/intact_fiber_map.json
  · l3_contact     Φ: z_pred → 接触丛 (二次项, 让曲率非零)
  · geom_contact   Φ_geo: z7_geo → 接触丛 (canonical 几何联络的对照)
  · z7_morph       A: z_pred → z7_geo (丛映射; 喂既有流形专家预测器, 权重不动)
  · perf           Φ_p: z_pred → 性能丛 (只记录, w_perf=0)

闸值: R²_LOSO ≥ 0.30 且 null-R² < 0.10 (与 intact_l3_map / intent_line 同一纪律);
      未过闸的块**照写进 json** 并标 ready=False —— 运行时线路照跑但不注入 (诚实拒绝, 不静默)。

用法: python3 tools/fit_fiber_map.py [reports/fiber_calib_s*.npz ...]
"""
from __future__ import annotations

import glob
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from lerobot.manifold.fiber_bundle import R2_GATE, fit_map            # noqa: E402


def load(paths: list[str]) -> dict:
    zt, zp, zg, ct, pf, z7, stg = [], [], [], [], [], [], []
    for p in paths:
        with np.load(p, allow_pickle=True) as d:
            f = list(d.files)
            if "z_pred" not in f:
                print(f"  跳过 {os.path.basename(p)} (无 z_pred)")
                continue
            n = d["z_t"].shape[0]
            zt.append(d["z_t"])
            zp.append(d["z_pred"])
            zg.append(d["z_goal"] if "z_goal" in f else np.zeros_like(d["z_t"]))
            ct.append(d["contact"])
            pf.append(d["perf"] if "perf" in f else np.zeros((n, 6)))
            z7.append(d["z7_geo"] if "z7_geo" in f else np.zeros((n, 7)))
            stg.extend(list(d["stage"]) if "stage" in f else [""] * n)
            print(f"  {os.path.basename(p)}: n={n}")
    if not zt:
        return {}
    return {"z_t": np.concatenate(zt), "z_pred": np.concatenate(zp),
            "z_goal": np.concatenate(zg), "contact": np.concatenate(ct),
            "perf": np.concatenate(pf), "z7": np.concatenate(z7), "stage": stg}


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    paths = args or sorted(glob.glob(os.path.join(ROOT, "reports", "fiber_calib_s*.npz")))
    print(f"🧬 纤维丛标定: 读入 {len(paths)} 个样本文件")
    data = load(paths)
    if not data:
        print("❌ 无可用样本 (先跑: SS_L4_FIBER=1 SS_L4_FIBER_DATA=reports/fiber_calib_s0.npz "
              "python3 tools/probe_l4_callchain.py L4line 600)")
        return 2
    n = data["z_pred"].shape[0]
    from collections import Counter
    print(f"   样本数 n={n} · 阶段分布={dict(Counter(data['stage']))}")

    out: dict = {"note": f"标定 n={n} (真实引擎样本) · 数据文件 {len(paths)} 个",
                 "n": int(n), "w_perf": 0.0,
                 "perf_note": "插拔任务次要: 只记录不注入 (老倪口径)"}

    def _fit(name: str, x: np.ndarray, y: np.ndarray, quad: bool, key: str) -> dict:
        m = fit_map(x, y, use_quad=quad)
        blk = m.to_json()
        out[key] = blk
        gd = np.asarray(blk.get("gate_dim") or [], float)
        print(f"   {name:16s} r2={m.r2:+.3f} r2_loso={m.r2_loso:+.3f} null={m.null_r2:+.3f} "
              f"n={m.n} ready={m.ready} 逐维R²={np.round(gd, 3).tolist()}")
        return blk

    zp = data["z_pred"].astype(np.float64)
    print("── 拟合 ──")
    c = _fit("Φ: z_pred→接触丛", zp, data["contact"], True, "l3_contact")
    g = _fit("Φ_geo: z7→接触丛", data["z7"], data["contact"], False, "geom_contact")
    a = _fit("A: z_pred→z7 (丛映射)", zp, data["z7"], False, "z7_morph")
    p = _fit("Φ_p: z_pred→性能丛", zp, data["perf"], False, "perf")

    ready = (float(c["r2_loso"]) >= R2_GATE and float(c["null_r2"]) < 0.10
             and float(a["r2_loso"]) >= R2_GATE and float(a["null_r2"]) < 0.10)
    out["ready"] = bool(ready)
    out["gate"] = {"r2_gate": R2_GATE, "null_gate": 0.10,
                   "contact_r2_loso": float(c["r2_loso"]), "morph_r2_loso": float(a["r2_loso"]),
                   "geom_contact_r2_loso": float(g["r2_loso"]),
                   "perf_r2_loso": float(p["r2_loso"])}
    out["note"] += f" · contact r²_loso={float(c['r2_loso']):.3f} / morph r²_loso={float(a['r2_loso']):.3f} → ready={ready}"
    dst = os.path.join(ROOT, "models", "intact_fiber_map.json")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"── 落盘 {os.path.relpath(dst, ROOT)} (ready={ready}) ──")
    if not ready:
        print("⚠️ 未过闸: 运行时线路照跑 (采数/计数/来源), 但**不注入**(w=0) —— 这是红线不是 bug。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
