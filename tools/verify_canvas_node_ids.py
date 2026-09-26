#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查: n_realscene 是否真在 _items 里 + 重复渲染复现性 (3 轮)"""
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

for i in range(3):
    m = SM.SimulinkModule()
    m.load_flow_file(FLOW, confirm=False)
    app.processEvents()
    ids = list(m._items.keys())
    hit = [k for k, v in m._items.items() if "真实场景叠加" in v.node.get("name", "")]
    print("轮%d: 文件节点 %d · items %d · n_realscene in items: %s · 命中: %s"
          % (i + 1, len(spec["nodes"]), len(ids), "n_realscene" in m._items,
             [(k, m._items[k].node.get("id")) for k in hit]))
    tgt = m._ov_live_target_item()
    print("      _ov_live_target_item -> %s" % (tgt.node.get("id") if tgt else None))
    # 样本 id 形状
    print("      items 前 3 键: %s" % ids[:3])
