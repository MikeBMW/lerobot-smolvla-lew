#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""moveit_layout_fix.py — 把 MoveIt 挪到原子技能阶梯末端(右下) → 扇入变嵌套式, 消除本次新增交叉

原理: 阶梯 sssk1..8 沿"右下"排列 (x+320, y+124/级)。当汇聚点也在其右下方时,
      8 条入线两两不交叉(单调嵌套); 原先把 MoveIt 放在**右上方** → 必然交叉。
做法: 试验移动 → 量交叉 → 只有改善才落盘(否则还原)。含零重叠断言与渲染复核。
"""
import json
import os
import shutil
import sys
import time

R = "/home/ubuntu/zmax_rel"
sys.path.insert(0, os.path.join(R, "tools"))
from canvas_rewire_exec_chain import count_cross                               # noqa: E402

FLOW = os.path.join(R, "flows/state_space_obs.json")
d = json.load(open(FLOW, encoding="utf-8"))
nodes, links = d["nodes"], d["links"]
by = {n["id"]: n for n in nodes}
mv = by["n_moveit"]
pos_old = (mv["x"], mv["y"])
c_before = count_cross(nodes, links)

# 候选: 阶梯末端右下 (sssk8 是 12459,5762 尺寸 280x110 → 之后 +40/-? )
cands = [(12779, 5886), (12819, 5926), (12859, 5966)]
best = None
for (nx, ny) in cands:
    mv["x"], mv["y"] = nx, ny
    # 零重叠
    ok = True
    for n in nodes:
        if n.get("type") in ("bg", "row_bg") or n["id"] == "n_moveit":
            continue
        if not (mv["x"] + mv["w"] + 6 <= n["x"] or n["x"] + n["w"] + 6 <= mv["x"] or
                mv["y"] + mv["h"] + 6 <= n["y"] or n["y"] + n["h"] + 6 <= mv["y"]):
            ok = False
            break
    if not ok:
        print("  候选 (%d,%d): 与既有节点重叠, 跳过" % (nx, ny))
        continue
    c = count_cross(nodes, links)
    print("  候选 (%d,%d): 交叉 %d 对 (当前 %d, 变化 %+d)" % (nx, ny, c, c_before, c - c_before))
    if best is None or c < best[2]:
        best = ((nx, ny), ok, c)

if best and best[2] < c_before:
    mv["x"], mv["y"] = best[0]
    print("✅ 采用 (%d,%d): 交叉 %d → %d (减少 %d 对)" % (best[0][0], best[0][1], c_before, best[2], c_before - best[2]))
    bak = os.path.join(R, "flows/_archive/state_space_obs_before_moveitpos_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(FLOW, bak)
    json.dump(d, open(FLOW, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("   已写入 · 备份 %s" % os.path.relpath(bak, R))
    # 连通性复核
    real = [n for n in nodes if n.get("type") not in ("bg", "row_bg")]
    deg = {n["id"]: [0, 0] for n in real}
    for l in links:
        if l["f"] in deg:
            deg[l["f"]][1] += 1
        if l["t"] in deg:
            deg[l["t"]][0] += 1
    orph = [k for k, v in deg.items() if v[0] == 0 and v[1] == 0]
    print("   连通性: 孤立 %d (应 0) · MoveIt 入线 %d 出线 %d" % (len(orph), deg["n_moveit"][0], deg["n_moveit"][1]))
else:
    mv["x"], mv["y"] = pos_old
    print("⚠️ 候选均无改善 → 保持原位 (%d,%d), 文件未改" % pos_old)
