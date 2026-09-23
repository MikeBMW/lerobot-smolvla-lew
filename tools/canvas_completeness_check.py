#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""画布完备性终检 (2026-09-24): 行带/端点/孤岛/断头/悬空/越层/重叠/坐标类型 全断言。
判据: 孤岛 0; 断头 ⊆ 合法终端; 悬空 ⊆ 合法数据源; 无节点落在行带外; L2 功能不在 L4 带; 坐标全 int。
"""
import json
import sys
from collections import defaultdict

FLOW = "/home/ubuntu/lerobot-smolvla-lew/flows/state_space_obs.json"
TERMINALS = {"ssbypv", "ssff_hist", "ssvideo", "ss3d_view", "ssvideo2", "sstest", "ssfeat"}
SOURCES = {"ssdata", "ssz700", "n_eng_mem"}

d = json.load(open(FLOW, encoding="utf-8"))
ns = [n for n in d["nodes"] if n.get("type") != "row_bg"]
bands = [n for n in d["nodes"] if n.get("type") == "row_bg"]
ids = {n["id"] for n in ns}
ind, outd = defaultdict(int), defaultdict(int)
for L in d["links"]:
    outd[L["f"]] += 1
    ind[L["t"]] += 1


def band_of(n):
    cy = n["y"] + n["h"] / 2
    for b in bands:
        if b["y"] <= cy <= b["y"] + b["h"]:
            return b
    return None


bad_ep = [(L["f"], L["t"]) for L in d["links"] if L["f"] not in ids or L["t"] not in ids]
assert not bad_ep, f"断头连线 {bad_ep}"
nonint = [n["id"] for n in d["nodes"] for k in ("x", "y", "w", "h")
          if k in n and not isinstance(n[k], int)]
assert not nonint, f"非 int 坐标 {nonint}"
iso = [i for i in ids if ind[i] == 0 and outd[i] == 0]
dead = sorted(i for i in ids if outd[i] == 0)
susp = sorted(i for i in ids if ind[i] == 0)
assert not iso, f"孤岛 {iso}"
assert set(dead) <= TERMINALS, f"非法断头 {sorted(set(dead) - TERMINALS)}"
assert set(susp) <= SOURCES, f"非法悬空 {sorted(set(susp) - SOURCES)}"
outside = [n["id"] for n in ns if band_of(n) is None]
assert not outside, f"行带外节点 {outside}"
l4 = [b for b in bands if "L4" in str(b.get("name", ""))]
bad_layer = [n["id"] for n in ns if band_of(n) in l4
             and any(t in str(n.get("name", "")) for t in ("💪", "🔧 L2", "SK0"))]
assert not bad_layer, f"L2 功能越层到 L4: {bad_layer}"
ov = 0
for i in range(len(ns)):
    for j in range(i + 1, len(ns)):
        A, B = ns[i], ns[j]
        if (A["x"] < B["x"] + B["w"] and B["x"] < A["x"] + A["w"]
                and A["y"] < B["y"] + B["h"] and B["y"] < A["y"] + A["h"]):
            ov += 1
xs = [n["x"] for n in d["nodes"]]
xe = [n["x"] + n["w"] for n in d["nodes"]]
ys = [n["y"] for n in d["nodes"]]
ye = [n["y"] + n["h"] for n in d["nodes"]]
print(f"节点 {len(ids)} · 连线 {len(d['links'])} · 行带 {len(bands)} · 重叠 {ov} · "
      f"画布 {max(xe) - min(xs)}×{max(ye) - min(ys)}")
print(f"孤岛 0 · 断头 {len(dead)} 全为合法终端 {dead} · 悬空 {len(susp)} 全为数据源 {susp}")
assert ov == 0, f"方框重叠 {ov}"
print("✅ 完备性终检通过")
