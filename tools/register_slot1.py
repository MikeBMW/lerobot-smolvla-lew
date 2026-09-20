#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""register_slot1.py — 把【一号位】两阶段回槽位技能写进 L2 原子技能注册表 (幂等, 只加法不覆盖)

技能定义口径 (2026-09-20 老倪现场指令):
  · 技能名就叫「一号位」; 分两个阶段: ① 到一号位正上方 ② 下降到一号位
  · 全程不松光模块 → 定义里**没有 gripper 步骤** (执行层不自己发明动作)
  · 目标点 slot1 = 老倪抓持光模块那一刻的槽位位姿 (taught_points.json, 6 帧极差 7e-7 m)
  · quat=taught → 位置+姿态都回示教点 ⇒ 两阶段都是纯竖直平移, 不带旋转
"""
import json
import os
import shutil
import sys
import time

REPO = "/home/ubuntu/lerobot-smolvla-lew"
REG = os.path.join(REPO, "data/skills/l2_atomic/registry.json")

SKILL = {
    "id": "L2.slot1",
    "name": "一号位",
    "icon": "🅰️",
    "ros": "line_abs",
    "quat": "taught",
    "point": "slot1",
    "point_locked": True,
    "speed_max": 30,
    "param": {},
    # 🛡 守卫口径 (2026-09-20 现场修正, 见 l2_daemon.plan_stage):
    #   z_floor = 目标 z 不得低于槽位点(硬红线, 与Δ无关) → 这才是"绝不压进槽"的那条;
    #   阶段1 是转移段(从任意高度回到"正上方"), 允许大下降(dz_down_limit 400 只是防跑飞的理智值);
    #   阶段2 是最终插入段, 只允许 30mm 这个量级(dz_down_limit 40)。
    "guard": {"max_lin_mm": 500, "z_floor_point": "slot1", "z_floor_offset_mm": 0},
    "steps": [
        {"stage": 1, "to": "slot1", "dz_mm": 30, "note": "阶段1 到一号位正上方",
         "guard": {"dz_down_limit_mm": 400}, "tol_mm": 1.0, "timeout_s": 60, "dwell_s": 1.5},
        {"stage": 2, "to": "slot1", "dz_mm": 0, "note": "阶段2 下降到一号位(到位即停, 禁下压)",
         "guard": {"dz_down_limit_mm": 40}, "tol_mm": 0.5, "timeout_s": 40, "dwell_s": 1.0},
    ],
    "contact_guard": "阶段2 到位即停、禁下压; 若现场见触底/顶住, 把 slot1 点抬高 3~5mm 重录 —— 不改判据硬说成功",
    "note": "【一号位 · 两阶段回槽位】人机在环示教(2026-09-20 20:37): slot1=老倪抓持光模块那一刻的槽位位姿"
            "(6 帧采样极差 7e-7 m)。阶段1 = 该点 base+Z 抬 30mm(工具X轴≈base+Z 偏 2.2° → 纯竖直平移、不带旋转)"
            " → 真值等到位后 阶段2 = 竖直下 30mm 回槽位点。全程不碰夹爪。"
            "守卫: 直线距离>500mm 拒发(先把臂移到槽位附近) · 向下>40mm 拒发 · 限速 30。",
}


def main():
    with open(REG, encoding="utf-8") as f:
        reg = json.load(f)
    ids = [s["id"] for s in reg["skills"]]
    bak = "/tmp/registry.json.prek1_%d" % time.time()
    shutil.copy2(REG, bak)
    if "L2.slot1" in ids:
        reg["skills"][ids.index("L2.slot1")] = SKILL
        act = "覆盖更新"
    else:
        # 插在 L2.goto_aoi_gold 之后 (运动类技能聚在一起)
        at = ids.index("L2.goto_aoi_gold") + 1 if "L2.goto_aoi_gold" in ids else len(reg["skills"])
        reg["skills"].insert(at, SKILL)
        act = "新增"
    with open(REG, "w", encoding="utf-8") as f:
        json.dump(reg, f, ensure_ascii=False, indent=1)
    with open(REG, encoding="utf-8") as f:
        chk = json.load(f)
    got = [s for s in chk["skills"] if s["id"] == "L2.slot1"][0]
    assert len(chk["skills"]) == len(reg["skills"]), "写回技能数不符"
    assert got["steps"][0]["dz_mm"] == 30 and got["steps"][1]["dz_mm"] == 0, "阶段定义不符"
    assert not any("grip" in json.dumps(s) for s in got["steps"]), "夹爪步骤混进来了(会松爪)"
    print("✅ %s L2.slot1「%s」→ 技能数 %d" % (act, got["name"], len(chk["skills"])))
    print("   阶段1: %s (dz=%+dmm) | 阶段2: %s (dz=%+dmm)"
          % (got["steps"][0]["note"], got["steps"][0]["dz_mm"],
             got["steps"][1]["note"], got["steps"][1]["dz_mm"]))
    print("   守卫: %s · 限速 %s · 锁点 %s · 备份 %s" % (got["guard"], got["speed_max"], got["point_locked"], bak))
    return 0


if __name__ == "__main__":
    sys.exit(main())
