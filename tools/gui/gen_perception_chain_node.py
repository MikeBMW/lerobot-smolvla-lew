#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_perception_chain_node.py — 画布接入: 📐 板坐标系定位(工序坐标系) 节点 + 真连线 (幂等)"""
import json
import shutil
import os
import time

FLOW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "flows", "state_space_obs.json")
FLOW = os.path.abspath(FLOW)
NID = "n_board_frame"

def _node():
    return {"id": NID, "type": "process",
            "name": "📐 板坐标系定位 (工序坐标系·免手眼)",
            "x": 300.0, "y": 300.0, "w": 190.0, "h": 64.0,
            "params": {"kind": "real", "real": True, "dock": "board_frame",
                       "source": "tools/board_frame_module.py",
                       "desc": "真机帧 → 板检测(20点/反色/排镜像) → 模块射线∩板平面 → 模块在板坐标(x,y)mm。绕开手拖位姿精度限制; 精度~1mm(图像决定)。",
                       "out": "模块在板坐标系 (x,y) mm · 离板面 mm · 板距 m · conf"}}

LINKS = [
    ("ssyolo", NID, "in1", "YOLO 2D 框 → 射线 (L2 感知)"),
    ("ssz700", NID, "in2", "真机帧 → 板检测 (20 圆点)"),
    ("n_dsvl", NID, "in3", "VL 场景判读 → 工序纠错 (L3 理解)"),
    (NID, "ss2d3d", "in1", "板坐标系 3D 定位 → 3D 框/目标点"),
    (NID, "sssched", "in1", "工序坐标系目标 → 动作调制"),
    (NID, "ss_mem_share", "in1", "模块位姿 → 总装记忆"),
]

def main():
    d = json.load(open(FLOW, encoding="utf-8"))
    ids = {n["id"] for n in d["nodes"]}
    added = []
    if NID not in ids:
        d["nodes"].append(_node())
        added.append("节点 " + NID)
    have = {(l["f"], l["t"], l.get("label", "")) for l in d.get("links", [])}
    for f, t, port, lab in LINKS:
        if f not in {n["id"] for n in d["nodes"]} or t not in {n["id"] for n in d["nodes"]}:
            print("  ⚠️ 端点不存在, 跳过:", f, "→", t)
            continue
        if (f, t, lab) in have:
            continue
        d.setdefault("links", []).append({"id": "lkbdf%d" % (len(d.get("links", [])) + 1), "f": f, "t": t, "f_port": "out1", "t_port": port, "label": lab})
        added.append("连线 " + lab)
    if added:
        shutil.copy2(FLOW, FLOW + ".bak_%d" % int(time.time()))
        json.dump(d, open(FLOW, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("本节点数:", len(d["nodes"]), "| 连线:", len(d.get("links", [])))
    for a in added:
        print("  +", a)
    if not added:
        print("  (已存在, 幂等跳过)")


if __name__ == "__main__":
    import shutil
    main()
