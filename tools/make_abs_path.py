#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成"绝对位姿循环路点"(消 line_rel 累积漂移) —— 参数化版
  路径顺序: 前(+X) → 上(+Z) → 后(-X) → 下(-Z)，边长 --d
  ① 只读采样当前 TCP 得起点  ② 算 4 个绝对路点
  ③ 写 taught_points.json（只追加）  ④ 注册 line_abs 技能（注册表热加载，不重启 daemon）
用法: python tools/make_abs_path.py --d 30 --prefix afx30 [--dry]
     python tools/make_abs_path.py --d 30 --prefix afx30 --speed 30
"""
import argparse
import json
import os
import re
import subprocess
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PTS = os.path.join(REPO, "data/skills/l2_atomic/taught_points.json")
REG = os.path.join(REPO, "data/skills/l2_atomic/registry.json")
CONTAINER = "zmax-arm-raw"
NUM = re.compile(r"-?\d+\.?\d*(?:[eE][-+]?\d+)?")

ap = argparse.ArgumentParser()
ap.add_argument("--d", type=float, default=20.0, help="边长 mm")
ap.add_argument("--prefix", default="afx", help="路点/技能名前缀")
ap.add_argument("--dry", action="store_true")
A = ap.parse_args()
D_MM = A.d
PFX = A.prefix
NAMES = {"p1": "⏩绝对·前", "p2": "⬆️绝对·上", "p3": "⏪绝对·后", "p4": "⬇️绝对·下"}


def read_tcp(n=6):
    s = []
    for _ in range(n):
        try:
            r = subprocess.run(["sudo", "docker", "exec", CONTAINER, "bash", "-lc",
                                "source /opt/ros/humble/setup.bash; export ROS_DOMAIN_ID=0; "
                                "timeout 6 ros2 topic echo --once /robot/tcp_pose --field pose"],
                               capture_output=True, text=True, timeout=25)
            v = [float(x) for x in NUM.findall(r.stdout)]
            if len(v) >= 7:
                s.append(v[:7])
        except Exception as e:
            print("  采样失败:", e)
    return s


def main():
    print("══ ① 只读采样当前 TCP ══")
    s = read_tcp(6)
    if len(s) < 3:
        print("  ❌ 采样不足:", len(s))
        return
    pos = [sum(x[i] for x in s) / len(s) for i in range(3)]
    quat = [sum(x[i] for x in s) / len(s) for i in range(3, 7)]
    spread = [max(x[i] for x in s) - min(x[i] for x in s) for i in range(3)]
    print("  %d 帧 · 起点 (%.7f, %.7f, %.7f) · 极差 %.4fmm %s" % (
        len(s), pos[0], pos[1], pos[2], max(spread) * 1000,
        "✓静止" if max(spread) < 1e-4 else "⚠️未静止"))

    d = D_MM / 1000.0
    x0, y0, z0 = pos
    wp = {
        PFX + "_p1": ([x0 + d, y0, z0], "前 +X %.0fmm" % D_MM),
        PFX + "_p2": ([x0 + d, y0, z0 + d], "上 +Z %.0fmm" % D_MM),
        PFX + "_p3": ([x0, y0, z0 + d], "后 -X %.0fmm" % D_MM),
        PFX + "_p4": ([x0, y0, z0], "下 -Z %.0fmm (=起点)" % D_MM),
    }
    print("\n══ ② 绝对路点（前→上→后→下，边长 %.0fmm）══" % D_MM)
    for k, (p, desc) in wp.items():
        print("  %-16s (%.7f, %.7f, %.7f)  %s" % (k, p[0], p[1], p[2], desc))

    if A.dry:
        print("\n  --dry: 不写文件")
        return

    print("\n══ ③ 写 taught_points.json ══")
    tp = json.load(open(PTS, encoding="utf-8"))
    tp.setdefault("points", {})
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    for k, (p, desc) in wp.items():
        tp["points"][k] = {
            "pos": [round(v, 7) for v in p], "quat": [round(v, 7) for v in quat],
            "desc": "绝对位姿循环路点 %s (make_abs_path.py 生成)" % desc,
            "recorded_at": now, "source": "/robot/tcp_pose (只读 %d 帧均值)" % len(s),
            "n_samples": len(s), "spread_pos_m": max(spread),
        }
        print("  + %s" % k)
    json.dump(tp, open(PTS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("\n══ ④ 注册 line_abs 技能 ══")
    rg = json.load(open(REG, encoding="utf-8"))
    have = {x["id"] for x in rg["skills"]}
    for i, k in enumerate([PFX + "_p1", PFX + "_p2", PFX + "_p3", PFX + "_p4"], 1):
        sid = "L2." + k
        if sid in have:
            old = [x for x in rg["skills"] if x["id"] == sid][0]
            old["point"] = k
            old["guard"] = {"dz_down_limit_mm": D_MM + 10}
            print("  = %s 已存在，已更新" % sid)
            continue
        rg["skills"].append({
            "id": sid, "name": NAMES["p%d" % i], "icon": "🧭", "ros": "line_abs",
            "quat": "taught", "param": {}, "point": k, "point_locked": True,
            "guard": {"dz_down_limit_mm": D_MM + 10},
            "note": "绝对位姿循环路点 %.0fmm(前→上→后→下)，无累积漂移" % D_MM,
            "group": "运动",
        })
        print("  + %s" % sid)
    json.dump(rg, open(REG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n  ✅ 完成。序列: %s" % ",".join(PFX + "_p%d" % i for i in (1, 2, 3, 4)))


if __name__ == "__main__":
    main()
