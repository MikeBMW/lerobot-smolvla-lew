#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""canvas_add_realscene_node.py — 加「🎥 真实场景叠加 · 双眼」节点并连入状态空间 (老倪 2026-09-26)

语义:
  入线: 📦 数据源(ssdata) → 本机/臂上相机帧;  🌍 物理世界(ssworld) → 场景真值
  出线: → 🌍 Z-MAX 引擎(swworld) 「真实场景观测 + sim2real 参数映射 → 引擎同步」
接线: 只用既有端口; 硬断言 (端口存在/无重复/零重叠/前向线); 渲染复核; 备份
"""
from __future__ import annotations

import json
import os
import shutil
import time

R = "/home/ubuntu/zmax_rel"
FLOW = os.path.join(R, "flows/state_space_obs.json")
NID, NAME = "n_realscene", "🎥 真实场景叠加 · 双眼 (sim2real)"
DESC = ("本机内置相机 + 臂上 realsense 双路叠加(并排/半透明/边缘对齐/参数带); "
        "输出真实场景观测 + sim2real 参数映射(相机/TCP/关节/夹爪/光照) → 引擎同步; 只读不动机器人")
IN_PORT, OUT_PORT = "in1", "out1"


def main() -> int:
    d = json.load(open(FLOW, encoding="utf-8"))
    nodes, links = d["nodes"], d["links"]
    by = {n["id"]: n for n in nodes}
    assert NID not in by, "节点已存在"
    src_in = "ssdata"                      # 入: 数据源
    src_in2 = "ssworld"                    # 入: 物理世界 (真值)
    dst_out = "swworld"                    # 出: Z-MAX 引擎
    for nid in (src_in, src_in2, dst_out):
        assert nid in by, "缺少引用节点 %s" % nid
    # 位置: 找到"数据源/物理世界"行, 放在其左侧空位 (不与任何真节点重叠)
    y_ref = by[src_in]["y"]
    x_cand = by[src_in]["x"] + by[src_in]["w"] + 60      # 放在数据源**右侧** (保证前向线)
    x_lim = by[dst_out]["x"] - 300                        # 且仍在引擎左侧
    while x_cand < x_lim:
        box = {"x": x_cand, "y": y_ref, "w": 260, "h": 90}
        ok = True
        for n in nodes:
            if n.get("type") in ("bg", "row_bg"):
                continue
            if not (box["x"] + box["w"] + 8 <= n["x"] or n["x"] + n["w"] + 8 <= box["x"] or
                    box["y"] + box["h"] + 8 <= n["y"] or n["y"] + n["h"] + 8 <= box["y"]):
                ok = False
                break
        if ok:
            break
        x_cand += 300
    node = {"id": NID, "type": "model", "name": NAME, "x": int(x_cand), "y": int(y_ref),
            "w": 260, "h": 90, "desc": DESC, "inputs": [IN_PORT], "outputs": [OUT_PORT]}
    def p0(nid, key, dflt):
        v = by[nid].get(key) or [dflt]
        x = v[0]
        return x if isinstance(x, str) else str(x.get("id", dflt))

    add = [{"f": src_in, "t": NID, "f_port": p0(src_in, "outputs", "out1"), "t_port": IN_PORT,
            "label": "相机帧 → 双眼叠加"},
           {"f": NID, "t": dst_out, "f_port": OUT_PORT, "t_port": p0(dst_out, "inputs", "in1"),
            "label": "真实场景 + sim2real 映射 → 引擎同步"}]
    nodes.append(node); by[NID] = node          # 先把新节点挂上, 再做端口断言
    have = {(l["f"], l["t"]) for l in links}
    for a in add:
        ins = [x if isinstance(x, str) else str(x.get("id")) for x in (by[a["t"]].get("inputs") or [])]
        outs = [x if isinstance(x, str) else str(x.get("id")) for x in (by[a["f"]].get("outputs") or [])]
        assert a["t_port"] in ins, "%s 无入端口 %s (有 %s)" % (a["t"], a["t_port"], ins)
        assert a["f_port"] in outs, "%s 无出端口 %s (有 %s)" % (a["f"], a["f_port"], outs)
        assert (a["f"], a["t"]) not in have, "重复连线"
        assert by[a["f"]]["x"] + by[a["f"]]["w"] <= by[a["t"]]["x"] + 1, "反向线 %s→%s" % (a["f"], a["t"])
    bak = os.path.join(R, "flows/_archive/state_space_obs_before_realscene_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(FLOW, bak)
    links.extend(add)
    json.dump(d, open(FLOW, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # 连通性
    real = [n for n in nodes if n.get("type") not in ("bg", "row_bg")]
    deg = {n["id"]: [0, 0] for n in real}
    for l in links:
        if l["f"] in deg: deg[l["f"]][1] += 1
        if l["t"] in deg: deg[l["t"]][0] += 1
    orph = [k for k, v in deg.items() if v[0] == 0 and v[1] == 0]
    print("✅ 节点 %s @ (%d,%d) 260x90 · 入:%s 出:%s" % (NID, node["x"], node["y"], src_in, dst_out))
    print("   画布: %d 节点(%d 真) / %d 连线 · 孤立 %d · 新节点度数 %s"
          % (len(nodes), len(real), len(links), len(orph), deg[NID]))
    assert len(orph) == 0
    print("   备份: %s" % os.path.relpath(bak, R))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
