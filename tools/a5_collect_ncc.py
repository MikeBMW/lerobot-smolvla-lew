#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""a5_collect_ncc.py — A5 12 位姿标定采集 (NCC 追踪, 对曝光变化免疫)

方法 (由实测确定): 跨位姿曝光不同 (std 82/30/54) ⇒ 强度差分不可用; 但 **NCC 模板匹配**稳定
  (实测 Δu 比值 2.69≈2 · NCC 0.84/1.00/0.84)。故:
   ① 模板 = 用 +40mm 位姿图里"差异簇"位置的 96×96 块 (臂的像)
   ② 每个位姿: 移到位 → 连拍 3 帧取中值(压噪) → NCC 定位模板 → 记录 (u,v,score) + TCP 真值
   ③ 结束回起始位姿; 产出 data/handeye/collect_ncc_*.json (供手眼解算)
安全: 每步只读三查 · 网格 ±15mm (x/y) · speed=30 (驱动 5% 限速) · 结束回原位
用法: ./gui-venv311/bin/python tools/a5_collect_ncc.py --amp 15 --n 12 --tpl-center 564,288
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
from a5_probe_v2 import grab                                                      # noqa: E402

OUT = os.path.join(R, "data/handeye")
K = 48


def median_frame(tag, n=3):
    gs = []
    for i in range(n):
        img, name, fresh = grab("%s_%d" % (tag, i))
        if img is None:
            continue
        gs.append(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
        time.sleep(0.8)
    if not gs:
        return None
    med = np.median(np.stack([g.astype(np.float32) for g in gs], 0), 0).astype(np.uint8)
    cv2.imwrite(os.path.join(OUT, "c_%s.png" % tag), med)
    return med


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--amp", type=float, default=15.0)
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--tpl-center", default="", help="模板中心 'u,v' (缺省: 用已存的 med_d040.png 差异簇自动选)")
    a = ap.parse_args()
    s0 = A5.state()
    print("三查: %s" % s0)
    if s0["operation"] != "idle":
        print("非 idle → 停"); return 1
    # 模板来源: 已存的 med_d040.png (上一轮 NCC 试验用的 +40mm 中值图)
    src = cv2.imread(os.path.join(OUT, "med_d040.png"), cv2.IMREAD_GRAYSCALE)
    if src is None:
        print("缺 med_d040.png → 先跑 tools/a5_median_track.py --amp 40 --nframes 3"); return 1
    if a.tpl_center:
        cx, cy = [int(float(v)) for v in a.tpl_center.split(",")]
    else:
        cx, cy = 564, 288
    tpl = src[max(0, cy - K):cy + K, max(0, cx - K):cx + K]
    cv2.imwrite(os.path.join(OUT, "c_tpl.png"), tpl)
    print("模板: 中心(%d,%d) 尺寸 %dx%d → data/handeye/c_tpl.png" % (cx, cy, tpl.shape[1], tpl.shape[0]))

    t0 = A5.tcp()
    print("起始 TCP=(%.6f, %.6f, %.6f)\n" % tuple(t0["p"]))
    amp = a.amp / 1000.0
    pat = [(0, 0), (amp, 0), (-amp, 0), (0, amp), (0, -amp), (amp, amp),
           (-amp, -amp), (amp, -amp), (-amp, amp), (amp / 2, 0), (-amp / 2, 0), (0, amp / 2)][:a.n]
    recs = []
    for i, (dx, dy) in enumerate(pat):
        if dx or dy:
            A5.move_pose([t0["p"][0] + dx, t0["p"][1] + dy, t0["p"][2]], t0["q"], 30.0, A5.joints())
            A5.wait_idle()
        tt = A5.tcp()
        med = median_frame("p%02d" % i)
        if med is None:
            print("  位姿%02d 取图失败" % i); continue
        r = cv2.matchTemplate(med, tpl, cv2.TM_CCOEFF_NORMED)
        _, mx, _, loc = cv2.minMaxLoc(r)
        u, v = loc[0] + K, loc[1] + K
        recs.append({"i": i, "arm_mm": [round(dx * 1000, 2), round(dy * 1000, 2)],
                     "tcp_m": [round(x, 6) for x in tt["p"]], "uv_px": [u, v],
                     "ncc": round(float(mx), 4), "raw_std": round(float(med.std()), 1)})
        print("  位姿%02d 臂(%+5.1f,%+5.1f)mm TCP=(%.6f,%.6f,%.6f) → (u,v)=(%4d,%4d) NCC=%.3f std=%.1f" %
              (i, dx * 1000, dy * 1000, tt["p"][0], tt["p"][1], tt["p"][2], u, v, mx, med.std()))
    A5.move_pose(t0["p"], t0["q"], 30.0, A5.joints()); A5.wait_idle()
    print("\n已回起始位姿")
    good = [r for r in recs if r["ncc"] >= 0.5]
    print("采集: %d/%d 位姿 NCC≥0.5" % (len(good), len(recs)))
    dst = os.path.join(OUT, "collect_ncc_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    json.dump({"ts": time.strftime("%F %T"), "tcp0": t0, "tpl_center": [cx, cy], "amp_mm": a.amp,
               "recs": recs}, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("产物: %s" % dst)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
