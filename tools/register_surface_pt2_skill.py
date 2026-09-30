#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""register_surface_pt2_skill.py — 注册『🎯 回到侧面点2』技能 (幂等, 只加法)

老倪 2026-10-01: 「记录现在的表面检测的位姿, 侧面点2, 并增加侧面点2的技能,
在表面检测窗口下面的侧面点1旁边增加 侧面点2 按钮」

与 L2.goto_surface_pt1 / L2.goto_gold_pt1 完全同规格(回点类技能的铁律):
  · ros=line_abs + quat="taught"  → 位置**和姿态**都回示教点(不然姿态沿用当前, 视角不对)
  · point_locked + point           → 目标点写死在定义里, 页面/接口都改不了点位
  · guard.dz_down_limit_mm=20      → 相对当前位姿下降 >20mm 拒发(要下降得显式 allow_down_mm)
点位真值在 data/skills/l2_atomic/taught_points.json 的『侧面点2』(现场实录, 不在本脚本里)。

用法: python3 tools/register_surface_pt2_skill.py     # 幂等注册(已存在则只校验不改写)
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = os.path.join(ROOT, "data/skills/l2_atomic/registry.json")

SKILL = {
    "id": "L2.goto_surface_pt2",
    "name": "🎯 回到侧面点2",
    "icon": "🎯",
    "ros": "line_abs",
    "quat": "taught",
    "point": "侧面点2",
    "point_locked": True,
    "group": "AOI检测",
    "guard": {"dz_down_limit_mm": 20},
    "note": ("回到示教点『侧面点2』(表面/侧面检测第二观察位) — 位姿由 tools/record_point_sdk.py 现场记录"
             "(ROKAE SDK 直读 endInRef, 页面同源); 位置+姿态锁定, 向下>20mm 需显式允许"),
}


def main():
    reg = json.load(open(REG, encoding="utf-8"))
    skills = reg.setdefault("skills", [])
    hit = [s for s in skills if s.get("id") == SKILL["id"]]
    if hit:
        same = all(hit[0].get(k) == SKILL[k] for k in SKILL)
        print(("✅ 已存在且一致" if same else "⚠️ 已存在但字段不同(未改写)") + ": " + SKILL["id"])
        if not same:
            print("   现有:", json.dumps(hit[0], ensure_ascii=False))
            print("   期望:", json.dumps(SKILL, ensure_ascii=False))
        return 0 if same else 1
    skills.append(SKILL)
    with open(REG, "w", encoding="utf-8") as f:
        json.dump(reg, f, ensure_ascii=False, indent=2)
    print("✅ 已注册 %s → %s (共 %d 条)" % (SKILL["id"], REG, len(skills)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
