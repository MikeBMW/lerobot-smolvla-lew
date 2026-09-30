#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把"前→上→后→下 × N 圈"固化成 L2 可复用技能（多阶段 steps，逐阶段真值等到位）
依赖 make_abs_path.py 先生成路点 <prefix>_p1..p4
用法: python tools/make_loop_skill.py --prefix afx50 --d 50 --cycles 10 --speed 50
"""
import argparse
import json
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PTS = os.path.join(REPO, "data/skills/l2_atomic/taught_points.json")
REG = os.path.join(REPO, "data/skills/l2_atomic/registry.json")

ap = argparse.ArgumentParser()
ap.add_argument("--prefix", default="afx50")
ap.add_argument("--d", type=float, default=50.0)
ap.add_argument("--cycles", type=int, default=10)
ap.add_argument("--speed", type=float, default=50.0)
ap.add_argument("--name", default="", help="自定义技能名(中文，如 正方形10厘米)")
ap.add_argument("--dry", action="store_true")
A = ap.parse_args()

PFX, D, CY, SP = A.prefix, A.d, A.cycles, A.speed
SEQ = [("p1", "前 +X"), ("p2", "上 +Z"), ("p3", "后 -X"), ("p4", "下 -Z")]
SID = "L2.loop_fubd%d_x%d" % (int(D), CY)


def main():
    tp = json.load(open(PTS, encoding="utf-8"))
    miss = [k for k in (PFX + "_p%d" % i for i in (1, 2, 3, 4)) if k not in tp.get("points", {})]
    if miss:
        print("  ❌ 路点缺失: %s —— 先跑 make_abs_path.py --d %g --prefix %s" % (miss, D, PFX))
        return

    steps = []
    n = 0
    for c in range(1, CY + 1):
        for key, lab in SEQ:
            n += 1
            steps.append({
                "stage": n,
                "to": PFX + "_" + key,
                "dz_mm": 0,
                "tol_mm": 0.5,
                "timeout_s": 45,
                "dwell_s": 0.3,
                "guard": {"dz_down_limit_mm": D + 10},
                "note": "圈%d 第%d步 %s" % (c, n, lab),
            })

    sk = {
        "id": SID,
        "name": (A.name + " (%.0fcm·前上后下×%d·%.0fmm/s)" % (D / 10, CY, SP * 0.100)) if A.name else
                ("🔁 %.0fcm 前上后下 ×%d (%.1fmm/s)" % (D / 10, CY, SP * 0.100)),
        "icon": "🔁",
        "ros": "line_abs",
        "quat": "taught",
        # ⚠️ 多路点循环**不能**设 point_locked/point —— daemon 的 _point_name() 里
        #    技能级锁点优先级高于阶段 to，会把 40 段全锁到同一个点(臂不动)。
        "speed_max": SP + 5,
        "param": {},
        "guard": {"max_lin_mm": D * 2, "dz_down_limit_mm": D + 10},
        "steps": steps,
        "note": ("【%.0fcm 正方形循环 · 前→上→后→下 ×%d 圈】绝对位姿路点(由 make_abs_path.py 从真机 TCP 采样算出) "
                 "→ 无 line_rel 累积漂移(实测同条件 line_rel 漂 24.2mm)。每阶段下发后用真值等到位(tol 0.5mm)再进下一段, "
                 "到点即停不重发。限速上限 %.0f。%d 段 = %.0fcm×%d 圈。"
                 % (D / 10, CY, SP + 5, len(steps), D / 10, CY)),
    }

    print("  技能: %s · %s" % (SID, sk["name"]))
    print("  段数: %d (%d 圈 × 4 步) · 每段 %.0fmm · 限速 %s" % (len(steps), CY, D, SP))
    print("  前 2 段:", json.dumps(steps[:2], ensure_ascii=False))
    if A.dry:
        print("\n  --dry: 不写文件")
        return

    rg = json.load(open(REG, encoding="utf-8"))
    have = [x for x in rg["skills"] if x["id"] == SID]
    if have:
        have[0].pop("point_locked", None)      # 多路点必须清掉这两个键，否则 40 段全锁一点
        have[0].pop("point", None)
        have[0].update(sk)
        print("  = %s 已存在 → 已更新(并清掉 point_locked/point)" % SID)
    else:
        rg["skills"].append(sk)
        print("  + %s 新增" % SID)
    json.dump(rg, open(REG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n  ✅ 已保存。跑法: echo '{\"skill\":\"%s\",\"speed\":%.0f}' > ~/zmax_data/l2_cmd.fifo" % (SID, SP))


if __name__ == "__main__":
    main()
