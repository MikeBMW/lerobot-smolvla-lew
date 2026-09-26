#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""compare_canvas_render.py — 对比"改前(HEAD~1) vs 改后(当前)"两个画布文件的真实渲染数
输出写 /tmp/canvas_render_cmp.txt (避免 os._exit 吞输出)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

sys.path.insert(0, "/home/ubuntu/zmax_rel/tools/gui")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5 import QtWidgets                                                  # noqa: E402

lines = []


def p(*a):
    lines.append(" ".join(str(x) for x in a))


app = QtWidgets.QApplication(sys.argv)
import simulink_module as SM                                                 # noqa: E402

CUR = "/home/ubuntu/zmax_rel/flows/state_space_obs.json"
OLD = "/tmp/flow_head1.json"
open(OLD, "w", encoding="utf-8").write(
    subprocess.run(["git", "-C", "/home/ubuntu/zmax_rel", "show", "HEAD~1:flows/state_space_obs.json"],
                   capture_output=True, text=True).stdout)


def probe(path, tag):
    spec = json.load(open(path, encoding="utf-8"))
    m = SM.SimulinkModule()
    lg = []
    m._log = lambda msg, *a, **k: lg.append(str(msg))
    m.load_flow_file(path, confirm=False)
    app.processEvents()
    p("%s: 文件 %d 节点/%d 连线 → 渲染 %d 节点项/%d 连线项 %s"
      % (tag, len(spec["nodes"]), len(spec["links"]), len(m._items), len(m._link_items),
         [x for x in lg if "失败" in x or "❌" in x][:2]))
    # 未渲染的连线 (按节点名映射新 id)
    id2name = {n["id"]: n["name"] for n in spec["nodes"]}
    name2new = {}
    for k, v in {n["id"]: n["name"] for n in (m.nodes or [])}.items():
        name2new.setdefault(v, []).append(k)
    loaded_pairs = {(l["f"], l["t"]) for l in (m.links or [])}
    miss = []
    for l in spec["links"]:
        fn, tn = id2name.get(l["f"], "?"), id2name.get(l["t"], "?")
        pairs = {(a, b) for a in name2new.get(fn, []) for b in name2new.get(tn, [])}
        if pairs and not (pairs & loaded_pairs):
            miss.append((l["id"], fn[:20], tn[:20]))
    p("    未渲染连线 %d 条: %s" % (len(miss), miss[:4]))
    return m


probe(OLD, "改前 HEAD~1")
probe(CUR, "改后 当前")
open("/tmp/canvas_render_cmp.txt", "w", encoding="utf-8").write("\n".join(lines) + "\n")
sys.stderr.write("\n".join(lines) + "\n")
os._exit(0)
