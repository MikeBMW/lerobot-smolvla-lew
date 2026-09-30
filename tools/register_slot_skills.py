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

形态 (2026-09-30 现场定为 **4 段转移**, 逐字依据 老倪: 「要先垂直抬升5厘米, 才能去别的地方。
  要到任何一个位置, 也要先到这个位置的上方, 再垂直下落。」):
    阶段1  **就地垂直抬升 50mm** (rel, XY 不动) —— 抬够才允许去别处;
    阶段2  高位横移到目标点正上方 (目标 z = 点位+200mm ⇒ 横移全程在高处, 不下沉);
    阶段3  竖直下降到点位正上方 30mm;
    阶段4  竖直下降到点位 (到位即停, 禁下压, 下降 ≤40mm 守卫)。
  全程不碰夹爪; 守卫 ``z_floor_point``(绝不低于该点) 保留。限速 ``speed_max=150``(≈15mm/s, 生产标定值)。
  旧形态(2 段: 直接斜线走到正上方 30mm → 竖直落)的毛病: 从相邻号位出发时横移的前半段
  只有槽面以上 2~32mm —— 就是"低空横移"。``--four-stage`` 把已有号位技能升级成 4 段。

用法: python3 tools/register_slot_skills.py                 # 只新增缺的号位
      python3 tools/register_slot_skills.py --dry           # 只看要新增哪些
      python3 tools/register_slot_skills.py --four-stage    # 把已有号位升级成 4 段(备份后重写 steps)
      python3 tools/register_slot_skills.py --max-lin-mm 1500
