#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🎯 L4 对齐映射标定 — 用实测成对样本 (u_l2 下层参考, u_int 上层提案) 拟合 R/b。

产出: models/l4_align_map.json  (运行时由 IntentAligner 加载; SS_L4_ALIGN=1 才施加)
闸值: 对齐后 LOO cos 中位数 ≥ 0.90 且相对基线提升 ≥ 0.20 → ready; 否则运行时不施加 (诚实拒绝)。

用法: python3 tools/fit_l4_align.py [reports/l4_align_s*.npz ...]
"""
from __future__ import annotations

import glob
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from lerobot.manifold.l4_align import COS_GAIN, COS_READY, fit_align   # noqa: E402


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    paths = args or [p for p in sorted(glob.glob(os.path.join(ROOT, "reports", "l4_align_s*.npz")))
                     if os.path.getsize(p) > 0]
    if not paths:
        print("❌ 无样本。先跑:\n  SS_L4_FIBER=1 SS_L4_ALIGN_DATA=reports/l4_align_s0.npz "
              "python3 tools/probe_l4_callchain.py L4audit 200")
        return 2
    ups, l2s, stg = [], [], []
    for p in paths:
        with np.load(p, allow_pickle=True) as d:
            f = list(d.files)
            if "u_up" not in f:
                print(f"  跳过 {os.path.basename(p)} (无 u_up)")
                continue
            ups.append(d["u_up"])
            l2s.append(d["u_l2"])
            stg.extend(list(d["stage"]) if "stage" in f else [""] * d["u_up"].shape[0])
            print(f"  {os.path.basename(p)}: n={d['u_up'].shape[0]}")
    if not ups:
        return 2
    x = np.concatenate(ups)
    y = np.concatenate(l2s)
    from collections import Counter
    print(f"   合计 n={x.shape[0]} · 阶段分布={dict(Counter(stg))}")
    m = fit_align(x, y, stages=stg)
    per_stage = m.per_stage or {}
    print(f"── 对齐标定 ──  cos: 基线 {m.cos_base:+.3f} → LOO {m.cos_loso:+.3f} "
          f"(闸 ≥{COS_READY}, 提升 ≥{COS_GAIN})  ready={m.ready}")
    for k, v in per_stage.items():
        print(f"   阶段 {k:6s} n={v['n']:4d} cos {v['cos_base']:+.3f} → {v['cos_loso']:+.3f}")
    out = {"r": m.r.tolist(), "b": m.b.tolist(), "cos_loso": m.cos_loso, "cos_base": m.cos_base,
           "n": int(m.n), "per_stage": per_stage,
           "gate": {"cos_ready": COS_READY, "cos_gain": COS_GAIN},
           "ready": bool(m.ready),
           "note": (f"标定 n={m.n} · cos 基线 {m.cos_base:.3f} → LOO {m.cos_loso:.3f} · "
                    f"ready={m.ready} (闸 cos≥{COS_READY} 且提升≥{COS_GAIN})")}
    dst = os.path.join(ROOT, "models", "l4_align_map.json")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"── 落盘 {os.path.relpath(dst, ROOT)} (ready={m.ready}) ──")
    if not m.ready:
        print("⚠️ 未过闸 → 运行时不施加对齐 (原样透传, 不硬掰方向)。这是红线不是 bug。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
