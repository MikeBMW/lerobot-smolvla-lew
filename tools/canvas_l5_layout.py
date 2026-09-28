#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""canvas_l5_layout.py — 把 L5 闭环节点加高 (68→132), 给"画布上的闭环进度三行"腾空间

老倪口径: 用户正看的界面必须看到变化 —— L5 节点要在画布上直接显示 标注 pid/批次/训练阶段,
不能只写日志。加高前断言: 仍在行帯内 + 与任何真节点零重叠 + 幂等。
写盘前备份到 flows/_archive/ 并打印还原命令。
"""
from __future__ import annotations

import json
import os
import shutil
import time

R = "/home/ubuntu/zmax_rel"
FLOW = os.path.join(R, "flows/state_space_obs.json")
ARCHIVE = os.path.join(R, "flows/_archive")
NID, NEW_H = "ss_l5", 132


def main() -> int:
    d = json.load(open(FLOW, encoding="utf-8"))
    nodes = d["nodes"]
    n = next((x for x in nodes if x["id"] == NID), None)
    assert n is not None, "缺节点 %s (先跑 tools/canvas_add_l5_node.py)" % NID
    if n.get("h") == NEW_H:
        print("✅ 幂等: %s 高度已是 %d" % (NID, NEW_H))
        return 0
    box = {"x": n["x"], "y": n["y"], "w": n["w"], "h": NEW_H}
    for o in nodes:
        if o is n or o.get("type") in ("bg", "row_bg"):
            continue
        if not (box["x"] + box["w"] + 8 <= o["x"] or o["x"] + o["w"] + 8 <= box["x"] or
                box["y"] + box["h"] + 8 <= o["y"] or o["y"] + o["h"] + 8 <= box["y"]):
            raise AssertionError("加高后与 %s (%s) 重叠" % (o["id"], o["name"][:24]))
    band = [b for b in nodes if b.get("type") == "row_bg" and b["y"] <= box["y"] < b["y"] + b["h"]]
    assert band and box["y"] + box["h"] <= band[0]["y"] + band[0]["h"], "超出行帯"
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = os.path.join(ARCHIVE, "state_space_obs_before_l5_h_%s.json" % ts)
    shutil.copy2(FLOW, bak)
    old = n["h"]
    n["h"] = NEW_H
    json.dump(d, open(FLOW, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("✅ %s 高度 %d → %d (行帯 [%s])" % (NID, old, NEW_H, band[0]["name"][:18]))
    print("   备份: %s" % os.path.relpath(bak, R))
    print("   ↩️ 还原: cp %s %s" % (os.path.relpath(bak, R), os.path.relpath(FLOW, R)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
