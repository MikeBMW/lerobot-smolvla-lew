#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""record_l2_point.py — 记录当前真机 TCP 位姿为 L2 示教点位 (只读订阅, 不下发任何运动)

用法: python3 tools/record_l2_point.py <点位名> ["说明"]
链路: 本机 Docker tap 容器 (ss-remote-tap, ROS_DOMAIN_ID=0) → /robot/tcp_pose 只读订阅
纪律: 连续采样 ≥6 帧算均值 + 极差; 极差过大(机械臂还在动) → 拒绝记录, 不写坏点位。
"""
import json
import os
import re
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "data", "skills", "l2_atomic", "taught_points.json")
CONTAINER = os.environ.get("ZMAX_TAP_CONTAINER", "ss-remote-tap")
NUM = re.compile(r"-?\d+\.?\d*(?:e-?\d+)?")


def sample(n=6, timeout=8):
    """只读采样 /robot/tcp_pose 的 pose (position xyz + orientation xyzw)"""
    rows = []
    for _ in range(n):
        cmd = ("source /opt/ros/humble/setup.bash; export ROS_DOMAIN_ID=0; "
               "timeout 4 ros2 topic echo --once /robot/tcp_pose --field pose")
        r = subprocess.run(["sudo", "docker", "exec", CONTAINER, "bash", "-lc", cmd],
                           capture_output=True, text=True, timeout=timeout + 8)
        vals = [float(x) for x in NUM.findall(r.stdout)]
        if len(vals) >= 7:
            rows.append(vals[:7])
        time.sleep(0.5)
    return rows


def main():
    if len(sys.argv) < 2:
        print("用法: python3 tools/record_l2_point.py <点位名> [说明]")
        return 2
    name = sys.argv[1]
    desc = sys.argv[2] if len(sys.argv) > 2 else ""
    rows = sample()
    if len(rows) < 4:
        print("❌ 采样不足 (%d 帧) —— 检查 tap 容器/tcp_pose 话题" % len(rows))
        return 1
    cols = list(zip(*rows))
    mean = [sum(c) / len(c) for c in cols]
    spread = [max(c) - min(c) for c in cols]
    pos_max, quat_max = max(spread[:3]), max(spread[3:])
    print("采样 %d 帧: pos=(%.7f, %.7f, %.7f) m · quat(xyzw)=(%.7f, %.7f, %.7f, %.7f)"
          % (len(rows), mean[0], mean[1], mean[2], mean[3], mean[4], mean[5], mean[6]))
    print("极差: pos %.2e m · quat %.2e  (静止判据: pos 极差 ≤1e-4 m)" % (pos_max, quat_max))
    if pos_max > 1e-4:
        print("❌ 机械臂还在动 (极差 %.2e m > 1e-4) → 拒绝记录, 让现场停稳再录" % pos_max)
        return 1
    try:
        store = json.load(open(OUT, encoding="utf-8"))
    except Exception:
        store = {"version": "v1",
                 "note": "L2 示教绝对点位 (按真机 /robot/tcp_pose 实测记录, 供 line_abs 回点)",
                 "frame": "base_link", "points": {}}
    store.setdefault("points", {})[name] = {
        "pos": [round(v, 7) for v in mean[:3]],
        "quat": [round(v, 7) for v in mean[3:7]],
        "desc": desc,
        "recorded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": "/robot/tcp_pose (只读订阅, Docker tap)",
        "n_samples": len(rows),
        "spread_pos_m": round(pos_max, 8),
        "spread_quat": round(quat_max, 8),
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=1)
    print("✅ 已记录点位 %s → %s" % (name, OUT))
    print(json.dumps(store["points"][name], ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
