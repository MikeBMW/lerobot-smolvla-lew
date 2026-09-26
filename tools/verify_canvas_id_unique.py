#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""id 唯一性复现测试: 连续 N 次加载画布, 每次都必须 节点 item == 文件节点数 且 id 全唯一"""
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
NN, NL = len(spec["nodes"]), len(spec["links"])
bad = 0
for i in range(10):
    m = SM.SimulinkModule()
    m.load_flow_file(FLOW, confirm=False)
    app.processEvents()
    nid = [n["id"] for n in m.nodes]
    lid = [l["id"] for l in m.links]
    ok = (len(m._items) == NN) and (len(set(nid)) == len(nid)) and (len(set(lid)) == len(lid))
    if not ok:
        bad += 1
    print("轮%02d items=%d/%d 节点id唯一 %d/%d 连线id唯一 %d/%d %s"
          % (i + 1, len(m._items), NN, len(set(nid)), len(nid), len(set(lid)), len(lid),
             "✅" if ok else "❌"))
print("\n10 轮: 异常 %d 次 → %s" % (bad, "稳定 ✅" if bad == 0 else "仍有撞 id ❌"))
