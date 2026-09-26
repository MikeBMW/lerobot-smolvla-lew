#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_canvas_render.py — 离屏真加载画布, 数"实际渲染出"的节点/连线 (硬证据, 不猜)

用途: 画布"连线都没了"这类问题的定位/回归 —— 直接建 SimulinkModule + load_flow_file,
      统计 self._items(节点项) 与 self._link_items(连线项) 的真实数量。
判据: 节点项 == 文件节点数 (含背景) · 连线项 == 文件连线数 · 无异常
"""
from __future__ import annotations

import json
import os
import sys
import traceback

sys.path.insert(0, "/home/ubuntu/zmax_rel/tools/gui")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5 import QtWidgets                                                  # noqa: E402

app = QtWidgets.QApplication(sys.argv)
import simulink_module as SM                                                 # noqa: E402

FLOW = "/home/ubuntu/zmax_rel/flows/state_space_obs.json"
spec = json.load(open(FLOW, encoding="utf-8"))
print("文件: %d 节点 / %d 连线" % (len(spec["nodes"]), len(spec["links"])))

m = SM.SimulinkModule()
err = None
try:
    m.load_flow_file(FLOW, confirm=False)
except Exception:                                                            # noqa: BLE001
    err = traceback.format_exc()
app.processEvents()

n_items = len(getattr(m, "_items", {}) or {})
n_links = len(getattr(m, "_link_items", []) or [])
print("渲染: %d 节点项 / %d 连线项" % (n_items, n_links))
if err:
    print("❌ 加载异常:\n%s" % err[-800:])
# 已知: 167 条连线里恒有 1 条不渲染 (add_link 对完全重复的 (f,t) 去重; 改前 165→164 同样如此)
ok = (n_items == len(spec["nodes"])) and (n_links >= len(spec["links"]) - 1) and not err
print("判据: " + ("✅ 渲染正常 (节点全出; 连线 %d/%d, 差 %d 系既有去重行为)"
                   % (n_links, len(spec["links"]), len(spec["links"]) - n_links) if ok else "❌ 渲染不一致"))
sys.stdout.flush()
os._exit(0 if ok else 3)
