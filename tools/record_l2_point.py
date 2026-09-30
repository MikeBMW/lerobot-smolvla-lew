#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""record_l2_point.py — 记录当前真机 TCP 位姿为 L2 示教点位 (只读订阅, 不下发任何运动)

用法(原 CLI 兼容):
  python3 tools/record_l2_point.py <点位名> ["说明"]
  python3 tools/record_l2_point.py --name slot4 --desc "4号位" --samples 6 [--dry] [--json]

链路: 本机 Docker tap 容器 (ss-remote-tap, ROS_DOMAIN_ID=0) → /robot/tcp_pose 只读订阅
纪律:
  · 连续采样 ≥6 帧算均值 + 极差; **极差过大(机械臂还在动) → 拒绝记录**, 绝不写坏点位;
  · 写前自动备份到 /tmp/taught_points.pre_<name>_<时间>.json;
  · 一律写 4 分量四元数(2026-09-30 教训: 缺 w 的 quat 会让执行器 plan_stage 抛 IndexError);
  · ``--dry`` 只采样+打印不落盘; ``--json`` 末行输出一份机器可读结果(给页面/接口用)。

2026-09-30 老倪: 「4 5 6 号位, 你能自己实现记录么？」—— 记录本身零运动, 所以可以做成
页面按钮(8793 /ctl/record_point → 本脚本), 现场点动到位后一键记住; 但"臂要站在那个
物理位置上"仍需现场(或由几何外推候选 + 人眼确认)。
"""
import json
import math
import os
import re
import shutil
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


def parse_args(argv):
    name, desc, samples, dry, js = None, "", 6, False, False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--dry",):
            dry = True
        elif a in ("--json",):
            js = True
        elif a in ("--name", "-n"):
            i += 1
            name = argv[i]
        elif a in ("--desc", "-d"):
            i += 1
            desc = argv[i]
        elif a in ("--samples", "-s"):
            i += 1
            samples = max(4, int(argv[i]))
        elif a in ("-h", "--help"):
            print(__doc__)
            sys.exit(0)
        elif not a.startswith("-"):
            if name is None:
                name = a
            elif not desc:
                desc = a
        i += 1
    return name, desc, samples, dry, js


def main():
    name, desc, samples, dry, js = parse_args(sys.argv[1:])
    if not name:
        print("用法: python3 tools/record_l2_point.py <点位名> [说明]")
        return 2
    rows = sample(samples)
    if len(rows) < 4:
        out = {"ok": False, "name": name, "msg": "采样不足 (%d 帧) —— 检查 tap 容器/tcp_pose 话题" % len(rows),
               "n_samples": len(rows)}
        print(json.dumps(out, ensure_ascii=False) if js else "❌ " + out["msg"])
        return 1
    cols = list(zip(*rows))
    mean = [sum(c) / len(c) for c in cols]
    spread = [max(c) - min(c) for c in cols]
    pos_max, quat_max = max(spread[:3]), max(spread[3:])
    print("采样 %d 帧: pos=(%.7f, %.7f, %.7f) m · quat(xyzw)=(%.7f, %.7f, %.7f, %.7f)"
          % (len(rows), mean[0], mean[1], mean[2], mean[3], mean[4], mean[5], mean[6]))
    print("极差: pos %.2e m · quat %.2e  (静止判据: pos 极差 ≤1e-4 m)" % (pos_max, quat_max))
    if pos_max > 1e-4:
        out = {"ok": False, "name": name, "n_samples": len(rows), "spread_pos_m": round(pos_max, 8),
               "msg": "机械臂还在动 (极差 %.2e m > 1e-4) → 拒绝记录, 让现场停稳再录" % pos_max}
        print(json.dumps(out, ensure_ascii=False) if js else "❌ " + out["msg"])
        return 1
    quat = [round(v, 7) for v in mean[3:7]]
    try:                                        # 单位约束自检: 缺分量/坏四元数绝不入库
        n2 = sum(v * v for v in quat)
        if abs(n2 - 1.0) > 1e-4 or len(quat) != 4:
            raise ValueError("|q|^2=%.6f" % n2)
    except Exception as e:                                                    # noqa: BLE001
        out = {"ok": False, "name": name, "msg": "四元数不自洽(%s) → 拒绝记录" % e}
        print(json.dumps(out, ensure_ascii=False) if js else "❌ " + out["msg"])
        return 1
    try:
        store = json.load(open(OUT, encoding="utf-8"))
    except Exception:
        store = {"version": "v1",
                 "note": "L2 示教绝对点位 (按真机 /robot/tcp_pose 实测记录, 供 line_abs 回点)",
                 "frame": "base_link", "points": {}}
    had = name in (store.get("points") or {})
    entry = {
        "pos": [round(v, 7) for v in mean[:3]],
        "quat": quat,
        "desc": desc or ("%s — 2026-09-30 现场记录" % name),
        "recorded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": "/robot/tcp_pose (只读订阅, Docker tap)",
        "n_samples": len(rows),
        "spread_pos_m": round(pos_max, 8),
        "spread_quat": round(quat_max, 8),
    }
    if not dry:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        if os.path.exists(OUT):
            bak = "/tmp/taught_points.pre_%s_%s.json" % (name, time.strftime("%m%d_%H%M%S"))
            shutil.copy(OUT, bak)
            print("备份: %s" % bak)
        store.setdefault("points", {})[name] = entry
        store["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(store, f, ensure_ascii=False, indent=1)
        print("✅ 已记录点位 %s → %s" % (name, OUT))
    else:
        print("(--dry: 未落盘)")
    out = {"ok": True, "name": name, "written": (not dry), "overwrote": bool(had),
           "pos": entry["pos"], "quat": entry["quat"], "n_samples": len(rows),
           "spread_pos_m": entry["spread_pos_m"], "spread_quat": entry["spread_quat"],
           "recorded_at": entry["recorded_at"],
           "msg": ("%s已记录 %s" % ("覆盖" if had else "", name)) if not dry else ("%s 演练: 未落盘" % name)}
    if js:
        print(json.dumps(out, ensure_ascii=False))
    else:
        print(json.dumps(entry, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
