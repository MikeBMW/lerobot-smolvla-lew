#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""register_approach_skill.py — 通用「三段式靠近」技能 (幂等)

用途: 把「到某个示教点」从**一次直线**(长距离时=低空横移/斜插, 违反现场两点转移铁律)
      改成 3 段: ①就地垂直抬升 climb ②高位平移到目标正上方 +traverse_dz ③垂直下落。
      姿态: ②③ 段用示教姿态(quat=taught), ①段是 rel ⇒ 取**现读**当前姿态 ⇒ 纯平移不转。

现场铁律(老倪 2026-09-30): 「要先垂直抬升5厘米, 才能去别的地方。要到任何一个位置,
也要先到这个位置的上方, 再垂直下落。」

用法:
  tools/register_approach_skill.py --point 侧面点1 --skill-id L2.approach_surface_pt1 \
      --name "🎯 靠近侧面点1(3段平滑)" --climb 50 --traverse-dz 60 [--descent-guard-mm 100]
"""
from __future__ import annotations
import argparse, json, os, shutil, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = os.path.join(ROOT, "data/skills/l2_atomic/registry.json")
PTS = os.path.join(ROOT, "data/skills/l2_atomic/taught_points.json")
WL = os.path.join(ROOT, "data/skills/l2_atomic/ctl_abs_skills.json")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--point", required=True)
    ap.add_argument("--skill-id", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--climb", type=float, default=50.0, help="阶段1 就地垂直抬升 mm")
    ap.add_argument("--no-climb", action="store_true",
                    help="省掉阶段1(当前已在高位时用) ⇒ 只 2 段: 高位平移到目标正上方 → 垂直下落。"
                         "2026-10-01 现场: 停在 0.583(比准备点高 214mm)要回撤 ⇒ 再抬 50mm 会到 0.633(逼近横梁/包络上限 0.6987)")
    ap.add_argument("--traverse-dz", type=float, default=50.0,
                    help="阶段2 目标点正上方的高度 mm · 🛡 2026-10-01 碰撞教训: 必须相对目标点就近有界(默认 50), "
                         "禁止 180 这类绝对量 —— 它会让臂从起点凭空再抬 200mm+ 顶到横梁风险区")
    ap.add_argument("--descent-guard-mm", type=float, default=100.0, help="阶段3 允许的下降量 mm")
    ap.add_argument("--z-floor-point", default=None,
                    help="技能级 z 硬红线的参考点(低于此点 z 一律拒发)。默认不设; 本用例应给**起点/准备点**而不是目标点 —— "
                         "目标点比起点高时, 拿目标当红线会把'就地抬升'直接拒掉(2026-10-01 实测被拦)")
    ap.add_argument("--group", default="表面检测观察位")
    a = ap.parse_args()
    if not a.skill_id.startswith("L2."):
        print("❌ skill-id 必须以 L2. 开头(白名单只认 L2 开头)"); return 2

    pts = json.load(open(PTS, encoding="utf-8")); pts = pts.get("points", pts)
    if a.point not in pts:
        print("❌ 点位『%s』不在示教点库 —— 先录点" % a.point); return 2
    p = pts[a.point]["pos"]
    print("点位 %s pos=(%.6f, %.6f, %.6f) ⇒ 段1 抬 %.0fmm · 段2 到 z=%.4f(点位+%.0f, ⚠️≤100mm) · 段3 垂直下落 %.0fmm"
          % (a.point, p[0], p[1], p[2], a.climb, p[2] + a.traverse_dz / 1000.0, a.traverse_dz, a.traverse_dz))

    sk = {
        "id": a.skill_id, "name": a.name, "icon": "🎯", "ros": "line_abs", "quat": "taught",
        "point": a.point, "point_locked": True, "group": a.group, "speed_max": 200, "param": {},
        "guard": dict([("max_lin_mm", 1200.0)] + ([("z_floor_point", a.z_floor_point), ("z_floor_offset_mm", 0)] if a.z_floor_point else [])),
        "steps": ([  # --no-climb: 已在高位, 只走 平移+下落, 不做再抬升
            {"stage": 1, "to": a.point, "dz_mm": a.traverse_dz,
             "note": "阶段1 高位平移到%s正上方(z=点位+%.0fmm; 当前已在高位 ⇒ 不额外抬升, 全程不下沉; 转身在空中完成)" % (a.point, a.traverse_dz),
             "guard": {"dz_down_limit_mm": 400}, "tol_mm": 1.5, "timeout_s": 300, "dwell_s": 1.5},
            {"stage": 2, "to": a.point, "dz_mm": 0.0,
             "note": "阶段2 纯垂直下落到%s(到位即停, 禁下压)" % a.point,
             "guard": {"dz_down_limit_mm": max(a.descent_guard_mm, a.traverse_dz + 40)}, "tol_mm": 0.5, "timeout_s": 300, "dwell_s": 1.0},
        ] if a.no_climb else [
            {"stage": 1, "rel": True, "dz_mm": a.climb,
             "note": "阶段1 就地垂直抬升 %.0fmm(铁律: 抬够才能去别的地方; rel ⇒ 姿态取现读, 纯平移不转)" % a.climb,
             "guard": {"dz_down_limit_mm": 400}, "tol_mm": 1.0, "timeout_s": 90, "dwell_s": 1.5},
            {"stage": 2, "to": a.point, "dz_mm": a.traverse_dz,
             "note": "阶段2 高位平移到%s正上方(z=点位+%.0fmm) —— 转身/横移都在空中完成, 全程不下沉" % (a.point, a.traverse_dz),
             "guard": {"dz_down_limit_mm": 400}, "tol_mm": 1.0, "timeout_s": 300, "dwell_s": 1.5},
            {"stage": 3, "to": a.point, "dz_mm": 0.0,
             "note": "阶段3 纯垂直下落到%s(到位即停, 禁下压)" % a.point,
             "guard": {"dz_down_limit_mm": a.descent_guard_mm}, "tol_mm": 0.5, "timeout_s": 180, "dwell_s": 1.0},
             ]),
        "contact_guard": "阶段3 到位即停、禁下压; 若现场见顶住/擦碰 ⇒ 把%s抬高 3~5mm 重录, 不改判据硬说成功" % a.point,
        "note": "三段式靠近 %s(2026-10-01 老倪: 「你来规划从准备点到侧面点1的动作, 慢一些, 我监控, 中间的轨迹要平滑」): "
                "长距离直插=低空横移/斜插 ⇒ 拆 抬升/高位平移/垂直下落 三段; 姿态在段2 空中完成。" % a.point,
    }
    reg = json.load(open(REG, encoding="utf-8"))
    lst = reg["skills"] if isinstance(reg, dict) and isinstance(reg.get("skills"), list) else reg
    old = [s for s in lst if s.get("id") == a.skill_id]
    if old:
        lst[lst.index(old[0])] = sk; act = "已更新"
    else:
        lst.append(sk); act = "已注册"
    shutil.copy(REG, REG + ".bak_%s" % time.strftime("%Y%m%d_%H%M%S"))
    json.dump(reg, open(REG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("✅ %s %s (技能库共 %d 条)" % (act, a.skill_id, len(lst)))
    wl = json.load(open(WL, encoding="utf-8")) if os.path.exists(WL) else {}
    wl.setdefault("skills", {})[a.skill_id] = a.name
    json.dump(wl, open(WL, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("✅ 白名单热读标签: %s = %s (共 %d 条)" % (a.skill_id, a.name, len(wl["skills"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
