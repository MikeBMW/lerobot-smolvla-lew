#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""register_goto_skill.py — 通用「回到示教点 X」技能注册 (幂等, 只加法)

2026-10-01: 老倪连加 侧面点1/2/3 ⇒ 把「改一个 id/点名」这件事从复制脚本变成传参。

回点类技能的铁律四件套(见 real-arm-motion-control 技能):
  ros=line_abs + quat="taught"(位置**和**姿态都回点) + point_locked+point(点位写死) + guard.dz_down_limit_mm=20

用法:
  python3 tools/register_goto_skill.py --point 侧面点3 --skill-id L2.goto_surface_pt3 --name "🎯 回到侧面点3"
  python3 tools/register_goto_skill.py --point 侧面点4 --skill-id L2.goto_surface_pt4 --name "🎯 回到侧面点4" --group AOI检测
"""
import argparse, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = os.path.join(ROOT, "data/skills/l2_atomic/registry.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--point", required=True, help="示教点名(必须在 taught_points.json 里)")
    ap.add_argument("--skill-id", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--group", default="AOI检测")
    ap.add_argument("--note", default="")
    a = ap.parse_args()

    pts = json.load(open(os.path.join(ROOT, "data/skills/l2_atomic/taught_points.json"), encoding="utf-8"))["points"]
    if a.point not in pts:
        print("❌ 示教点库没有 <%s> —— 先录点: tools/record_point_sdk.py --record %s" % (a.point, a.point))
        return 2
    skill = {"id": a.skill_id, "name": a.name, "icon": "🎯", "ros": "line_abs", "quat": "taught",
             "point": a.point, "point_locked": True, "group": a.group,
             "guard": {"dz_down_limit_mm": 20},
             "note": a.note or ("回到示教点『%s』— 位姿由 tools/record_point_sdk.py 现场记录"
                                "(ROKAE SDK 直读 endInRef, 页面同源); 位置+姿态锁定, 向下>20mm 需显式允许" % a.point)}
    reg = json.load(open(REG, encoding="utf-8"))
    skills = reg.setdefault("skills", [])
    hit = [s for s in skills if s.get("id") == skill["id"]]
    if hit:
        same = all(hit[0].get(k) == skill[k] for k in skill)
        print(("✅ 已存在且一致" if same else "⚠️ 已存在但字段不同(未改写)") + ": " + skill["id"])
        if not same:
            print("   现有:", json.dumps(hit[0], ensure_ascii=False))
            print("   期望:", json.dumps(skill, ensure_ascii=False))
        return 0 if same else 1
    skills.append(skill)
    json.dump(reg, open(REG, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("✅ 已注册 %s → 点名『%s』(共 %d 条)" % (skill["id"], a.point, len(skills)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
