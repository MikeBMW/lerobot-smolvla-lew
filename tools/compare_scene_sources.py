#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三源框对照: L5 大模型(蓝) / L2 YOLO(红) / 仿真投影(绿) —— 谁跟谁对得上。"""
import json
import sys
from pathlib import Path

REPO = Path("/home/ubuntu/zmax_rel")
sys.path.insert(0, str(REPO / "tools"))
import numpy as np                                                                   # noqa: E402
import scene_overlay as SO                                                           # noqa: E402

spec = SO.load_spec()
cam = "arm"
boxes = (spec.get("cameras", {}).get(cam, {}).get("boxes") or [])
K = SO.load_intrinsics(640, 480)
tcp = SO.read_tcp()
X = SO.load_handeye()["X"]
H, W = 480, 640


def rect(b):
    if b.get("xyxy"):
        x1, y1, x2, y2 = [float(v) for v in b["xyxy"]]
    else:
        bb = SO.box3d_to_xyxy(b["box3d"]["center"], b["box3d"]["size"], K, X, tcp, None)
        if bb is None:
            return None
        x1, y1, x2, y2 = [float(v) for v in bb]
    # 允许部分出画: 裁到画面内再算几何
    return [x1, y1, x2, y2]


def iou(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1, ix2, iy2 = max(ax1, bx1), max(ay1, by1), min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    ua = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / ua if ua > 0 else 0.0


def ctr(r):
    return ((r[0] + r[2]) / 2, (r[1] + r[3]) / 2)


sims = [(b, rect(b)) for b in boxes if b.get("origin") == "sim"]
vlm = [(b, rect(b)) for b in boxes if b.get("origin") == "vlm"]
det = [(b, rect(b)) for b in boxes if b.get("origin") == "det"]

print("══ 规格里三源框 (arm, %dx%d) ══" % (W, H))
for tag, arr in (("sim", sims), ("det", det), ("vlm", vlm)):
    print("  [%s] %d 框" % (tag, len(arr)))
    for b, r in arr:
        if r is None:
            print("     %-22s 框退化(视锥外/背后)" % b.get("label"))
            continue
        c = ctr(r)
        inside = (0 <= c[0] < W) and (0 <= c[1] < H)
        print("     %-22s xyxy=[%4.0f,%4.0f,%4.0f,%4.0f] 框心=(%4.0f,%4.0f)%s conf=%s" % (
            b.get("label"), r[0], r[1], r[2], r[3], c[0], c[1], "" if inside else " (框心在画外)", b.get("conf")))

print("══ 交叉核对: 同类物体三源是否落在同一处 ══")
pairs = []
for bv, rv in vlm:
    for bs, rs in sims:
        if rs is None:
            continue
        d = float(np.hypot(ctr(rv)[0] - ctr(rs)[0], ctr(rv)[1] - ctr(rs)[1]))
        pairs.append((d, iou(rv, rs), bv.get("label"), bs.get("label"), ctr(rv), ctr(rs)))
pairs.sort(key=lambda x: x[0])
for d, i, lv, ls, cv, cs in pairs[:6]:
    print("  最近配对: 大模型[%s](%3.0f,%3.0f) ↔ 仿真[%s](%3.0f,%3.0f) · 框心差 %.0fpx · IoU %.2f" % (
        lv, cv[0], cv[1], ls, cs[0], cs[1], d, i))
if det and sims:
    bd, rd = det[0]
    best = min(((float(np.hypot(ctr(rd)[0] - ctr(rs)[0], ctr(rd)[1] - ctr(rs)[1])), bs, rs)
                for bs, rs in sims if rs is not None), key=lambda x: x[0])
    print("  YOLO[%s](%3.0f,%3.0f) ↔ 最近仿真[%s](%3.0f,%3.0f) · 框心差 %.0fpx" % (
        bd.get("label"), *ctr(rd), best[1].get("label"), *ctr(best[2]), best[0]))
