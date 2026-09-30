#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
live_plan_segment.py — **同源实时规划段**: 从"当前真机 TCP(实测)"到目标位姿, 出可过闸的分段 + 叠到画面
────────────────────────────────────────────────────────────
老倪 2026-09-29: 「我要开始移动机器人手臂，你要实时显示3D边界框，实时规划轨迹。实时感知和规划结果
                  要叠加到手臂相机的场景。」

为什么这条线敢画到真机画面上(而 MoveIt 那条不敢):
  · 两端都是**真机真值** —— 起点 = 真机当前 TCP(50Hz 真值), 终点 = 示教点/指定目标;
  · 分段只按执行器自己的守卫(单步 ≤50mm、向下 ≤20mm)切, 切出来的中间点是**直线插值**, 只代表"意图段",
    控制器实际走的是它自己的插补 ⇒ 报告里必须写明这一点(不冒充控制器轨迹)。
  · MoveIt 那条(URDF 与真机差 261.5mm/137.5°)只在 --moveit-compare 里给**数字**, 绝不画到真机画面上。

用法:
  ./gui-venv311/bin/python tools/live_plan_segment.py --to slot2 --publish
  ./gui-venv311/bin/python tools/live_plan_segment.py --to-xyz 0.647 0.206 0.108 --publish
  ./gui-venv311/bin/python tools/live_plan_segment.py --to slot2 --moveit-compare
  ./gui-venv311/bin/python tools/live_plan_segment.py --restore      # 恢复 plan 层备份
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
import scene_overlay as SO                                                      # noqa: E402

TAUGHT = os.path.join(_REPO, "data", "skills", "l2_atomic", "taught_points.json")
SPEC = os.path.join(_REPO, "data", "scene", "overlay_spec.json")
HEAD_LOCAL = os.path.join(_REPO, "reports", "moveit", "live_head.json")
CONTAINER = os.environ.get("TRACE_CONTAINER", "ss-remote-tap")
MAX_STEP_MM = 50.0      # 与 arm_control.GATE / l2_daemon 守卫同口径
MAX_DOWN_MM = 20.0
CAM = "arm"


def quat_angle_deg(a, b):
    d = abs(sum(x * y for x, y in zip(a, b)))
    d = max(-1.0, min(1.0, d))
    return math.degrees(2.0 * math.acos(d))


def now_tcp(max_age=3.0):
    """真机当前 TCP(优先读 marker 刚落盘的 head 小文件; 太旧就自己 docker cp 一次)。"""
    if os.path.isfile(HEAD_LOCAL) and time.time() - os.path.getmtime(HEAD_LOCAL) < max_age:
        try:
            h = json.load(open(HEAD_LOCAL, encoding="utf-8"))["head"]
            if h:
                return h[-1]["tcp"], h[-1].get("js"), "head(%.1fs前)" % (time.time() - os.path.getmtime(HEAD_LOCAL))
        except Exception:                                                      # noqa: BLE001
            pass
    r = subprocess.run(["sudo", "docker", "cp", "%s:/tmp/live_head.json" % CONTAINER, HEAD_LOCAL],
                       capture_output=True, text=True, timeout=30)
    if r.returncode == 0:
        try:
            h = json.load(open(HEAD_LOCAL, encoding="utf-8"))["head"]
            if h:
                return h[-1]["tcp"], h[-1].get("js"), "刚 docker cp"
        except Exception:                                                      # noqa: BLE001
            pass
    return None, None, "取不到真机 TCP"


def taught_point(name):
    d = json.load(open(TAUGHT, encoding="utf-8"))
    pts = d.get("points") or {}
    if name not in pts:
        return None, "示教库里没有 '%s' (有: %s)" % (name, ", ".join(list(pts)[:12]))
    v = pts[name]
    p = v.get("p") or v.get("xyz") or v.get("pos")
    q = v.get("q") or v.get("quat") or v.get("quaternion")
    if p is None:
        return None, "示教点 %s 没有位置字段" % name
    return {"p": [float(x) for x in p], "q": [float(x) for x in q] if q else None,
            "frame": v.get("frame") or d.get("frame")}, ""


def segment(a, b, max_step_mm, max_down_mm):
    """按执行器守卫分段; 返回 [(点, 段长mm, 该段下降mm, 过闸?)]"""
    d = [b[i] - a[i] for i in range(3)]
    dist = math.dist(a, b) * 1000.0
    n = max(1, int(math.ceil(dist / max_step_mm)))
    rows = []
    prev = a
    for i in range(1, n + 1):
        pt = [a[j] + d[j] * (i / float(n)) for j in range(3)]
        seg_mm = math.dist(prev, pt) * 1000.0
        down_mm = -(pt[2] - prev[2]) * 1000.0
        rows.append({"pt": pt, "seg_mm": seg_mm, "down_mm": down_mm,
                     "ok_step": seg_mm <= max_step_mm + 1e-6,
                     "ok_down": down_mm <= max_down_mm + 1e-6})
        prev = pt
    return rows, dist


