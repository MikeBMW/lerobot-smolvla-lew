#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""register_lissa_insert.py — 注册 L2「里萨如力控插入」技能 (2026-09-20, 老倪现场)

用法:
  python3 tools/register_lissa_insert.py [示教点名=slot1] [技能名=里萨如力控插入] [力N=6]

口径来源: **产线原有配方** (只读抄参数, 产线代码一行未改)
  resource/config/sr5_guangmokuai_400gAOI-BL/state_machines/抓取放置/motion/尝试插入第一次.yaml
  → GetTaughtPose(insert_pose) → PoseTranslateLocalOffset([0,0,-0.06] 到插槽口) → MoveSequence(到插槽口, 再直线到 insert_pose)
    → LissajousForceSearch(frame_type=3 工具系 · plane=0 XY · load 1.51kg · K · vmax · desired_force=[0,0,6,0,0,0]
                           · Lissajous 6/3Hz + 4/2Hz · calibrate_force_sensor=true · timeout_sec 2.0
                           · 盒 ±10mm 以当前位姿为原点 · search_box_timeout_sec 8.0)
  期望力: 第一次 6N / 第二次 8N (state_machine.yaml: 沿工具 Z 压)。

安全口径:
  · 全程**不发夹爪指令**(不松光模块) · 力控由驱动执行, 本机只发起服务并看真实回执
  · 守卫: z_floor=该槽位点(不得压过) · 直线 ≤300mm(只允许在槽位附近插) · 限速 30
  · 服务返回 success=False 一律中止并报原文(如 tool1/wobj0 坐标系不存在 → FORCE_CONTROL_CLEANUP_FAILED)
