#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""analyze_canvas_links.py — 连线质量分析: 方向(左→右?) · 交叉数 · 最差连线 TOP

口径: 用节点框的中心连线; 两条连线在 x 区间交叠且 y 端点反向 = 交叉 (与画布视觉一致)
输出: /tmp/canvas_links_analysis.txt
"""
from __future__ import annotations

import json
import os
import sys

F = "/home/ubuntu/zmax_rel/flows/state_space_obs.json"
d = json.load(open(F, encoding="utf-8"))
by = {n["id"]: n for n in d["nodes"]}
rows = sorted({int(n["y"]) for n in d["nodes"]})
lines = []


def p(*a):
    lines.append(" ".join(str(x) for x in a))


def seg(l):
    a, b = by.get(l["f"]), by.get(l["t"])
    if not a or not b:
        return None
    # 起止点: 源右缘中点 → 目标左缘中点 (画布连线锚点近似)
    return (a["x"] + a["w"], a["y"] + a["h"] // 2, b["x"], b["y"] + b["h"] // 2)


segs = [(l, seg(l)) for l in d["links"] if seg(l)]
back = [(l["id"], by[l["f"]]["name"][:16], by[l["t"]]["name"][:16], by[l["f"]]["x"], by[l["t"]]["x"])
        for l, s in segs if s[0] >= s[2]]
p("连线总数: %d · 其中**反向(右→左)** %d 条" % (len(segs), len(back)))
for x in back[:8]:
    p("    反向 %-16s %s → %s (x %d → %d)" % x)

cross_per = {}
pairs = 0
for i in range(len(segs)):
    li, s = segs[i]
    x1, y1, x2, y2 = s
    for j in range(i + 1, len(segs)):
        lj, t = segs[j]
        a1, b1, a2, b2 = t
        if x1 < a2 and a1 < x2 and (y1 - y2) * (b1 - b2) < 0:
            pairs += 1
            cross_per[li["id"]] = cross_per.get(li["id"], 0) + 1
            cross_per[lj["id"]] = cross_per.get(lj["id"], 0) + 1
p("交叉对: %d" % pairs)
top = sorted(cross_per.items(), key=lambda kv: -kv[1])[:10]
p("交叉最多的 10 条:")
for k, v in top:
    l = next(x for x, s in segs if x["id"] == k)
    a, b = by[l["f"]], by[l["t"]]
    span = abs(b["x"] - a["x"])
    p("    %-18s %3d 次  跨距 %5dpx  %s → %s" % (k, v, span, a["name"][:16], b["name"][:16]))
# 我的两条连线贡献
mine = {k: v for k, v in cross_per.items() if k.startswith("lkhil")}
p("我新增连线交叉贡献: %s" % (mine or "0 (未进 TOP)"))
p("行带 y: %s (共 %d 行)" % (rows[:14], len(rows)))
open("/tmp/canvas_links_analysis.txt", "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("\n".join(lines))
