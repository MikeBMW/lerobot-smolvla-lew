#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""找出"文件里有、渲染时没建出 item"的节点 id (定位 85 vs 86)"""
import json
import os
import sys

sys.path.insert(0, "/home/ubuntu/zmax_rel/tools/gui")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5 import QtWidgets                                                      # noqa: E402

app = QtWidgets.QApplication(sys.argv)
import simulink_module as SM                                                     # noqa: E402

FLOW = "/home/ubuntu/zmax_rel/flows/state_space_obs.json"
spec = json.load(open(FLOW, encoding="utf-8"))
m = SM.SimulinkModule()
m.load_flow_file(FLOW, confirm=False)
app.processEvents()
have = set(m._items.keys())
want = [n["id"] for n in spec["nodes"]]
missing = [i for i in want if i not in have]
print("文件节点 %d · 唯一 %d · item %d" % (len(want), len(set(want)), len(have)))
print("没建出 item 的 id:", missing)
by = {n["id"]: n for n in spec["nodes"]}
for i in missing:
    print("   ", json.dumps(by[i], ensure_ascii=False)[:300])
# 连线
lh = {l["id"] for l in spec["links"]}
items = getattr(m, "_link_items", [])
print("文件连线 %d · 唯一 %d · 渲染 %d" % (len(spec["links"]), len(lh), len(items)))
