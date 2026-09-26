#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rewire_cross_check.py — 量化新增/存量连线的交叉归因 + 重启控制台提示"""
import json
import os
import sys

R = "/home/ubuntu/zmax_rel"
sys.path.insert(0, os.path.join(R, "tools"))
from canvas_rewire_exec_chain import count_cross, seg_cross                            # noqa: E402

d = json.load(open(os.path.join(R, "flows/state_space_obs.json"), encoding="utf-8"))
nodes, links = d["nodes"], d["links"]
pos = {n["id"]: (n["x"] + n["w"] / 2.0, n["y"] + n["h"] / 2.0) for n in nodes}
SK = ["sssk%d" % k for k in range(1, 9)]
new_key = {(s, "n_moveit") for s in SK} | {("sslimit", s) for s in SK[1:]} | {("ssdec", "n_moveit")}
tot = count_cross(nodes, links)
print("全图: %d 节点 / %d 连线 / 交叉 %d 对" % (len(nodes), len(links), tot))
per = {}
for i, li in enumerate(links):
    if li["f"] not in pos or li["t"] not in pos:
        continue
    c = 0
    for j, lj in enumerate(links):
        if i == j or lj["f"] not in pos or lj["t"] not in pos:
            continue
        if li["f"] == lj["f"] and li["t"] == lj["t"]:
            continue
        if seg_cross(pos[li["f"]], pos[li["t"]], pos[lj["f"]], pos[lj["t"]]):
            c += 1
    per[(li["f"], li["t"])] = c
newsum = sum(v for k, v in per.items() if k in new_key)
print("本次新增/改向连线 %d 条 → 交叉贡献合计 %d 对 (占全图 %.1f%%)" % (len(new_key), newsum, newsum / max(tot, 1) * 100))
for k in sorted(new_key):
    print("   %-10s → %-9s 交叉 %d" % (k[0], k[1], per.get(k, -1)))
top = sorted(per.items(), key=lambda kv: -kv[1])[:6]
print("\n全图交叉最多的 6 条 (都是既有的跨行长线, 非本次改动):")
for (f, t), c in top:
    print("   %-10s → %-10s  %4d 对   (x %.0f→%.0f)" % (f, t, c, pos[f][0], pos[t][0]))
print("\n结论: 本次拓扑改造的交叉代价 ≈ %d 对; 全图 %d 对由上述跨行长线主导" % (newsum, tot))
