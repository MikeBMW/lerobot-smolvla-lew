#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成"绝对位姿循环"——消掉 line_rel 的累积漂移
  ① 只读采样当前 TCP（N 帧取均值，方差要极小）
  ② 由起点算出 4 个绝对路点（上/后/下/前，各 20mm）
  ③ 写入 taught_points.json（只追加，不动原点位）
  ④ 注册 4 个 line_abs 技能到 registry.json（热加载，无需重启 daemon）
用法: python tools/make_abs_loop.py [--dry]
"""
import json
import os
import re
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PTS = os.path.join(REPO, "data/skills/l2_atomic/taught_points.json")
REG = os.path.join(REPO, "data/skills/l2_atomic/registry.json")
CONTAINER = "zmax-arm-raw"
D_MM = 20.0
DRY = "--dry" in sys.argv

NUM = re.compile(r"-?\d+\.?\d*(?:[eE][-+]?\d+)?")


def read_tcp(n=6):
    """只读 /robot/tcp_pose，取 n 帧"""
    samples = []
    for _ in range(n):
        try:
            r = subprocess.run(["sudo", "docker", "exec", CONTAINER, "bash", "-lc",
                                "source /opt/ros/humble/setup.bash; export ROS_DOMAIN_ID=0; "
                                "timeout 6 ros2 topic echo --once /robot/tcp_pose --field pose"],
                               capture_output=True, text=True, timeout=25)
            v = [float(x) for x in NUM.findall(r.stdout)]
            if len(v) >= 7:
                samples.append(v[:7])
        except Exception as e:
            print("  采样失败:", e)
    return samples


def main():
    print("══ ① 只读采样当前 TCP ══")
    s = read_tcp(6)
    if len(s) < 3:
        print("  ❌ 采样不足:", len(s))
        return
    pos = [sum(x[i] for x in s) / len(s) for i in range(3)]
    quat = [sum(x[i] for x in s) / len(s) for i in range(3, 7)]
    spread = [max(x[i] for x in s) - min(x[i] for x in s) for i in range(3)]
    print("  采样 %d 帧 · 起点 pos=(%.7f, %.7f, %.7f)" % (len(s), pos[0], pos[1], pos[2]))
    print("  位置极差(mm): (%.4f, %.4f, %.4f)  %s" % (
        spread[0] * 1000, spread[1] * 1000, spread[2] * 1000,
        "✓ 静止" if max(spread) < 1e-4 else "⚠️ 未静止"))

    d = D_MM / 1000.0
    wp = {
        "loop20_p1": ([pos[0], pos[1], pos[2] + d], "上 +Z 20mm"),
        "loop20_p2": ([pos[0] - d, pos[1], pos[2] + d], "后 -X 20mm"),
        "loop20_p3": ([pos[0] - d, pos[1], pos[2]], "下 -Z 20mm"),
        "loop20_p4": ([pos[0], pos[1], pos[2]], "前 +X 20mm (=起点)"),
    }
    print("\n══ ② 绝对路点（由起点算出，绝对位姿 → 不累积漂移）══")
    for k, (p, desc) in wp.items():
        print("  %-12s (%.7f, %.7f, %.7f)  %s" % (k, p[0], p[1], p[2], desc))

    if DRY:
        print("\n  --dry: 不写文件")
        return

    # ③ 写点位库（只追加）
    print("\n══ ③ 写入 taught_points.json ══")
    tp = json.load(open(PTS, encoding="utf-8"))
    tp.setdefault("points", {})
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    for k, (p, desc) in wp.items():
        tp["points"][k] = {
            "pos": [round(v, 7) for v in p],
            "quat": [round(v, 7) for v in quat],
            "desc": "绝对位姿循环路点 %s (消漂移用, 由 make_abs_loop.py 生成)" % desc,
            "recorded_at": now,
            "source": "/robot/tcp_pose (只读采样 %d 帧均值)" % len(s),
            "n_samples": len(s),
            "spread_pos_m": max(spread),
        }
        print("  + %s" % k)
    json.dump(tp, open(PTS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # ④ 注册技能（只追加）
    print("\n══ ④ 注册 line_abs 技能 ══")
    rg = json.load(open(REG, encoding="utf-8"))
    have = {x["id"] for x in rg["skills"]}
    for i, k in enumerate(("loop20_p1", "loop20_p2", "loop20_p3", "loop20_p4"), 1):
        sid = "L2." + k
        if sid in have:
            print("  = %s 已存在，跳过" % sid)
            continue
        rg["skills"].append({
            "id": sid,
            "name": {"loop20_p1": "⬆️绝对·上", "loop20_p2": "⏪绝对·后",
                     "loop20_p3": "⬇️绝对·下", "loop20_p4": "⏩绝对·前"}[k],
            "icon": "🧭",
            "ros": "line_abs",
            "quat": "taught",
            "param": {},
            "point": k,
            "point_locked": True,
            "guard": {"dz_down_limit_mm": 30},
            "note": "绝对位姿循环路点(20mm), 与 L2.lift/backward/lower/forward 同序但绝对 → 无累积漂移",
            "group": "运动",
        })
        print("  + %s" % sid)
    json.dump(rg, open(REG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n  ✅ 完成。跑法: echo '{\"skill\":\"L2.loop20_p1\",\"speed\":19}' > ~/zmax_data/l2_cmd.fifo")


if __name__ == "__main__":
    main()
