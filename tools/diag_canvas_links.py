#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""diag_canvas_links.py — 定位"连线全丢"的确切原因 (输出写文件, 避免 os._exit 吞输出)"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, "/home/ubuntu/zmax_rel/tools/gui")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5 import QtWidgets                                                  # noqa: E402

OUT = "/tmp/canvas_diag.txt"
lines = []


def p(*a):
    lines.append(" ".join(str(x) for x in a))


app = QtWidgets.QApplication(sys.argv)
import simulink_module as SM                                                 # noqa: E402

F = "/home/ubuntu/zmax_rel/flows/state_space_obs.json"
spec = json.load(open(F, encoding="utf-8"))
m = SM.SimulinkModule()
try:
    m.load_flow_file(F, confirm=False)
except Exception as e:                                                       # noqa: BLE001
    p("加载抛异常:", type(e).__name__, str(e)[:200])
app.processEvents()

items = dict(getattr(m, "_items", {}) or {})
links = list(getattr(m, "links", []) or [])
p("文件:", len(spec["nodes"]), "节点 /", len(spec["links"]), "连线")
p("加载后 self.nodes =", len(getattr(m, "nodes", []) or []), "| self.links =", len(links))
p("_items(节点项) =", len(items), "| 样例键:", list(items)[:5])
p("_link_items(连线项) =", len(getattr(m, "_link_items", []) or []))
have = set(items)
want = {n["id"] for n in spec["nodes"]}
p("缺节点项:", sorted(want - have))
both = [l for l in links if l.get("f") in have and l.get("t") in have]
p("两端都在 _items 的连线:", len(both), "/", len(links))
if links:
    p("第一条第连线:", json.dumps(links[0], ensure_ascii=False)[:140])
    p("  其 f/t 是否在 _items:", links[0].get("f") in have, links[0].get("t") in have)
notin = [(l.get("id"), l.get("f") in have, l.get("t") in have) for l in links if not (l.get("f") in have and l.get("t") in have)]
p("端点缺失连线数:", len(notin), "前 5:", notin[:5])
open(OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
sys.stderr.write("\n".join(lines) + "\n")
os._exit(0)
