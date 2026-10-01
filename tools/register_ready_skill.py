#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""register_ready_skill.py — 注册「回到准备点」技能 L2.goto_ready (幂等)

背景 (2026-10-01 老倪: 「增加 按钮 准备点，在表面检测的窗口，位置位于 侧面点0的前面」):
  准备点 = 老倪现场手动退让危险点(侧面点0)后确认的安全位, 已用 record_point_sdk.py 录点。

⚠️ 为什么不做成一次直线移动:
  准备点比各侧面点**低 118~169mm、横向 218~244mm** ⇒ 直线过去就是「低空横移/斜插」,
  违反现场铁律「要先垂直抬升5厘米, 才能去别的地方。要到任何一个位置, 也要先到这个位置的上方,
  再垂直下落」。⇒ 与号位技能同构, 拆 3 段:
    ① 就地垂直抬升 50mm (rel, 不依赖任何点位)
    ② 平移到准备点正上方 50mm (z=准备点+50 ⇒ 只为满足"先到上方再垂直下落"; ⚠️ 不允许 +180 那种绝对量)
    ③ 垂直下落到准备点 (到位即停, 禁下压)
  真值只有一个来源: 示教点库里的 准备点 (point_locked) ⇒ 页面/接口都改不了点位。
"""
from __future__ import annotations
import json, os, shutil, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = os.path.join(ROOT, "data/skills/l2_atomic/registry.json")
PTS = os.path.join(ROOT, "data/skills/l2_atomic/taught_points.json")
WL = os.path.join(ROOT, "data/skills/l2_atomic/ctl_abs_skills.json")

SID = "L2.goto_ready"
NAME = "🎯 回到准备点"
POINT = "准备点"
# 🛡 2026-10-01 碰撞教训(见 docs/INCIDENT-20261001-traverse-height-collision.md):
#   横移高度**必须相对目标点就近有界**, 不能写成"目标点z+180" —— 那会让臂从起点凭空再抬 200mm+ 顶到横梁风险区。
#   现场规矩「升高不要超过 10cm」⇒ 取 50mm(到目标点正上方 50mm 再垂直下落, 最低限度满足"先到上方再下落")。
TRAVERSE_DZ = 50.0     # 平移段所在高度 = 准备点 z + 50mm


def main() -> int:
    pts = json.load(open(PTS, encoding="utf-8"))
    pts = pts.get("points", pts)
    if POINT not in pts:
        print("❌ 点位『%s』不在 %s —— 先录点: tools/record_point_sdk.py --record %s" % (POINT, os.path.basename(PTS), POINT))
        return 2
    p = pts[POINT]["pos"]
    print("点位 %s pos=(%.6f, %.6f, %.6f) ⇒ 平移段高度 z=%.4f, 末段下落 180mm" % (POINT, p[0], p[1], p[2], p[2] + TRAVERSE_DZ / 1000.0))

    reg = json.load(open(REG, encoding="utf-8"))
    lst = reg["skills"] if isinstance(reg, dict) and isinstance(reg.get("skills"), list) else reg
    skill = {
        "id": SID, "name": NAME, "icon": "🎯", "ros": "line_abs", "quat": "taught",
        "point": POINT, "point_locked": True, "group": "安全位", "speed_max": 150,
        "param": {},
        "guard": {"max_lin_mm": 1200.0, "z_floor_point": POINT, "z_floor_offset_mm": 0},
        "steps": [
            {"stage": 1, "rel": True, "dz_mm": 50.0,
             "note": "阶段1 就地垂直抬升 50mm(现场铁律: 抬够才能去别的地方)",
             "guard": {"dz_down_limit_mm": 400}, "tol_mm": 1.0, "timeout_s": 60, "dwell_s": 1.5},
            {"stage": 2, "to": POINT, "dz_mm": TRAVERSE_DZ,
             "note": "阶段2 高位平移到准备点正上方(目标 z=点位+%dmm) ⇒ 全程不下沉, 不做低空横移" % int(TRAVERSE_DZ),
             "guard": {"dz_down_limit_mm": 400}, "tol_mm": 1.0, "timeout_s": 180, "dwell_s": 1.5},
            {"stage": 3, "to": POINT, "dz_mm": 0.0,
             "note": "阶段3 垂直下落到准备点(到位即停, 禁下压)",
             "guard": {"dz_down_limit_mm": 260}, "tol_mm": 0.5, "timeout_s": 180, "dwell_s": 1.0},
        ],
        "contact_guard": "阶段3 到位即停、禁下压; 若现场见顶住/擦碰, 把准备点抬高 3~5mm 重录 —— 不改判据硬说成功",
        "note": "准备点收口技能(3 段转移, 2026-10-01): 点位真值在示教点库 准备点(老倪现场手动退让危险点侧面点0 后确认的安全位); "
                "位置+姿态锁定; 未录点时调用被干净拒发「点位 准备点 不在点位库」。",
    }
    old = [s for s in lst if s.get("id") == SID]
    if old:
        lst[lst.index(old[0])] = skill
        act = "已更新"
    else:
        lst.append(skill)
        act = "已注册"
    shutil.copy(REG, REG + ".bak_%s" % time.strftime("%Y%m%d_%H%M%S"))
    json.dump(reg, open(REG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("✅ %s %s → 点位『%s』(技能库共 %d 条)" % (act, SID, POINT, len(lst)))

    wl = json.load(open(WL, encoding="utf-8")) if os.path.exists(WL) else {}
    wl.setdefault("skills", {})[SID] = NAME
    json.dump(wl, open(WL, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("✅ 白名单标签(热读层): %s = %s (共 %d 条)" % (SID, NAME, len(wl["skills"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
