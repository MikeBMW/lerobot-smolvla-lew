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
            {"stage": 1, "to": pt, "local_mm": [0.0, 0.0, -RETRACT_MM],
             "note": "阶段1 沿模块轴向退 60mm 到插槽口", "guard": {"dz_down_limit_mm": 400},
             "tol_mm": 1.0, "timeout_s": 90, "dwell_s": 1.0},
            {"stage": 2, "to": pt, "local_mm": [0.0, 0.0, 0.0],
             "note": "阶段2 直线推进到插入位", "guard": {"dz_down_limit_mm": 40},
             "tol_mm": 0.5, "timeout_s": 90, "dwell_s": 1.0},
            {"stage": 3, "op": "service", "srv": "/lissajous_force_search",
             "type": "interfaces/srv/LissajousForceSearch", "timeout_s": 60, "dwell_s": 0.5,
             "note": "阶段3 里萨如力控搜索插入(%.0fN)" % force,
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
             }},
        ],
        "contact_guard": "力控插入只靠驱动的 cartesian_desired_force(本机不下压); 若现场见插入不到位, "
                         "先看服务回执原文, 再考虑改用 8N(产线第二次档), 不改判据硬说成功",
        "note": "【%s · 里萨如力控插入】配方**只读抄自产线** 尝试插入第一次.yaml: "
                "沿工具 Z 退 60mm 到插槽口 → 直线推进到插入位(%s 示教点) → 调 /lissajous_force_search"
                "(工具系 · XY 平面 · 6N 沿工具 Z · 李萨如 6mm/3Hz + 4mm/2Hz · 盒 ±10mm/8s · 到位前自动标定力传感器)。"
                "全程不发夹爪指令。服务回执 success=False 即中止并报原文。"
                "产线原流程还用 8N 做第二次尝试; 要先只送插槽口再纯力控插入(不推到位), 去掉阶段2 即可。" % (name, pt),
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
    ids = [s["id"] for s in reg["skills"]]
    sk = build(nm, pt, force)
    bak = "/tmp/registry.json.prelissa_%d" % time.time()
    shutil.copy2(REG, bak)
    if "L2.lissa_insert" in ids:
        reg["skills"][ids.index("L2.lissa_insert")] = sk
        act = "覆盖更新"
    else:
        at = max(i for i, x in enumerate(reg["skills"]) if x["id"].startswith("L2.slot")) + 1
        reg["skills"].insert(at, sk)
        act = "新增"
    json.dump(reg, open(REG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    chk = [s for s in json.load(open(REG, encoding="utf-8"))["skills"] if s["id"] == "L2.lissa_insert"][0]
    st3 = chk["steps"][2]
    assert st3["op"] == "service" and st3["srv"] == "/lissajous_force_search", "阶段3 不是力控服务"
    assert st3["args"]["cartesian_desired_force"][2] == force, "期望力不符"
    assert "gripper" not in json.dumps(chk, ensure_ascii=False).replace(chk["contact_guard"], ""), "夹爪混进来了"
    p = pts[pt]["pos"]
    print("✅ %s L2.lissa_insert「%s」→ 技能数 %d · 点 %s=(%.7f, %.7f, %.7f)"
          % (act, chk["name"], len(reg["skills"]), pt, p[0], p[1], p[2]))
    print("   阶段1 沿工具 Z 退 %.0fmm 到插槽口   阶段2 直线推进到插入位   阶段3 里萨如力控(%.0fN, 盒±10mm/8s)"
          % (RETRACT_MM, force))
    print("   守卫 %s · 限速 %s · 锁点 %s · 备份 %s" % (chk["guard"], chk["speed_max"], chk["point_locked"], bak))
    print("   配方来源: 产线 尝试插入第一次.yaml (只读抄, 产线代码未改)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
