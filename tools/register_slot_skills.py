#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📍 号位技能注册 (1~7 号位) —— 幂等。

2026-09-30 老倪: 「http://…/station 这个页面的左下角, 也没有什么功能;
  增加技能点: 1号位, 2号位, 一直到7号位; 有记录的点就是绿色按钮, 没有记录的点就是灰色按钮」

口径:
  · 号位 = 示教点库里的 ``slotN``(``data/skills/l2_atomic/taught_points.json``)。
  · 技能只是给点位一个"可下发的壳" —— 目标点真值仍在示教点库 + 执行器 ``point_locked`` 收口,
    页面/接口都改不了点位。
  · 没有示教记录的号位 ⇒ 调用会被执行器**干净拒发** ``点位 slotN 不在点位库``
    (不是崩, 也不是瞎走); 页面上的灰按钮根本不会下发, 这条只是兜底。
形态: 与现场已验证的 ``L2.slot1/2/3`` 同规格 —— 阶段1 到该点 base+Z 30mm 正上方 → 真值等到位 →
  阶段2 竖直下降 30mm 回该点; 全程不碰夹爪; 守卫 ``z_floor_point``(绝不低于该点) + 阶段级
  ``dz_down_limit_mm``; 限速 ``speed_max=150``(≈15mm/s, 生产标定值)。
  **已有的号位技能一律不动**(现场可能手调过守卫/点位)。

用法: python3 tools/register_slot_skills.py            # 只新增缺的号位
      python3 tools/register_slot_skills.py --dry      # 只看要新增哪些
"""
import argparse
import json
import os
import shutil
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = os.path.join(REPO, "data", "skills", "l2_atomic", "registry.json")
SLOTS = [1, 2, 3, 4, 5, 6, 7]


def build(n: int) -> dict:
    """一个号位技能(与 L2.slot3 同规格, 只换点名/文案)。"""
    p = "slot%d" % n
    return {
        "id": "L2." + p,
        "name": "%d号位(到位即停)" % n,
        "icon": "🅰️",
        "ros": "line_abs",
        "quat": "taught",
        "point": p,
        "point_locked": True,
        "speed_max": 150,
        "param": {},
        "guard": {"max_lin_mm": 500, "z_floor_point": p, "z_floor_offset_mm": 0},
        "steps": [
            {"stage": 1, "to": p, "dz_mm": 30.0, "note": "阶段1 到%d号位正上方" % n,
             "guard": {"dz_down_limit_mm": 400}, "tol_mm": 1.0, "timeout_s": 60, "dwell_s": 1.5},
            {"stage": 2, "to": p, "dz_mm": 0, "note": "阶段2 下降到%d号位(到位即停, 禁下压)" % n,
             "guard": {"dz_down_limit_mm": 40}, "tol_mm": 0.5, "timeout_s": 40, "dwell_s": 1.0},
        ],
        "contact_guard": ("阶段2 到位即停、禁下压; 若现场见触底/顶住, 把 %s 点抬高 3~5mm 重录 —— "
                          "不改判据硬说成功" % p),
        "note": ("%d号位收口技能(同 slot1/2/3 形态): 阶段1 到该点 base+Z 30mm 正上方 → 真值等到位 → "
                 "阶段2 竖直下降 30mm 回该点; 点位真值在示教点库 %s(taught_points.json), 位置+姿态锁定"
                 "(point_locked); 未示教时调用被干净拒发「点位 %s 不在点位库」。" % (n, p, p)),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="只打印将要新增的技能, 不落盘")
    a = ap.parse_args()

    with open(REG, encoding="utf-8") as f:
        reg = json.load(f)
    have = {str(s.get("id")) for s in reg["skills"]}

    pts = {}
    try:
        with open(os.path.join(REPO, "data/skills/l2_atomic/taught_points.json"), encoding="utf-8") as f:
            pts = json.load(f).get("points", {})
    except Exception as e:                                                    # noqa: BLE001
        print("⚠️ 示教点库读取失败(只影响下面的记录状态提示): %s" % e)

    added, kept = [], []
    for n in SLOTS:
        sid, p = "L2.slot%d" % n, "slot%d" % n
        if sid in have:
            kept.append(sid)
            continue
        added.append(sid)
        if not a.dry:
            reg["skills"].append(build(n))

    print("注册表: %s" % REG)
    for sid in added:
        n = int(sid.rsplit("slot", 1)[1])
        print("  ➕ %s (%d号位) · 示教记录: %s" % (sid, n, "有" if ("slot%d" % n) in pts else "无(灰色按钮)"))
    print("  跳过已有(未动): %s" % (", ".join(kept) if kept else "无"))
    if a.dry:
        print("(--dry: 未落盘)")
        return
    if added:
        bak = "/tmp/registry.json.preslot_%s" % time.strftime("%m%d_%H%M%S")
        shutil.copy(REG, bak)
        with open(REG, "w", encoding="utf-8") as f:
            json.dump(reg, f, ensure_ascii=False, indent=1)
        print("  备份: %s" % bak)
    print("总技能数: %d" % len(reg["skills"]))


if __name__ == "__main__":
    main()
