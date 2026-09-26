#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""a5_ncc_track.py — NCC(归一化互相关)追踪: 对线性亮度变化免疫, 离线用已存中值图验证可追踪性

背景: 实测跨位姿曝光不同 (std 81.8→30.0→53.5), 强度差分/簇定位不可重复。
做法: ① 取 +40mm 中值图里"差异簇"位置的一小块当**模板** (候选=臂的像)
      ② 在 ref / +80mm 中值图里用 cv2.matchTemplate TM_CCOEFF_NORMED (NCC, 亮度不变) 搜索
      ③ 看峰值位置是否随臂位移单调成比例   ④ 记录峰值相关系数 (越高越可信)
判据: 峰值随臂单调 + 近似成比例 ⇒ **NCC 可追踪 ⇒ 可用它做 12 位姿标定采集** (不需要改相机曝光)
用法: ./gui-venv311/bin/python tools/a5_ncc_track.py
"""
from __future__ import annotations

import glob
import json
import os
import time

import numpy as np
import cv2

OUT = "/home/ubuntu/zmax_rel/data/handeye"
K = 48          # 模板半径 (96x96)


def load(tag):
    p = os.path.join(OUT, "med_%s.png" % tag)
    return cv2.imread(p, cv2.IMREAD_GRAYSCALE) if os.path.isfile(p) else None


def main() -> int:
    ref, p40, p80 = load("ref"), load("d040"), load("d080")
    have = {k: v is not None for k, v in (("ref", ref), ("+40", p40), ("+80", p80))}
    print("中值图: %s" % have)
    if not all(have.values()):
        print("缺图 → 请先跑 tools/a5_median_track.py --amp 40 --nframes 3")
        return 1
    # ① 用 CLAHE 归一后的差异找候选位置 (在 +40 上)
    def cl(g):
        return cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(g)
    d = np.abs(cl(ref).astype(np.int16) - cl(p40).astype(np.int16))
    thr = max(25, int(np.percentile(d, 99.5)))
    m = (d >= thr).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, lab, st, cent = cv2.connectedComponentsWithStats(m, 8)
    if n <= 1:
        print("差异簇为空 → 无法选模板"); return 1
    i = 1 + int(np.argmax(st[1:, 4]))
    cx, cy = int(cent[i][0]), int(cent[i][1])
    print("候选模板中心 (来自 +40mm 差异簇): (%d, %d), 面积 %d" % (cx, cy, st[i][4]))

    h, w = p40.shape
    x0, y0 = max(0, cx - K), max(0, cy - K)
    tpl = p40[y0:y0 + 2 * K, x0:x0 + 2 * K]
    if tpl.size == 0:
        print("模板越界"); return 1
    print("模板尺寸: %dx%d" % (tpl.shape[1], tpl.shape[0]))

    res = {}
    for tag, img in (("ref", ref), ("+40", p40), ("+80", p80)):
        r = cv2.matchTemplate(img, tpl, cv2.TM_CCOEFF_NORMED)
        _, mx, _, loc = cv2.minMaxLoc(r)
        res[tag] = {"peak": [loc[0] + K, loc[1] + K], "score": round(float(mx), 4)}
        print("  %-4s → 匹配峰值 (%4d, %4d) · NCC=%.4f" % (tag, loc[0] + K, loc[1] + K, mx))
    du1 = res["+40"]["peak"][0] - res["ref"]["peak"][0]
    du2 = res["+80"]["peak"][0] - res["ref"]["peak"][0]
    dv1 = res["+40"]["peak"][1] - res["ref"]["peak"][1]
    dv2 = res["+80"]["peak"][1] - res["ref"]["peak"][1]
    r_u = abs(du2 / du1) if abs(du1) > 1e-6 else float("inf")
    print("\n═══ 判定 ═══")
    print("  Δu: +40mm→%+d px · +80mm→%+d px · 比值 %.2f (期望≈2)" % (du1, du2, r_u))
    print("  Δv: +40mm→%+d px · +80mm→%+d px" % (dv1, dv2))
    print("  NCC: ref=%.4f +40=%.4f +80=%.4f (≥0.7 视为同一特征)" %
          (res["ref"]["score"], res["+40"]["score"], res["+80"]["score"]))
    ok = (1.2 <= r_u <= 3.4) and (du1 * du2 > 0) and min(v["score"] for v in res.values()) >= 0.5
    print("  %s" % ("✅ NCC 可追踪 (亮度不变) ⇒ **可直接用它做 12 位姿标定采集**, 不必改相机曝光" if ok
                    else "❌ NCC 也不行 ⇒ **必须固定相机曝光/增益** (工控机侧, 技能记载的根治手段)"))
    json.dump({"ts": time.strftime("%F %T"), "tpl_center": [cx, cy], "res": res,
               "du": [du1, du2], "dv": [dv1, dv2], "ratio": r_u, "ok": ok},
              open(os.path.join(OUT, "ncc_track_%s.json" % time.strftime("%Y%m%d_%H%M%S")), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
