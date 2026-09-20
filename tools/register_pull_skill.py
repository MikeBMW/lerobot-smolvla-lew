#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""register_pull_skill.py — 注册 L2「解锁+拔出」技能 (2026-09-20 老倪现场)

用法:  python3 tools/register_pull_skill.py [示教点名=insert_pose] [下垂补偿mm=3] [技能名=解锁并拔出]

机理 (老倪现场 + 产线只读口径):
  · 夹爪**后方有钩子**: 松开夹爪 → 沿模块轴向**退一点**(钩子钩住后面绿色环) → 合爪夹住 → 再沿轴退把模块拉出。
  · 产线对应实现 (只读抄):
      暂时松开.yaml    : 夹爪 pos=1000 speed=100 force=50 acc=100 (松开释放模块)
      移动到治具插槽.yaml: 到拔出位后 MoveLine 到 pull_pose+local(0,0,-0.015)   ← 退 15mm = 钩子咬合行程
      拔出.yaml        : 合爪 pos=0 speed=100 force=30 (+ PIM PULL_SUCCESS)     ← 夹住绿色环
      AOI_1.yaml 首段  : 沿工具轴退 local[-0.002,0,-0.12] = 120mm             ← 真正把模块拔出
  · 老倪 2026-09-20 现场补充: 松开后模块后半截受重力**下垂约 3mm** → 抓之前先垂直下移补偿。

安全口径:
  · 本技能**就是**解锁+拔出流程, 所以不做 needs_unlock 拦截; 但阶段2(钩环)与阶段4(拔出)都沿工具轴外拉,
    仍受 max_lin_mm / z_floor 守卫; 建议现场逐段跑: {"stages":[1]} → [2] → [3] → [4]
  · 每步回执都看真值: 夹爪 curr_pos (空爪≈21 / 夹住模块≈185) —— 夹空要停, 不许"说成功了"