"""
import json
import os
import shutil
import sys
import time

REPO = "/home/ubuntu/lerobot-smolvla-lew"
REG = os.path.join(REPO, "data/skills/l2_atomic/registry.json")
PTS = os.path.join(REPO, "data/skills/l2_atomic/taught_points.json")

# ── 产线配方 (只读抄, 未改) ─────────────────────────────────────────────
PROD_LOAD = [1.51, 0.01617, 0.01289, 0.03117, 0.0, 0.0, 0.0]      # 工具负载: 质量kg + 质心xyz
PROD_K = [6000.0, 6000.0, 0.0, 300.0, 300.0, 100.0]               # 笛卡尔刚度
PROD_VMAX = [0.1, 0.1, 0.01, 5.0, 5.0, 5.0]                       # 笛卡尔限速
RETRACT_MM = 60.0                                                 # 插槽口 = 插入位沿工具 Z 退 60mm (第一次)


def _svc_step(force, stage=3):
    return {"stage": stage, "op": "service", "srv": "/lissajous_force_search",
            "type": "interfaces/srv/LissajousForceSearch", "timeout_s": 60, "dwell_s": 0.5,
            "note": "阶段%d 里萨如力控搜索插入(%.0fN)" % (stage, force),
            "args": {
                "frame_type": 3,                                   # 工具坐标系
                "plane": 0,                                        # XY 平面李萨如抖动
                "load": PROD_LOAD,
                "cartesian_stiffness": PROD_K,
                "cartesian_max_vel": PROD_VMAX,
                "cartesian_desired_force": [0.0, 0.0, force, 0.0, 0.0, 0.0],   # 沿工具 Z 压
                "amplify_one": 6.0, "frequency_one": 3.0,
                "amplify_two": 4.0, "frequency_two": 2.0, "phase_diff": 0.0,
                "calibrate_force_sensor": True, "force_settle_sec": 0.1,
                "timeout_sec": 2.0,
                "use_current_pose_as_box_origin": True,             # 搜索盒原点=当前位置(插槽口/插入位)
                "search_box": [-0.01, 0.01, -0.01, 0.01, -0.01, 0.01],   # ±10mm 盒(min/max 对)
                "search_box_is_inside": True, "search_box_timeout_sec": 8.0,
            }}


def build(name, pt, force=6.0):
    return {
        "id": "L2.lissa_insert",
        "name": name,
        "icon": "🔌",
        "ros": "line_abs",
        "quat": "taught",
        "point": pt,
        "point_locked": True,
        "speed_max": 30,
        "param": {},
        "guard": {"max_lin_mm": 300, "z_floor_point": pt, "z_floor_offset_mm": 0},
        "steps": [
            {"stage": 1, "to": pt, "local_mm": [0.0, 0.0, -RETRACT_MM], "needs_unlock": True,
             "note": "阶段1 沿模块轴向退 60mm 到插槽口(⚠️ 会拔出模块: 必须先解锁)", "guard": {"dz_down_limit_mm": 400},
             "tol_mm": 1.0, "timeout_s": 90, "dwell_s": 1.0},
            {"stage": 2, "to": pt, "local_mm": [0.0, 0.0, 0.0],
             "note": "阶段2 直线推进到插入位", "guard": {"dz_down_limit_mm": 40},
             "tol_mm": 0.5, "timeout_s": 90, "dwell_s": 1.0},
            _svc_step(force, 3),
        ],
        "contact_guard": "力控插入只靠驱动的 cartesian_desired_force(本机不下压); 若现场见插入不到位, "
                         "先看服务回执原文, 再考虑改用 8N(产线第二次档), 不改判据硬说成功",
        "note": "【%s · 里萨如力控插入】配方**只读抄自产线** 尝试插入第一次.yaml: "
                "沿工具 Z 退 60mm 到插槽口 → 直线推进到插入位(%s 示教点) → 调 /lissajous_force_search"
                "(工具系 · XY 平面 · %.0fN 沿工具 Z · 李萨如 6mm/3Hz + 4mm/2Hz · 盒 ±10mm/8s · 到位前自动标定力传感器)。"
                "全程不发夹爪指令。服务回执 success=False 即中止并报原文。"
                "已到槽口只想做力控那一段 → 用同源技能 L2.lissa_search(同一份配方, 只调服务)。"
                % (name, pt, force),
    }


def build_search_only(pt, force=6.0):
    """只跑力控搜索那一段 (人工已把模块摆到槽口时用) —— 与三段技能**同一份配方**(共用 _svc_step)。"""
    return {
        "id": "L2.lissa_search",
        "name": "里萨如力控插入·只搜索",
        "icon": "🔍",
        "ros": "line_abs",
        "quat": "taught",
        "point": pt,
        "point_locked": True,
        "speed_max": 30,
        "param": {},
        "guard": {"max_lin_mm": 300, "z_floor_point": pt, "z_floor_offset_mm": 0},
        "steps": [_svc_step(force, 1)],
        "contact_guard": "只调力控服务, 本机不下发任何运动; 回执 success=False 即中止不重发",
        "note": "【里萨如力控插入·只搜索】人工已把光模块摆到插槽口后, 只执行产线的 /lissajous_force_search"
                "(配方与 L2.lissa_insert 同一份: 工具系 · XY · %.0fN 沿工具 Z · 李萨如 6mm/3Hz+4mm/2Hz · "
                "盒 ±10mm 原点=当前位姿/8s · 自动标定力传感器)。点 %s 仅用于守卫(z_floor/锁点)。" % (force, pt),
    }


def main():
    pt = sys.argv[1] if len(sys.argv) > 1 else "slot1"
    nm = sys.argv[2] if len(sys.argv) > 2 else "里萨如力控插入"
    force = float(sys.argv[3]) if len(sys.argv) > 3 else 6.0
    pts = json.load(open(PTS, encoding="utf-8"))["points"]
    if pt not in pts:
        print("❌ 点位 %s 还没录" % pt)
        return 1
    reg = json.load(open(REG, encoding="utf-8"))
    bak = "/tmp/registry.json.prelissa_%d" % time.time()
    shutil.copy2(REG, bak)
    made = []
    for sk in (build(nm, pt, force), build_search_only(pt, force)):
        ids = [s["id"] for s in reg["skills"]]
        if sk["id"] in ids:
            reg["skills"][ids.index(sk["id"])] = sk
            act = "覆盖更新"
        else:
            at = max(i for i, x in enumerate(reg["skills"]) if x["id"].startswith("L2.slot")) + 1
            reg["skills"].insert(at, sk)
            act = "新增"
        made.append((act, sk["id"], sk["name"]))
    json.dump(reg, open(REG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    allsk = json.load(open(REG, encoding="utf-8"))["skills"]
    chk = [s for s in allsk if s["id"] == "L2.lissa_insert"][0]
    chk2 = [s for s in allsk if s["id"] == "L2.lissa_search"][0]
    for c in (chk, chk2):
        svc = [s for s in c["steps"] if s.get("op") == "service"]
        assert len(svc) == 1 and svc[0]["srv"] == "/lissajous_force_search", "%s 力控服务步不对" % c["id"]
        assert svc[0]["args"]["cartesian_desired_force"][2] == force, "%s 期望力不符" % c["id"]
        assert not any("grip" in json.dumps(s, ensure_ascii=False) for s in c["steps"]), "%s 夹爪步骤混入" % c["id"]
    assert chk["steps"][0].get("needs_unlock") is True, "三段技能的拔出段没加解锁守卫"
    assert len(chk["steps"]) == 3 and len(chk2["steps"]) == 1, "阶段数不对"
    p = pts[pt]["pos"]
    for act, sid, sname in made:
        print("✅ %s %s「%s」" % (act, sid, sname))
    print("   → 技能数 %d · 点 %s=(%.7f, %.7f, %.7f)" % (len(allsk), pt, p[0], p[1], p[2]))
    print("   L2.lissa_insert: 退60mm(⚠️需解锁) → 推进插入位 → 力控 %.0fN" % force)
    print("   L2.lissa_search: 只调力控 %.0fN (人工已把模块摆到槽口时用)" % force)
    print("   守卫 %s · 限速 %s · 锁点 %s · 备份 %s" % (chk["guard"], chk["speed_max"], chk["point_locked"], bak))
    print("   配方来源: 产线 尝试插入第一次.yaml (只读抄, 产线代码未改)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
