#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""a5_median_track.py — 每位姿多帧取中值压曝光抖动 + 结构追踪 (不改现场的补救尝试)

背景: 实测每帧曝光不同 (raw std 82/30/50 · 饱和 19%/0%/0%) → 单帧强度特征不可重复。
做法: 每位姿**连拍 N=3 帧 → 逐像素中值** (曝光抖动为随机 → 中值显著稳定) → CLAHE → 与参考位姿中值图做差
      → 取最大差异簇质心当 2D 观测; 3 档位移 (+0/+40/+80mm) 看是否单调成比例。
判据: |Δu(80)| ≈ 2|Δu(40)| (±40%) 且方向一致 ⇒ 可追踪; 否则 ⇒ 必须固定相机曝光 (现场动作)。
用法: ./gui-venv311/bin/python tools/a5_median_track.py --amp 40 --nframes 3
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
from a5_coherence import biggest_cluster                                          # noqa: E402

OUT = os.path.join(R, "data/handeye")


def median_gray(tag, n):
    """连拍 n 帧 → 逐像素中值 (压曝光抖动) → 灰度图 + 原始标准差统计"""
    gs, stds = [], []
    for i in range(n):
        img, name, fresh = grab("%s_%d" % (tag, i))
        if img is None:
            continue
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gs.append(g.astype(np.float32))
        stds.append(round(float(g.std()), 1))
        time.sleep(1.0)
    if not gs:
        return None, []
    med = np.median(np.stack(gs, 0), 0).astype(np.uint8)
    cv2.imwrite(os.path.join(OUT, "med_%s.png" % tag), med)
    return med, stds


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--amp", type=float, default=40.0)
    ap.add_argument("--nframes", type=int, default=3)
    a = ap.parse_args()
    s0 = A5.state()
    print("三查: %s" % s0)
    if s0["operation"] != "idle":
        print("非 idle → 停"); return 1
    t0 = A5.tcp()
    print("参考 TCP=(%.6f, %.6f, %.6f) · 每位姿连拍 %d 帧取中值\n" % (*t0["p"], a.nframes))
    ref_med, ref_stds = median_gray("ref", a.nframes)
    if ref_med is None:
        print("参考取图失败"); return 1
    print("参考: 各帧 std=%s → 中值图 std=%.1f" % (ref_stds, ref_med.std()))
    gref = clahe_gray(cv2.cvtColor(ref_med, cv2.COLOR_GRAY2BGR))
    rows = [{"dx": 0.0, "u": None, "v": None}]
    for dx in (a.amp, 2 * a.amp):
        A5.move_pose([t0["p"][0] + dx / 1000.0, t0["p"][1], t0["p"][2]], t0["q"], 30.0, A5.joints())
        A5.wait_idle()
        tt = A5.tcp()
        real = [round((tt["p"][i] - t0["p"][i]) * 1000, 3) for i in range(3)]
        med, stds = median_gray("d%03d" % int(dx), a.nframes)
        if med is None:
            print("  +%.0fmm: 取图失败" % dx); continue
        g = clahe_gray(cv2.cvtColor(med, cv2.COLOR_GRAY2BGR))
        d = np.abs(g.astype(np.int16) - gref.astype(np.int16))
        bc = biggest_cluster(d, 400)
        rows.append({"dx": dx, "tcp_mm": real, "u": bc["centroid"][0] if bc else None,
                     "v": bc["centroid"][1] if bc else None, "area": bc["area"] if bc else None,
                     "diff_pct": bc["diff_pct"] if bc else None, "stds": stds})
        print("  +%.0fmm 臂Δ=(%.1f,%.1f,%.1f)mm 各帧std=%s 中值图std=%.1f 最大簇=%s 变化%.2f%%" %
              (dx, real[0], real[1], real[2], stds, med.std(),
               (bc["centroid"] if bc else "无"), (bc["diff_pct"] if bc else 0)))
    A5.move_pose(t0["p"], t0["q"], 30.0, A5.joints()); A5.wait_idle()
    us = [r["u"] for r in rows]
    print("\n═══ 判定 ═══")
    if None in us:
        print("  有档位取不到簇 → 仍不可判定"); ok = False; ratio = None
    else:
        du1, du2 = us[1] - us[0], us[2] - us[0]
        ratio = abs(du2 / du1) if abs(du1) > 1e-6 else float("inf")
        ok = abs(du1) > 3 and 1.2 <= ratio <= 3.4 and du1 * du2 > 0
        print("  Δu(%.0f)=%.0fpx · Δu(%.0f)=%.0fpx · 比值=%.2f (期望≈2)" % (a.amp, du1, 2 * a.amp, du2, ratio))
        print("  %s" % ("✅ 可追踪 (中值压噪有效) ⇒ 继续 12 位姿采集" if ok
                        else "❌ 仍不可追踪 ⇒ **必须固定相机曝光/增益** (现场动作, 技能已记载为根治手段)"))
    json.dump({"ts": time.strftime("%F %T"), "nframes": a.nframes, "tcp0": t0, "rows": rows,
               "ratio": ratio, "ok": ok}, open(os.path.join(OUT, "median_track_%s.json" % time.strftime("%Y%m%d_%H%M%S")),
                                               "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