"""
import json
import os
import shutil
import sys
import time

REPO = "/home/ubuntu/lerobot-smolvla-lew"
REG = os.path.join(REPO, "data/skills/l2_atomic/registry.json")
PTS = os.path.join(REPO, "data/skills/l2_atomic/taught_points.json")

HOOK_MM = -15.0        # 钩子咬合行程 (产线 pull_pose → pull_pose_1 = local(0,0,-0.015))
PULL_MM = -120.0       # 拔出直线 (产线 AOI_1 local[-0.002,0,-0.12])


def build(pt, droop_mm=3.0, name="解锁并拔出"):
    # ⚠️ 全程用**相对当前位姿**的步(rel=true): 力控插入会把模块多压进几毫米, 若用"回示教插入位"的绝对点,
    #    第一步就变成把模块往回拽 —— 锁扣还锁着时 = 硬拽(老倪现场明确禁止)。
    steps = [
        {"stage": 1, "rel": True, "dz_mm": -abs(droop_mm),
         "note": "阶段1 垂直下移补偿模块下垂 %.0fmm" % droop_mm,
         "tol_mm": 0.5, "timeout_s": 60, "dwell_s": 0.5},
        {"op": "gripper", "stage": 2, "pos": 1000.0, "speed": 100.0, "force": 50.0, "acc": 100.0,
         "note": "阶段2 松开夹爪(释放模块, 产线 暂时松开.yaml 同参数)", "dwell_s": 0.5},
        {"stage": 3, "rel": True, "local_mm": [0.0, 0.0, HOOK_MM],
         "note": "阶段3 沿模块轴退 %.0fmm 让后方钩子钩住绿色环" % abs(HOOK_MM),
         "guard": {"dz_down_limit_mm": 400}, "tol_mm": 0.5, "timeout_s": 60, "dwell_s": 0.5},
        {"op": "gripper", "stage": 4, "pos": 0.0, "speed": 100.0, "force": 30.0, "acc": 100.0,
         "note": "阶段4 合爪 force30 夹住绿色环(产线 拔出.yaml 同参数)", "dwell_s": 0.5},
        {"stage": 5, "rel": True, "local_mm": [0.0, 0.0, PULL_MM],
         "note": "阶段5 沿模块轴退 %.0fmm 拉出模块(产线 AOI_1 同口径)" % abs(PULL_MM),
         "guard": {"dz_down_limit_mm": 400}, "tol_mm": 1.0, "timeout_s": 120, "dwell_s": 0.5},
    ]
    return {
        "id": "L2.pull_module",
        "name": name,
        "icon": "🪝",
        "ros": "line_abs",
        "quat": "taught",
        "point": pt,
        "point_locked": True,
        "speed_max": 30,
        "param": {},
        "guard": {"max_lin_mm": 200, "z_floor_point": pt, "z_floor_offset_mm": -10},
        "steps": steps,
        "contact_guard": "夹爪回执是唯一真值: 空爪≈21 / 夹住模块≈185; 夹空或 curr_pos 异常一律停手人工确认 —— "
                         "不许用'已下发'当成功。逐段跑 {\"stages\":[N]} 更稳。",
        "note": "【%s · 解锁并拔出】机理=夹爪后方钩子(老倪现场): 松开 → 沿轴退 %.0fmm 钩住**绿色环** → "
                "合爪 force30 夹住 → 沿轴退 %.0fmm 拉出。参数只读抄产线(暂时松开/移动到治具插槽/拔出/AOI_1)。"
                "阶段1 垂直下移 %.0fmm 补偿模块后半截重力下垂。"
                "每段可单独跑: {\"skill\":\"L2.pull_module\",\"stages\":[3]}。"
                % (name, abs(HOOK_MM), abs(PULL_MM), droop_mm),
    }


def main():
    pt = sys.argv[1] if len(sys.argv) > 1 else "insert_pose"
    droop = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0
    nm = sys.argv[3] if len(sys.argv) > 3 else "解锁并拔出"
    pts = json.load(open(PTS, encoding="utf-8"))["points"]
    if pt not in pts:
        print("❌ 点位 %s 还没录" % pt)
        return 1
    reg = json.load(open(REG, encoding="utf-8"))
    ids = [s["id"] for s in reg["skills"]]
    sk = build(pt, droop, nm)
    bak = "/tmp/registry.json.prepull_%d" % time.time()
    shutil.copy2(REG, bak)
    if "L2.pull_module" in ids:
        reg["skills"][ids.index("L2.pull_module")] = sk
        act = "覆盖更新"
    else:
        at = max(i for i, x in enumerate(reg["skills"]) if x["id"].startswith("L2.lissa")) + 1
        reg["skills"].insert(at, sk)
        act = "新增"
    json.dump(reg, open(REG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    chk = [s for s in json.load(open(REG, encoding="utf-8"))["skills"] if s["id"] == "L2.pull_module"][0]
    assert len(chk["steps"]) == 5 and chk["steps"][3]["pos"] == 0.0 and chk["steps"][3]["force"] == 30.0, "阶段定义不符"
    assert abs(chk["steps"][4]["local_mm"][2] + 120.0) < 1e-9, "拔出量不符"
    assert chk["steps"][2]["local_mm"][2] == -15.0, "钩环行程不符"
    print("✅ %s L2.pull_module「%s」→ 技能数 %d · 点 %s" % (act, chk["name"], len(reg["skills"]), pt))
    print("   1 垂直下移 %.0fmm(下垂补偿) → 2 松开夹爪(pos1000/f50) → 3 沿轴退15mm(钩绿环) "
          "→ 4 合爪 f30(夹住环) → 5 沿轴退120mm(拉出)" % droop)
    print("   守卫 %s · 限速 %s · 备份 %s" % (chk["guard"], chk["speed_max"], bak))
    return 0


if __name__ == "__main__":
    sys.exit(main())
