#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""register_vision_grasp_skill.py — 把「视觉引导抓取」注册进 L2 原子技能表 (幂等, 可重跑)

注册 id: **L2.grasp_vision**
口径 (与前例 L2.slot1/L2.slot2/L2.pull_module 完全一致):
  · ros=line_abs + quat=taught (回示教姿态, 纯平移) + speed_max=30 (练习用低速, 收口在执行层)
  · steps 四段: 到模块正上方 → 下降到抓取位(禁下压) → 合爪 force40 → 抬升 50mm 离槽
  · 点位用**占位名 `slot_vision`**: 由执行器里的**视觉门**在每次执行前解析成 slot1/slot2
    (判据见 tools/vision_grasp_skill.py; 判不出/两路冲突 → 拒发)
  · 守卫沿用: z_floor=该槽(绝不低于示教抓取位) · 直线>500mm 拒发 · 阶段2 下降>40mm 拒发
  · point_locked 保持 false: 允许调用方带 point 覆盖 —— 但视觉门会把 spec.point 改写成判定结果,
    所以**人工也不能把它指到没有模块的槽**(判定说 slot2 就一定去 slot2)

用法: gui-venv311/bin/python tools/register_vision_grasp_skill.py [--dry]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import time

REPO = "/home/ubuntu/lerobot-smolvla-lew"
REG = os.path.join(REPO, "data/skills/l2_atomic/registry.json")
PTS = os.path.join(REPO, "data/skills/l2_atomic/taught_points.json")
SID = "L2.grasp_vision"

ENTRY = {
    "id": SID,
    "name": "视觉引导抓取",
    "icon": "🎯",
    "ros": "line_abs",
    "quat": "taught",
    "point": "slot_vision",
    "point_locked": False,
    "speed_max": 30,
    "vision_gate": {
        "resolver": "vision_grasp_skill.judge_slot",
        "candidates": ["slot1", "slot2"],
        "require": "module_present",
        "fail_closed": True,
        "double_witness": ["yolo_box_bottom_vs_slot_projection", "vertical_edge_column_peak"],
        "note": "执行前跑双路视觉判据决定 slot_vision→slot1/slot2; 判不出/两路冲突/帧不新鲜 → 拒发(宁缺勿假)",
    },
    "param": {},
    "guard": {"max_lin_mm": 500, "z_floor_point": "slot_vision", "z_floor_offset_mm": 0},
    "steps": [
        {"stage": 1, "to": "slot_vision", "dz_mm": 30.0, "note": "阶段1 到模块所在槽正上方(视觉解析)",
         "guard": {"dz_down_limit_mm": 400}, "tol_mm": 1.0, "timeout_s": 60, "dwell_s": 1.5},
        {"stage": 2, "to": "slot_vision", "dz_mm": 0, "note": "阶段2 下降到抓取位(到位即停, 禁下压)",
         "guard": {"dz_down_limit_mm": 40}, "tol_mm": 0.5, "timeout_s": 40, "dwell_s": 1.0},
        {"op": "gripper", "stage": 3, "pos": 0.0, "speed": 100.0, "force": 40.0, "acc": 100.0,
         "note": "阶段3 合爪夹住模块(force40; 回执 curr_pos 应≈185 而非空爪≈21)", "dwell_s": 0.5},
        {"rel": True, "stage": 4, "dz_mm": 50.0, "note": "阶段4 抬升 50mm 离槽(相对当前位姿, 姿态不变)",
         "guard": {"dz_down_limit_mm": 400}, "tol_mm": 1.0, "timeout_s": 60, "dwell_s": 0.5},
    ],
    "contact_guard": "判完成只看真值: 阶段到位看 TCP 真值; 抓没抓到看夹爪回执 curr_pos(空爪≈21 / 夹住模块≈185); "
                     "任一段失败 → 中止剩余段且**绝不重发**",
    "note": "【视觉引导抓取】判位 = 双路独立证据一致才认: ①YOLO peg 框底心 ↔ 槽位示教点手眼投影 "
            "(Δx≤12px ∧ 框底-投影∈[-5,25]px) ②模块竖直带『竖直棱边能量』列剖面峰列归属(≤20px)。"
            "执行 = 槽正上方→下降→合爪 force40→抬升 50mm。视觉门在**执行器内** fail-closed: 解析不到槽位就拒发。"
            "零下发自检/编排: tools/vision_grasp_skill.py (不加 --apply 一律 dry-run)",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="只打印将要写入的条目, 不改文件")
    a = ap.parse_args()
    reg = json.load(open(REG, encoding="utf-8"))
    pts = json.load(open(PTS, encoding="utf-8")).get("points", {})
    miss = [n for n in ENTRY["vision_gate"]["candidates"] if n not in pts]
    if miss:
        print("❌ 点位库缺候选槽位: %s (先示教并写入 taught_points.json)" % miss)
        return 2
    skills = [s for s in reg["skills"] if s.get("id") != SID]
    skills.append(ENTRY)
    reg["skills"] = skills
    print("候选槽位都在点位库: %s" % {n: [round(v, 4) for v in pts[n]["pos"]] for n in ENTRY["vision_gate"]["candidates"]})
    if a.dry:
        print(json.dumps(ENTRY, ensure_ascii=False, indent=1))
        return 0
    bak = REG + ".bak_%s" % time.strftime("%m%d_%H%M%S")
    shutil.copy2(REG, bak)
    with open(REG, "w", encoding="utf-8") as f:
        json.dump(reg, f, ensure_ascii=False, indent=1)
    json.load(open(REG, encoding="utf-8"))                 # 回读校验
    n_l2 = len([s for s in json.load(open(REG, encoding="utf-8"))["skills"] if s["id"].startswith("L2.")])
    print("✅ 已注册 %s · 技能总数 %d (L2.* %d) · 备份 %s" % (SID, len(skills), n_l2, os.path.basename(bak)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
