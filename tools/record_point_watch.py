#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""record_point_watch.py — 盯真值, 等臂停稳在新位置后自动录点 (不下发任何运动)

用法:
  python3 tools/record_point_watch.py <新点名> "<说明>" [参考点名=slot1] [最小距离mm=40] [超时s=480]

链路: 只读订阅 /robot/tcp_pose (Docker tap 容器) —— 全程不发任何指令。
判据: 连续 5 帧相邻位移 <0.5mm 且 距参考点 > 最小距离  → 调 record_l2_point.py 正式录点
      (6 帧均值 + 极差 ≤1e-4 m; 极差超标会自己拒绝, 不写坏点位)。
用途: 老倪拖着臂到"二号位/三号位…", 我不用他喊"到了", 停稳自动录。
"""
import importlib.util
import os
import subprocess
import sys
import time
from collections import deque

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location("rlp", os.path.join(REPO, "tools/record_l2_point.py"))
rlp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rlp)
PTS_PATH = os.path.join(REPO, "data/skills/l2_atomic/taught_points.json")


def ref_pos(name):
    import json
    try:
        return json.load(open(PTS_PATH, encoding="utf-8"))["points"][name]["pos"]
    except Exception:
        return None


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    name, desc = sys.argv[1], sys.argv[2]
    ref = sys.argv[3] if len(sys.argv) > 3 else "slot1"
    min_d = float(sys.argv[4]) if len(sys.argv) > 4 else 40.0
    timeout = float(sys.argv[5]) if len(sys.argv) > 5 else 480.0
    r0 = ref_pos(ref)
    if not r0:
        print("❌ 参考点 %s 不存在" % ref)
        return 1
    print("盯真值中: 等「距 %s > %.0fmm 且停稳」→ 自动录点 %s (上限 %.0fs, 全程不下发指令)"
          % (ref, min_d, name, timeout))
    t0 = time.time()
    win = deque(maxlen=5)
    last_log = 0.0
    while time.time() - t0 < timeout:
        rows = rlp.sample(1)
        if not rows:
            time.sleep(0.5)
            continue
        v = rows[0]
        win.append(v)
        dx = [(v[i] - r0[i]) * 1000.0 for i in range(3)]
        dist = sum(x * x for x in dx) ** 0.5
        if len(win) == win.maxlen:
            sp = max(max(w[i] for w in win) - min(w[i] for w in win) for i in range(3)) * 1000.0
        else:
            sp = 999.0
        if time.time() - last_log > 5:
            print("  …距 %s %.0fmm · 窗口内极差 %.2fmm · 位置(%.4f, %.4f, %.4f)"
                  % (ref, dist, sp, v[0], v[1], v[2]), flush=True)
            last_log = time.time()
        if len(win) == win.maxlen and sp < 0.5 and dist > min_d:
            print("✅ 判定停稳: 距 %s %.1fmm · 窗口极差 %.3fmm → 正式录点" % (ref, dist, sp))
            r = subprocess.run([sys.executable, os.path.join(REPO, "tools/record_l2_point.py"), name, desc],
                               capture_output=True, text=True, timeout=180)
            print(r.stdout.strip() or r.stderr.strip())
            return 0 if r.returncode == 0 else r.returncode
        time.sleep(0.3)
    print("⏰ %.0fs 内没检测到「远离 %s 且停稳」—— 臂还在动/还没到位/离得太近" % (timeout, ref))
    return 3


if __name__ == "__main__":
    sys.exit(main())