"""
import argparse
import json
import os
import shutil
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = os.path.join(REPO, "data", "skills", "l2_atomic", "registry.json")
SLOTS = [1, 2, 3, 4, 5, 6, 7]
LIFT_MM = 50.0        # 老倪规矩: 去别处前先就地垂直抬 5cm
HIGH_MM = 200.0       # 高位横移高度(相对点位 z)
ABOVE_MM = 30.0       # 目标点正上方最终接近高度


def steps4(n: int) -> list:
    """4 段转移计划(现场规矩): 就地抬 50 → 高位横移 → 正上方 30 → 竖直落差。"""
    p = "slot%d" % n
    return [
        {"stage": 1, "rel": True, "dz_mm": LIFT_MM,
         "note": "阶段1 就地垂直抬升 %gmm(现场规矩: 抬够才能去别的地方)" % LIFT_MM,
         "guard": {"dz_down_limit_mm": 400}, "tol_mm": 1.0, "timeout_s": 60, "dwell_s": 1.5},
        {"stage": 2, "to": p, "dz_mm": HIGH_MM,
         "note": "阶段2 高位横移到%d号位正上方(目标 z=点位+%gmm ⇒ 全程在高处, 不下沉)" % (n, HIGH_MM),
         "guard": {"dz_down_limit_mm": 400}, "tol_mm": 1.0, "timeout_s": 120, "dwell_s": 1.5},
        {"stage": 3, "to": p, "dz_mm": ABOVE_MM,
         "note": "阶段3 竖直下降到%d号位正上方 %gmm" % (n, ABOVE_MM),
         "guard": {"dz_down_limit_mm": 400}, "tol_mm": 1.0, "timeout_s": 60, "dwell_s": 1.0},
        {"stage": 4, "to": p, "dz_mm": 0.0,
         "note": "阶段4 竖直下降到%d号位(到位即停, 禁下压)" % n,
         "guard": {"dz_down_limit_mm": 40}, "tol_mm": 0.5, "timeout_s": 40, "dwell_s": 1.0},
    ]


def note4(n: int) -> str:
    p = "slot%d" % n
    return ("%d号位收口技能(4 段转移, 2026-09-30 现场定): 阶段1 就地垂直抬 %gmm → 阶段2 高位横移到该点正上方"
            "(点位+%gmm) → 阶段3 竖直降到正上方 %gmm → 阶段4 竖直落到该点; 点位真值在示教点库 %s"
            "(taught_points.json), 位置+姿态锁定(point_locked); 未示教时调用被干净拒发「点位 %s 不在点位库」。"
            % (n, LIFT_MM, HIGH_MM, ABOVE_MM, p, p))


def build(n: int) -> dict:
    """一个号位技能(只换点名/文案)。"""
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
        "steps": steps4(n),
        "contact_guard": ("阶段4 到位即停、禁下压; 若现场见触底/顶住, 把 %s 点抬高 3~5mm 重录 —— "
                          "不改判据硬说成功" % p),
        "note": note4(n),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="只打印将要新增/修改的技能, 不落盘")
    ap.add_argument("--four-stage", action="store_true",
                    help="把**已有**号位技能的 steps 升级成 4 段(就地抬 50 → 高位横移 → 正上方 30 → 竖直落差); "
                         "依据 老倪 2026-09-30 现场规矩「要先垂直抬升5厘米, 才能去别的地方」")
    ap.add_argument("--max-lin-mm", type=float, default=None,
                    help="同时把**已有**号位技能的 guard.max_lin_mm 改到这个值(如 1500 = 整机工作范围); "
                         "2026-09-30 老倪: 「1号位, 没有回去, 不动, 这个技能怎么回事」—— 真因就是这条 500mm 距离上限 "
                         "(臂停在 (0.6451,-0.0126,0.2689), 1号位 527mm ⇒ 每次都被拒, 现场看着像技能坏了)。"
                         "这条是**距离可用性上限**, 不是防撞红线: 防撞靠 z_floor_point(绝不低于该点) + "
                         "阶段级 dz_down_limit_mm(下降≤40mm) + 到位即停禁下压 —— 那三条一律保留。")
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
        sid = "L2.slot%d" % n
        if sid in have:
            kept.append(sid)
            continue
        added.append(sid)
        if not a.dry:
            reg["skills"].append(build(n))

    # 🪜 4 段升级: 只重写执行顺序(steps), 点位真值/守卫/限速一律不动。
    up = []
    if a.four_stage and not a.dry:
        for s in reg["skills"]:
            sid = str(s.get("id", ""))
            if not sid.startswith("L2.slot"):
                continue
            n = int(sid.rsplit("slot", 1)[1])
            old_n = len(s.get("steps") or [])
            s["steps"] = steps4(n)
            s["note"] = note4(n)
            s["contact_guard"] = ("阶段4 到位即停、禁下压; 若现场见触底/顶住, 把 slot%d 点抬高 3~5mm 重录 —— "
                                  "不改判据硬说成功" % n)
            up.append("%s 阶段 %d → 4" % (sid, old_n))

    # 🔝 距离上限: 只改这条(可用性), 防撞三件套(z_floor / dz_down_limit / 到位即停)一律不动。
    lin_changed = []
    if a.max_lin_mm is not None and not a.dry:
        for s in reg["skills"]:
            if not str(s.get("id", "")).startswith("L2.slot"):
                continue
            g = s.setdefault("guard", {})
            old = g.get("max_lin_mm")
            if old != a.max_lin_mm:
                g["max_lin_mm"] = a.max_lin_mm
                lin_changed.append("%s %s→%s" % (s["id"], old, a.max_lin_mm))
            s["note"] = (str(s.get("note", "")).rstrip("。 ") +
                         " · 2026-09-30 老倪现场: 距离上限 500→%g(臂停位离 1 号位 527mm 被反复拒; "
                         "防撞仍靠 z_floor+下降≤40mm+到位即停)" % a.max_lin_mm).strip(" ·")

    print("注册表: %s" % REG)
    for sid in added:
        n = int(sid.rsplit("slot", 1)[1])
        print("  ➕ %s (%d号位) · 示教记录: %s" % (sid, n, "有" if ("slot%d" % n) in pts else "无(灰色按钮)"))
    print("  跳过已有(未动): %s" % (", ".join(kept) if kept else "无"))
    for _u in up:
        print("  🪜 4 段升级: %s" % _u)
    for _c in lin_changed:
        print("  🔝 距离上限: %s" % _c)
    if a.dry:
        print("(--dry: 未落盘)")
        return
    if added or lin_changed or up:
        bak = "/tmp/registry.json.preslot_%s" % time.strftime("%m%d_%H%M%S")
        shutil.copy(REG, bak)
        with open(REG, "w", encoding="utf-8") as f:
            json.dump(reg, f, ensure_ascii=False, indent=1)
        print("  备份: %s" % bak)
    print("总技能数: %d" % len(reg["skills"]))


if __name__ == "__main__":
    main()
