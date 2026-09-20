#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""register_slot_skill.py — 把「回槽位」两阶段技能写进 L2 原子技能注册表 (幂等, 只加法)

用法:
  python3 tools/register_slot_skill.py <技能名> <示教点名> <技能id> [clearance_mm=30]

例:
  python3 tools/register_slot_skill.py 一号位 slot1 L2.slot1
  python3 tools/register_slot_skill.py 二号位 slot2 L2.slot2

技能口径 (2026-09-20 老倪现场指令, 一号位/二号位通用):
  · 技能名 = 老倪叫的名字 (一号位/二号位…); 分两个阶段: ① 到槽位正上方 ② 下降到槽位
  · 全程不松光模块 → 定义里**没有 gripper 步骤** (执行层不自己发明动作)
  · 目标点 = 抓持光模块那一刻的槽位位姿 (taught_points.json, 只读订阅录的绝对点)
  · quat=taught → 位置+姿态都回示教点 ⇒ 两阶段都是纯竖直平移、不带旋转
  · 守卫(几何口径): z_floor=目标 z 不得低于该槽位点(绝不下压进夹具) · 直线>500mm 拒发
    · 阶段1 转移段允许大下降(400 只防跑飞) · 阶段2 插入段限 40mm · 限速 30
"""
import json
import os
import shutil
import sys
import time

REPO = "/home/ubuntu/lerobot-smolvla-lew"
REG = os.path.join(REPO, "data/skills/l2_atomic/registry.json")
PTS = os.path.join(REPO, "data/skills/l2_atomic/taught_points.json")
ICONS = ["🅰️", "🅱️", "🆑", "🅳", "🅴", "🅵", "🅶", "🅷"]


def build(name, pt, sid, clearance=30.0, icon=None):
    return {
        "id": sid,
        "name": name,
        "icon": icon or "🅰️",
        "ros": "line_abs",
        "quat": "taught",
        "point": pt,
        "point_locked": True,
        "speed_max": 30,
        "param": {},
        "guard": {"max_lin_mm": 500, "z_floor_point": pt, "z_floor_offset_mm": 0},
        "steps": [
            {"stage": 1, "to": pt, "dz_mm": clearance, "note": "阶段1 到%s正上方" % name,
             "guard": {"dz_down_limit_mm": 400}, "tol_mm": 1.0, "timeout_s": 60, "dwell_s": 1.5},
            {"stage": 2, "to": pt, "dz_mm": 0, "note": "阶段2 下降到%s(到位即停, 禁下压)" % name,
             "guard": {"dz_down_limit_mm": 40}, "tol_mm": 0.5, "timeout_s": 40, "dwell_s": 1.0},
        ],
        "contact_guard": "阶段2 到位即停、禁下压; 若现场见触底/顶住, 把 %s 点抬高 3~5mm 重录 —— 不改判据硬说成功" % pt,
        "note": "【%s · 两阶段回槽位】人机在环示教(只读订阅 /robot/tcp_pose 录点): %s=抓持光模块那一刻的槽位位姿。"
                "阶段1 = 该点 base+Z 抬 %.0fmm(工具X轴≈base+Z → 纯竖直平移、不带旋转) → 真值等到位后 "
                "阶段2 = 竖直下 %.0fmm 回槽位。全程不碰夹爪(定义里没有 gripper 步骤)。"
                "守卫: z_floor=%s(绝不低于该点) · 直线>500mm 拒发 · 限速 30。" % (name, pt, clearance, clearance, pt),
    }


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    name, pt, sid = sys.argv[1], sys.argv[2], sys.argv[3]
    clr = float(sys.argv[4]) if len(sys.argv) > 4 else 30.0
    try:
        pts = json.load(open(PTS, encoding="utf-8"))["points"]
    except Exception as e:
        print("❌ 点位库读不到: %s" % e)
        return 1
    if pt not in pts:
        print("❌ 点位 %s 还没录 (先录点: tools/record_point_watch.py)" % pt)
        return 1
    reg = json.load(open(REG, encoding="utf-8"))
    ids = [s["id"] for s in reg["skills"]]
    n_slot = len([i for i in ids if i.startswith("L2.slot")])
    icon = ICONS[n_slot] if n_slot < len(ICONS) else "🅾️"
    sk = build(name, pt, sid, clr, icon)
    bak = "/tmp/registry.json.preslot_%d" % time.time()
    shutil.copy2(REG, bak)
    if sid in ids:                       # 已存在 → 覆盖(保持原 icon)
        sk["icon"] = reg["skills"][ids.index(sid)].get("icon", icon)
        reg["skills"][ids.index(sid)] = sk
        act = "覆盖更新"
    else:
        at = max([i for i, x in enumerate(reg["skills"]) if x["id"].startswith("L2.slot")] + [ids.index("L2.goto_aoi_gold")]) + 1
        reg["skills"].insert(at, sk)
        act = "新增"
    json.dump(reg, open(REG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    chk = [s for s in json.load(open(REG, encoding="utf-8"))["skills"] if s["id"] == sid][0]
    assert chk["steps"][0]["dz_mm"] == clr and chk["steps"][1]["dz_mm"] == 0, "阶段定义不符"
    assert not any("grip" in json.dumps(s) for s in chk["steps"]), "夹爪步骤混进来了(会松爪)"
    assert chk["guard"]["z_floor_point"] == pt, "z_floor 未指向本槽位点"
    p = pts[pt]["pos"]
    print("✅ %s %s「%s」→ 技能数 %d · 点 %s=(%.7f, %.7f, %.7f)"
          % (act, sid, chk["name"], len(reg["skills"]), pt, p[0], p[1], p[2]))
    print("   阶段1 %s (dz=%+.0fmm, 目标 z=%.7f)" % (chk["steps"][0]["note"], clr, p[2] + clr / 1000.0))
    print("   阶段2 %s (dz=%+.0fmm, 目标 z=%.7f)" % (chk["steps"][1]["note"], 0, p[2]))
    print("   守卫 %s · 限速 %s · 锁点 %s · 容差 %s · 备份 %s"
          % (chk["guard"], chk["speed_max"], chk["point_locked"],
             [s["tol_mm"] for s in chk["steps"]], bak))
    return 0


if __name__ == "__main__":
    sys.exit(main())
