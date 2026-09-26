#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""canvas_relayout.py — 连线交叉优化 (分层 barycenter 重排, 老倪: 连线不要交叉, 方向左上→右下)

思路 (标准分层图交叉最小化, 保持层/行不变):
  ① 按 y 行带分组 (行=层, 不动 y)
  ② 迭代 (默认 4 轮): 每行的节点按"相邻行邻居位置的重心"排序
  ③ 硬约束: 任何连线的 f.x 必须 < t.x (不得把连线变成右→左); 违反则不交换
  ④ 行内重排 x: 保持各节点宽度与最小间距, 锚定该行最小 x 不变
  ⑤ 量化: 交叉对数 前 → 后; 不达 20% 改善或出现重叠 → 自动回滚
安全: 写前备份; 运行 --dry-run 只报数不写盘
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import time

ROOT = "/home/ubuntu/zmax_rel"
FLOW = os.path.join(ROOT, "flows", "state_space_obs.json")
MIN_GAP = 32


def seg_xy(n):
    return n["x"] + n["w"], n["y"] + n["h"] // 2


def count_cross(nodes, links):
    by = {n["id"]: n for n in nodes}
    segs = []
    for l in links:
        a, b = by.get(l["f"]), by.get(l["t"])
        if a and b:
            segs.append((a["x"] + a["w"], a["y"] + a["h"] // 2, b["x"], b["y"] + b["h"] // 2))
    c = 0
    for i in range(len(segs)):
        x1, y1, x2, y2 = segs[i]
        for j in range(i + 1, len(segs)):
            a1, b1, a2, b2 = segs[j]
            if x1 < a2 and a1 < x2 and (y1 - y2) * (b1 - b2) < 0:
                c += 1
    return c


def overlaps(nodes):
    real = [n for n in nodes if not ((n.get("params") or {}).get("bg") or (n.get("params") or {}).get("row_bg"))]
    bad = 0
    for i in range(len(real)):
        for j in range(i + 1, len(real)):
            a, b = real[i], real[j]
            if a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"] and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"]:
                bad += 1
    return bad


def adjacency(nodes, links):
    """节点 → 邻居 (无向, 用于重心)"""
    adj = {n["id"]: set() for n in nodes}
    for l in links:
        if l["f"] in adj and l["t"] in adj:
            adj[l["f"]].add(l["t"])
            adj[l["t"]].add(l["f"])
    return adj


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweeps", type=int, default=4)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    d = json.load(open(FLOW, encoding="utf-8"))
    nodes, links = d["nodes"], d["links"]
    by = {n["id"]: n for n in nodes}
    real = [n for n in nodes if not ((n.get("params") or {}).get("bg") or (n.get("params") or {}).get("row_bg"))]
    rows = {}
    for n in real:
        rows.setdefault(n["y"], []).append(n)
    before = count_cross(nodes, links)
    ov_before = overlaps(nodes)
    print("重排前: 交叉对 %d · 重叠 %d · 行数 %d (%d 个真节点)" % (before, ov_before, len(rows), len(real)))

    adj = adjacency(nodes, links)
    pos = {n["id"]: n["x"] for n in nodes}                       # 当前 x (重心输入)

    for sw in range(a.sweeps):
        order = sorted(rows)                                     # 逐行 (自上而下)
        seq = order if sw % 2 == 0 else list(reversed(order))    # 交替方向 (标准做法)
        for y in seq:
            group = rows[y]
            # 重心 = 邻居当前 x 均值 (无邻居者保持原相对序)
            def bary(n):
                nb = [pos[m] for m in adj.get(n["id"], ()) if m in by]
                return (sum(nb) / len(nb)) if nb else float(pos[n["id"]])
            new = sorted(group, key=lambda n: (bary(n), n["x"]))
            # 硬约束: 交换后不得出现 f.x >= t.x 的连线 (前向性)
            ok = True
            for i, n in enumerate(new):
                pos[n["id"]] = group[i]["x"]                      # 先放回原 x 槽位
            for i, n in enumerate(new):
                node_x = group[i]["x"]
                for l in links:
                    if l["f"] == n["id"] and pos.get(l["t"], 0) and node_x >= pos[l["t"]]:
                        ok = False
                    if l["t"] == n["id"] and pos.get(l["f"], 0) and pos[l["f"]] >= node_x:
                        ok = False
            if ok:
                for i, n in enumerate(new):
                    pos[n["id"]] = group[i]["x"]
                    rows[y][i] = n

    # 写回 x (行内按序排位, 保持宽度与最小间距, 锚定行最小 x)
    new_nodes = []
    row_of = {}
    for y, group in rows.items():
        group.sort(key=lambda n: pos[n["id"]])
        base = min(g["x"] for g in group)
        x = base
        for n in group:
            row_of[n["id"]] = x
            x += n["w"] + MIN_GAP
    for n in nodes:
        if n["id"] in row_of:
            n["x"] = int(row_of[n["id"]])
    after = count_cross(nodes, links)
    ov_after = overlaps(nodes)
    print("重排后: 交叉对 %d · 重叠 %d" % (after, ov_after))
    imp = (before - after) / max(before, 1) * 100
    print("改善: %.1f%%  (门槛 20%%)" % imp)
    ok = (imp >= 20) and (ov_after == 0)
    print("判据: %s" % ("✅ 采纳" if ok else "❌ 不达标 → 建议回滚"))
    if a.dry_run or not ok:
        print("(未写盘)")
        return 0 if ok else 4
    bak = FLOW + ".bak_layout_%d" % int(time.time())
    shutil.copy2(FLOW, bak)
    json.dump(d, open(FLOW, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("已写盘 · 备份 %s" % os.path.basename(bak))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
