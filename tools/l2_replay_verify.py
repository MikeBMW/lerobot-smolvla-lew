#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""l2_replay_verify.py — L2 肌肉记忆慢速回放校验 (逐步比对演示真值)
用法: gui-venv311/bin/python tools/l2_replay_verify.py --skill <json> --from 0 --to 3 --speed 20
"""
import argparse, json, os, subprocess, sys, time
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
from l2_ros2_bridge import sh, gate, tcp_pose, cmd_move  # 复用桥的转发/闸门

def read_pos():
    o = sh("ros2 topic echo --once /robot/tcp_pose --field pose.position 2>/dev/null | tr '\\n' ' '", 90)
    import re
    m = re.findall(r'(-?[0-9.]+)', o)
    return [float(x) for x in m[:3]] if len(m) >= 3 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", default="data/skills/l2_muscle/光模块_抓放_演示学习_v1.json")
    ap.add_argument("--from", dest="i0", type=int, default=0)
    ap.add_argument("--to", dest="i1", type=int, default=99)
    ap.add_argument("--speed", type=float, default=20)
    a = ap.parse_args()
    sk = json.load(open(os.path.join(REPO, a.skill), encoding="utf-8"))
    steps = sk["steps"][a.i0:a.i1 + 1]
    print("回放 %d 步 (speed=%s): 三闸门→下发→读真值→比对演示值" % (len(steps), a.speed))
    for k, st in enumerate(steps):
        idx = a.i0 + k; name = st["to"]; pt = sk["points"][name]
        ok, info = gate()
        print("\n--- [%d] %s 目标 %s" % (idx, name, [round(v, 5) for v in pt["pos"]]))
        print("    闸门: %s" % ("通过 ✓" if ok else ("未过 ✗ " + json.dumps(info, ensure_ascii=False))))
        if not ok:
            print("    → 跳过(不硬发)"); continue
        t0 = time.time(); out = sh(cmd_move(pt, a.speed), 400); time.sleep(6)
        p = read_pos()
        if p:
            d = [round((p[i] - pt["pos"][i]) * 1000, 2) for i in range(3)]
            e = round(sum((p[i] - pt["pos"][i]) ** 2 for i in range(3)) ** 0.5 * 1000, 2)
            print("    实测 %s → 差(演示值) %s mm | 模长 %.2f mm" % ([round(v, 5) for v in p], d, e))
        print("    success=%s · 耗时 %.0fs" % ("success=True" in out, time.time() - t0))


if __name__ == "__main__":
    main()
