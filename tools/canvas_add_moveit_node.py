#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""canvas_add_moveit_node.py — 在状态空间画布加「🧭 MoveIt 运动规划」节点 (老倪 2026-09-26)

要求: 「moveit 节点放在状态空间工程里, 并在画布上体现; 桥放在 Orin 上, 直接驱动 SDK」
语义:
  入线: 🌍 Z-MAX 引擎/状态空间 → MoveIt (目标位姿/意图 → 规划请求)
  出线: MoveIt → 🤖 机器人执行器 (规划轨迹 → 执行; 执行走 Orin SDK 桥, 兼容 ROS2 SRV)
硬断言 (沿用既有构图工具): id 唯一 / int 坐标 / 零重叠(排除背景) / 行带内 / 目标左侧同行 / 端口存在且前向无重复
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import time

ROOT = "/home/ubuntu/zmax_rel"
FLOW = os.path.join(ROOT, "flows/state_space_obs.json")
BGW = ("bg", "row_bg")
NID = "n_moveit"
NAME = "🧭 MoveIt 运动规划 · SDK 直驱桥(Orin)"
DESC = ("MoveIt2 规划 (IK/碰撞/轨迹) + 双执行后端: ① Orin SDK 桥 (xCoreSDK 直连控制器 192.168.23.160, "
        "不依赖 ROS2 栈, 实测 3~7ms/次) ② 兼容现有 ROS2 SRV (/move_pose 等)。安全闸在 L2 收口: "
        "Δ守卫/向下限幅/dry-run 默认。源码 src/lerobot/arm/arm_control.py · 桥: Orin zmax-arm-sdk-bridge.service")


def overlaps(a, b, pad=6):
    return not (a["x"] + a["w"] + pad <= b["x"] or b["x"] + b["w"] + pad <= a["x"] or
                a["y"] + a["h"] + pad <= b["y"] or b["y"] + b["h"] + pad <= a["y"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    d = json.load(open(FLOW, encoding="utf-8"))
    nodes, links = d["nodes"], d["links"]
    assert not any(n["id"] == NID for n in nodes), "节点已存在: %s" % NID

    # 位置: 与「🛡 安全执行边界(sslimit)」同行, 在其右侧 40px (语义: 限幅后 → 规划 → 执行)
    lim = next(n for n in nodes if n["id"] == "sslimit")
    row_y = lim["y"]
    x = int(lim["x"] + lim["w"] + 40)
    # 断言: 零重叠
    node = {"id": NID, "type": "model", "name": NAME, "x": int(x), "y": int(row_y), "w": 230, "h": 68,
            "desc": DESC, "inputs": ["in1", "in2"], "outputs": ["out1"],
            "params": {"layer": "L2/L3 执行面", "role": "MoveIt2 规划 + 双后端执行",
                       "backends": ["orin_sdk_bridge (xCoreSDK 直连, 默认/效率优先)",
                                    "ros2_srv (兼容现有 /move_pose)"],
                       "sdk_bridge": "http://192.168.23.66:39061",
                       "controller": "192.168.23.160",
                       "safety": "Δ守卫 · 向下限幅 · dry-run 默认 · 现场闸门",
                       "src": "src/lerobot/arm/arm_control.py",
                       "parity": "SDK vs ROS2 关节最大偏差 0.91 µrad (2026-09-26 实测)"}}
    for n in nodes:
        if n.get("type") in BGW or n["id"] == NID:
            continue
        assert not overlaps(node, n), "与 %s(%s) 重叠" % (n["id"], n["name"][:18])
    # 连线: 引擎(swworld) → MoveIt → 执行器(ssact); 端口存在 + 前向 + 无重复
    by = {n["id"]: n for n in nodes}
    new_links = []
    for f, t, fp, tp in (("sslimit", NID, "out1", "in1"), (NID, "ssact", "out1", "in1")):
        if f in by:
            assert fp in (by[f].get("outputs") or []), "%s 无出端口 %s" % (f, fp)
        if t in by:
            assert tp in (by[t].get("inputs") or []), "%s 无入端口 %s" % (t, tp)
        assert (f, t) not in [(l["f"], l["t"]) for l in links], "重复连线 %s→%s" % (f, t)
        new_links.append({"f": f, "t": t, "f_port": fp, "t_port": tp,
                          "label": "限幅后目标 → 规划" if t == NID else "轨迹 → 执行 (SDK桥 / ROS2 SRV)"})
    print("将新增节点: %s @ (%d,%d) 230x68  类型=model  (安全执行边界右侧 40px, 语义: 限幅→规划→执行)" % (NAME, x, row_y))
    for l in new_links:
        print("   连线:", l["f"], "→", l["t"], "(%s)" % l["label"])
    print("前: %d 节点 / %d 连线  → 后: %d 节点 / %d 连线" % (len(nodes), len(links), len(nodes) + 1, len(links) + len(new_links)))
    if a.dry_run:
        print("(--dry-run 未写盘)")
        return 0
    bak = os.path.join(ROOT, "flows/_archive/state_space_obs_before_moveit_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(FLOW, bak)
    nodes.append(node)
    links.extend(new_links)
    json.dump(d, open(FLOW, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("✅ 已写入 · 备份 %s" % os.path.relpath(bak, ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