def publish(pts, quats=None, label="同源规划段"):
    shutil.copy2(SPEC, SPEC + ".bak_planseg_" + time.strftime("%H%M%S"))
    spec = SO.load_spec()
    els = [{"origin": "plan", "label": label, "kind": "path3d", "pts3d": pts,
            "width": 4, "no_label": True, "conf": 1.0}]
    SO.merge_origin(spec, CAM, "plan", els)
    SO.save_spec(spec)
    return len(pts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", default="", help="示教点名(taught_points.json)")
    ap.add_argument("--to-xyz", nargs=3, type=float, default=None)
    ap.add_argument("--to-quat", nargs=4, type=float, default=None)
    ap.add_argument("--max-step-mm", type=float, default=MAX_STEP_MM)
    ap.add_argument("--max-down-mm", type=float, default=MAX_DOWN_MM)
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--moveit-compare", action="store_true")
    ap.add_argument("--restore", action="store_true")
    a = ap.parse_args()

    if a.restore:
        baks = sorted([f for f in os.listdir(os.path.dirname(SPEC)) if ".bak_planseg_" in f])
        if not baks:
            print("没有 plan 层备份可恢复"); return 2
        src = os.path.join(os.path.dirname(SPEC), baks[-1])
        shutil.copy2(src, SPEC)
        print("已从 %s 恢复 spec" % os.path.basename(src)); return 0

    tcp, js, src = now_tcp()
    if not tcp:
        print("❌ %s" % src); return 2
    cur = tcp[:3]
    print("起点(真机真值, %s): p=[%s]" % (src, ", ".join("%.5f" % v for v in cur)))
    if js:
        print("   关节: %s" % {k: round(v, 4) for k, v in js.items()})

    if a.to_xyz:
        tgt = {"p": list(a.to_xyz), "q": a.to_quat, "frame": "base"}
        tname = "指定目标"
    elif a.to:
        tgt, err = taught_point(a.to)
        if not tgt:
            print("❌ %s" % err); return 2
        tname = a.to
    else:
        print("❌ 给 --to <示教点> 或 --to-xyz"); return 2

    rows, dist = segment(cur, tgt["p"], a.max_step_mm, a.max_down_mm)
    ang = quat_angle_deg(tcp[3:7], tgt["q"]) if tgt.get("q") else None
    print("\n── 规划段: 当前 → %s ──" % tname)
    print("  目标 p=[%s]  frame=%s" % (", ".join("%.5f" % v for v in tgt["p"]), tgt.get("frame")))
    print("  Δ位置 = %.1f mm   分段 = %d 段(单步 ≤%.0fmm)" % (dist, len(rows), a.max_step_mm))
    if ang is not None:
        chunks = int(math.ceil(ang / 10.0)) if ang > 10.0 else 1
        print("  Δ姿态 = %.2f°(目标带四元数, 口径与 /robot/tcp_pose 同为 xyzw)"
              " ⇒ 需按 ≤10°/段自转分 %d 段(执行器守卫 max_deg=10)" % (ang, chunks))
    else:
        print("  Δ姿态 = 未知(该示教点没有四元数 ⇒ 姿态沿用当前, 需要现场确认)")
    bad = [r for r in rows if not (r["ok_step"] and r["ok_down"])]
    for i, r in enumerate(rows, 1):
        flag = "✓" if (r["ok_step"] and r["ok_down"]) else "✗"
        print("    %2d/%d 段长 %6.1fmm · 下降 %5.1fmm %s" % (i, len(rows), r["seg_mm"], r["down_mm"], flag))
    print("  守卫结论: %s" % ("全部过闸 ✓" if not bad else "有 %d 段不过闸 ✗" % len(bad)))

    if a.publish:
        pts = [cur] + [r["pt"] for r in rows]
        n = publish(pts, label="规划段→%s(%d段/%.0fmm)" % (tname, len(rows), dist))
        print("  已叠加: origin=plan · %d 点(kind=path3d)" % n)
        print("  ⚠️ 口径: 两端是真机真值; 中间点=直线插值(意图段), 控制器实际走自己的插补 —— 不是控制器轨迹。")
        print("     本段**未过 MoveIt 同源闸**(URDF 与真机差 261.5mm) ⇒ MoveIt 的轨迹不画到真机画面上。")

    if a.moveit_compare:
        print("\n── MoveIt plan-only 对照(只看数, 不画) ──")
        print("  说明: 需在 zmax-moveit(domain42) 容器里用 tools/moveit_plan_only.py 跑;")
        print("        其 FK 与真机不同源(261.5mm/137.5°), 因此数值只作参考, 不可当轨迹。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
