#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""a5_final.py — A5 终局: 验曝光稳定性 → (稳定则) 12 位姿采集 → 落数据集 (供手眼解算)

流程:
 ① 曝光稳定性: 位姿A 连拍3帧 std, 位移+40mm 再连拍3帧 std → 跨位姿 std 差异 <15% 判"曝光已固定"
 ② 稳定 → 12 位姿 (±15mm 网格): 每位姿连拍3帧中值 → 与参考中值图做 CLAHE 差分 → 最大簇质心当 2D 观测
 ③ 结束回起始位姿; 落 data/handeye/final_*.json (TCP + uv + 各档指标)
安全: 每步只读三查 · ±15mm · speed=30 · 回原位
用法: ./gui-venv311/bin/python tools/a5_final.py [--amp 15] [--n 12]
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


def med3(tag):
    gs, stds = [], []
    for i in range(3):
        img, _n, _f = grab("%s_%d" % (tag, i))
        if img is None:
            continue
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gs.append(g.astype(np.float32))
        stds.append(round(float(g.std()), 1))
        time.sleep(0.7)
    if not gs:
        return None, stds
    med = np.median(np.stack(gs, 0), 0).astype(np.uint8)
    return med, stds


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--amp", type=float, default=15.0)
    ap.add_argument("--n", type=int, default=12)
    a = ap.parse_args()
    s0 = A5.state()
    print("三查: %s" % s0)
    if s0["operation"] != "idle":
        print("非 idle → 停"); return 1
    t0 = A5.tcp()
    print("起始 TCP=(%.6f, %.6f, %.6f)\n" % tuple(t0["p"]))

    # ① 曝光稳定性
    mA, sA = med3("st_A")
    A5.move_pose([t0["p"][0] + 0.04, t0["p"][1], t0["p"][2]], t0["q"], 30.0, A5.joints()); A5.wait_idle()
    mB, sB = med3("st_B")
    A5.move_pose(t0["p"], t0["q"], 30.0, A5.joints()); A5.wait_idle()
    print("① 曝光稳定性: 位姿A 各帧std=%s (中值图 %.1f) · 位姿B(+40mm) 各帧std=%s (中值图 %.1f)" %
          (sA, mA.std() if mA is not None else -1, sB, mB.std() if mB is not None else -1))
    if mA is None or mB is None:
        print("取图失败"); return 1
    d_std = abs(float(mA.std()) - float(mB.std())) / max(float(mA.std()), 1e-6) * 100
    stable = d_std < 15
    print("   跨位姿 std 差异 %.1f%% → %s" % (d_std, "✅ 曝光已稳定, 继续采集" if stable else
                                             "❌ 曝光仍在变 (需现场固定曝光/增益)"))
    if not stable:
        print("\n结论: 曝光未固定 → 采集仍不可靠; 请在工控机侧关自动曝光/固定增益后重跑本脚本")
        return 1

    # ② 12 位姿采集 (CLAHE 差分 + 最大簇)
    gref = clahe_gray(cv2.cvtColor(mA, cv2.COLOR_GRAY2BGR))
    amp = a.amp / 1000.0
    pat = [(0, 0), (amp, 0), (-amp, 0), (0, amp), (0, -amp), (amp, amp),
           (-amp, -amp), (amp, -amp), (-amp, amp), (amp / 2, 0), (-amp / 2, 0), (0, amp / 2)][:a.n]
    recs = []
    for i, (dx, dy) in enumerate(pat):
        if dx or dy:
            A5.move_pose([t0["p"][0] + dx, t0["p"][1] + dy, t0["p"][2]], t0["q"], 30.0, A5.joints())
            A5.wait_idle()
        tt = A5.tcp()
        med, stds = med3("f%02d" % i)
        if med is None:
            print("  位姿%02d 取图失败" % i); continue
        d = np.abs(clahe_gray(cv2.cvtColor(med, cv2.COLOR_GRAY2BGR)).astype(np.int16) - gref.astype(np.int16))
        bc = biggest_cluster(d, 300)
        recs.append({"i": i, "arm_mm": [round(dx * 1000, 2), round(dy * 1000, 2)],
                     "tcp_m": [round(x, 6) for x in tt["p"]],
                     "uv_px": (bc["centroid"] if bc else None), "area": (bc["area"] if bc else None),
                     "diff_pct": (bc["diff_pct"] if bc else None), "stds": stds})
        print("  位姿%02d 臂(%+5.1f,%+5.1f)mm → uv=%s area=%s (std %s)" %
              (i, dx * 1000, dy * 1000, bc["centroid"] if bc else "无", bc["area"] if bc else "-", stds))
    A5.move_pose(t0["p"], t0["q"], 30.0, A5.joints()); A5.wait_idle()
    print("\n已回起始位姿")
    ok = [r for r in recs if r["uv_px"]]
    # 相关性判据
    if len(ok) >= 6:
        ax = np.array([r["tcp_m"][0] for r in ok]); ay = np.array([r["tcp_m"][1] for r in ok])
        u = np.array([r["uv_px"][0] for r in ok]); v = np.array([r["uv_px"][1] for r in ok])
        cc = {}
        for kn, kk in (("x→u", (ax, u)), ("y→v", (ay, v)), ("y→u", (ay, u)), ("x→v", (ax, v))):
            cc[kn] = round(float(np.corrcoef(kk[0], kk[1])[0, 1]), 3) if np.std(kk[0]) > 1e-9 and np.std(kk[1]) > 1e-9 else None
        print("  相关性:", cc)
        good = any(abs(cc[k]) > 0.8 for k in ("x→u", "y→v") if cc[k] is not None)
        print("  %s" % ("✅ 观测与臂位移强相关 ⇒ 数据可用于手眼解算" if good else
                        "❌ 相关性不足 ⇒ 观测仍不可靠 (需标记物 AprilTag)"))
    dst = os.path.join(OUT, "final_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    json.dump({"ts": time.strftime("%F %T"), "tcp0": t0, "amp_mm": a.amp, "exposure_stable": stable,
               "d_std_pct": round(d_std, 1), "recs": recs}, open(dst, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("产物: %s · 有效位姿 %d/%d" % (dst, len(ok), len(recs)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
