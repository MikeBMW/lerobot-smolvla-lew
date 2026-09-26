#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""a5_coherence.py — 位移一致性判定: 差异簇质心是否随臂单调/成比例移动 (证明可追踪)

方法: 位姿 0 (参考) → +40mm → +80mm (x 轴), 每档真拍新帧(校验文件名变化) + CLAHE 归一 + 与参考做差,
      取**最大差异簇**质心当 2D 观测 → 看 u 位移是否随臂位移单调且近似成比例。
判据: |Δu(80mm)| ≈ 2×|Δu(40mm)| (±40%) 且方向一致 ⇒ 该特征是臂且可追踪 ⇒ 可以做 12 位姿标定采集
用法: ./gui-venv311/bin/python tools/a5_coherence.py [--amp 40]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np
import cv2

R = "/home/ubuntu/zmax_rel"
sys.path.insert(0, os.path.join(R, "tools"))
import a5_handeye_collect as A5                                                   # noqa: E402
from a5_probe_v2 import grab, clahe_gray                                          # noqa: E402

OUT = os.path.join(R, "data/handeye")


def biggest_cluster(d, min_area=600):
    thr = max(25, int(np.percentile(d, 99.5)))
    m = (d >= thr).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    m = cv2.dilate(m, np.ones((9, 9), np.uint8), iterations=2)
    n, lab, st, cent = cv2.connectedComponentsWithStats(m, 8)
    best = None
    for i in range(1, n):
        if st[i][4] >= min_area and (best is None or st[i][4] > best["area"]):
            best = {"area": int(st[i][4]), "bbox": [int(v) for v in st[i][:4]],
                    "centroid": [round(float(cent[i][0]), 1), round(float(cent[i][1]), 1)],
                    "thr": thr, "diff_pct": round(float(m.mean() * 100), 2)}
    return best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--amp", type=float, default=40.0)
    a = ap.parse_args()
    s0 = A5.state()
    print("三查: %s" % s0)
    if s0["operation"] != "idle":
        print("非 idle → 停"); return 1
    t0 = A5.tcp()
    print("参考位姿 TCP=(%.6f, %.6f, %.6f)\n" % tuple(t0["p"]))
    ref, ref_name, ref_fresh = grab("coh_ref")
    gref = clahe_gray(ref)
    rows = []
    for k, dx in enumerate((0.0, a.amp, 2 * a.amp)):
        if dx:
            A5.move_pose([t0["p"][0] + dx / 1000.0, t0["p"][1], t0["p"][2]], t0["q"], 30.0, A5.joints())
            A5.wait_idle()
        tt = A5.tcp()
        d_real = [round((tt["p"][i] - t0["p"][i]) * 1000, 3) for i in range(3)]
        if k == 0:
            img, name, fresh = ref, ref_name, ref_fresh
        else:
            img, name, fresh = grab("coh_%d" % k)
        if img is None:
            print("  档%d: 取图失败" % k); continue
        d = np.abs(clahe_gray(img).astype(np.int16) - gref.astype(np.int16))
        bc = biggest_cluster(d)
        rows.append({"dx_mm": dx, "tcp_mm": d_real, "fresh": fresh, "cluster": bc,
                     "raw_std": round(float(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).std()), 1)})
        print("  档%d  臂Δ=(%.1f,%.1f,%.1f)mm  新帧=%s  raw_std=%.1f  最大簇: %s" %
              (k, d_real[0], d_real[1], d_real[2], "✅" if fresh else "❌",
               rows[-1]["raw_std"], (bc["centroid"] if bc else "无")))
    A5.move_pose(t0["p"], t0["q"], 30.0, A5.joints()); A5.wait_idle()
    print("\n已回参考位姿\n═══ 判定 ═══")
    cs = [r for r in rows if r.get("cluster")]
    if len(cs) < 3:
        print("  存在取不到簇的档位 → 无法判定 (见上表)"); return 1
    u0 = cs[0]["cluster"]["centroid"][0]
    du1 = cs[1]["cluster"]["centroid"][0] - u0
    du2 = cs[2]["cluster"]["centroid"][0] - u0
    ratio = abs(du2 / du1) if abs(du1) > 1e-6 else float("inf")
    print("  Δu(%.0fmm)=%.0fpx · Δu(%.0fmm)=%.0fpx · 比值=%.2f (期望≈2.0)" % (a.amp, du1, 2 * a.amp, du2, ratio))
    ok = (abs(du1) > 3) and (1.2 <= ratio <= 3.4) and (du1 * du2 > 0)
    print("  判据: %s" % ("✅ 单调且近似成比例 ⇒ 该簇=臂的像, **可追踪, 可做 12 位姿标定采集**" if ok
                          else "❌ 不成比例/方向不一致 ⇒ 该簇不是稳定的臂特征 (改用模板匹配或标记物)"))
    json.dump({"ts": time.strftime("%F %T"), "tcp0": t0, "rows": rows, "du1": du1, "du2": du2,
               "ratio": ratio, "ok": ok},
              open(os.path.join(OUT, "coherence_%s.json" % time.strftime("%Y%m%d_%H%M%S")), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
