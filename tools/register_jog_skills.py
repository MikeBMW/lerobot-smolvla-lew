#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""register_jog_skills.py — 方向化点动技能 (2026-09-20 老倪指令)

「前后平移」→ 「前进」+「后退」两个技能; 「左右平移」→ 「向左」+「向右」两个技能。
- **距离只填正数, 方向由技能内定** —— 现场不用再填负号(填错符号 = 往反方向走)。
- 符号口径与旧标签一致 (机器人右手系): +X=前 · +Y=左 · +Z=上。
- 幂等: 旧的 L2.move_x / L2.move_y 会被移除, 重复跑只覆盖同 id。
"""
import json
import os
import shutil
import sys
import time

REG = "/home/ubuntu/lerobot-smolvla-lew/data/skills/l2_atomic/registry.json"
OLD = ["L2.move_x", "L2.move_y"]

JOGS = [
    {"id": "L2.forward", "name": "前进", "icon": "⏩", "axis": "x_pos",
     "label": "前进距离", "note": "基座 **+X** 方向平移; 距离只填正数(方向内定) —— 2026-09-20 起取代「前后平移」的 ± 输入"},
    {"id": "L2.backward", "name": "后退", "icon": "⏪", "axis": "x_neg",
     "label": "后退距离", "note": "基座 **-X** 方向平移; 距离只填正数(方向内定)"},
    {"id": "L2.left", "name": "向左", "icon": "⬅️", "axis": "y_pos",
     "label": "向左距离", "note": "基座 **+Y** 方向平移; 距离只填正数(方向内定) —— 取代「左右平移」的 ± 输入"},
    {"id": "L2.right", "name": "向右", "icon": "➡️", "axis": "y_neg",
     "label": "向右距离", "note": "基座 **-Y** 方向平移; 距离只填正数(方向内定)"},
]


def build(j):
    return {
        "id": j["id"],
        "name": j["name"],
        "icon": j["icon"],
        "ros": "line_rel",
        "axis": j["axis"],
        "param": {"d_mm": {"default": 50, "unit": "mm", "min": 5, "max": 300, "label": j["label"]}},
        "note": j["note"] + " · 符号口径: +X=前 · +Y=左 · +Z=上",
    }


def main():
    reg = json.load(open(REG, encoding="utf-8"))
    bak = "/tmp/registry.json.prejog_%d" % time.time()
    shutil.copy2(REG, bak)
    before = [s["id"] for s in reg["skills"]]
    reg["skills"] = [s for s in reg["skills"] if s["id"] not in OLD]
    ids = [s["id"] for s in reg["skills"]]
    at = ids.index("L2.lower") + 1 if "L2.lower" in ids else 0
    for j in JOGS:
        sk = build(j)
        if j["id"] in ids:
            reg["skills"][ids.index(j["id"])] = sk
            act = "覆盖"
        else:
            reg["skills"].insert(at, sk)
            ids.insert(at, j["id"])
            at += 1
            act = "新增"
        print("  %s %s「%s」axis=%s" % (act, j["id"], sk["name"], sk["axis"]))
    json.dump(reg, open(REG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    chk = json.load(open(REG, encoding="utf-8"))
    got = {s["id"]: s for s in chk["skills"]}
    assert set(OLD).isdisjoint(got), "旧平移技能没删干净"
    for j in JOGS:
        assert got[j["id"]]["axis"] == j["axis"], j["id"]
    print("✅ 点动技能: 删除 %s → 现为 前进/后退/向左/向右 · 技能总数 %d · 备份 %s"
          % ([o for o in OLD if o in before], len(chk["skills"]), bak))
    print("   顺序: " + " · ".join("%s %s" % (s.get("icon", "•"), s["name"])
                                  for s in chk["skills"][:8]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
