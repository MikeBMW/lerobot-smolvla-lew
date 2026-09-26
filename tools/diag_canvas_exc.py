#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""diag_canvas_exc.py — 抓"工作流加载部分失败"的真实异常原文 (monkeypatch _log)"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, "/home/ubuntu/zmax_rel/tools/gui")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5 import QtWidgets                                                  # noqa: E402

logs = []
app = QtWidgets.QApplication(sys.argv)
import simulink_module as SM                                                 # noqa: E402

m = SM.SimulinkModule()


def _log_capture(msg, *a, **k):
    logs.append(str(msg))


m._log = _log_capture
F = "/home/ubuntu/zmax_rel/flows/state_space_obs.json"
m.load_flow_file(F, confirm=False)
app.processEvents()
print("=== 加载日志 ===")
for x in logs:
    print("  ", x)
print("=== 我的节点 spec (验证 add_node 会挂在哪) ===")
spec = json.load(open(F, encoding="utf-8"))
mine = [n for n in spec["nodes"] if n["id"] == "n_hil"][0]
print("  ", json.dumps(mine, ensure_ascii=False)[:300])
# 单独试 add_node 我的节点 → 拿真实异常
try:
    m.add_node(mine.get("type", "system"), mine.get("name", "?"), mine.get("x", 0), mine.get("y", 0), mine.get("params", {}))
    print("  单独 add_node: ✅ 没抛")
except Exception as e:                                                       # noqa: BLE001
    import traceback
    print("  单独 add_node: ❌ %s: %s" % (type(e).__name__, e))
    traceback.print_exc()
sys.stdout.flush()
os._exit(0)
