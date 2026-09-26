#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""goto_ref_low.py — 移到【新低高度的参考姿态】并验证靶标在视野

老倪授权继续（现场安全）。新工作高度 z=0.22711（比原来低100mm，上方空间宽敞）
只改姿态不改位置 → 靶标应重新进入视野（原参考姿态 0.81143... 下板可见）
"""
import os
import re
import subprocess
import time

import numpy as np

ORIN = "tashan@192.168.23.66"
PRE = ("source /opt/ros/humble/setup.bash; for ws in /home/tashan/0810/*/install/setup.bash; "
       "do [ -f \"$ws\" ] && source \"$ws\" && break; done; export ROS_DOMAIN_ID=0; ")
NEW_POS = np.array([0.53372, 0.23132, 0.22711])
REF_Q = np.array([0.8114265263133928, 0.0545364276727192, 0.5813654658319766, -0.02503928093312072])


def orin(cmd, timeout=90):
    r = subprocess.run(["sshpass", "-p", "ts123", "ssh", "-o", "StrictHostKeyChecking=no",
                        "-o", "ConnectTimeout=8", ORIN, PRE + cmd],
                       capture_output=True, text=True, timeout=timeout)
    return (r.stdout or "") + (r.stderr or "")


def read_pose():
    o = orin("timeout 10 ros2 topic echo --once /robot/tcp_pose --field pose 2>/dev/null")
    v = [float(x) for x in re.findall(r"-?\d+\.?\d*(?:e-?\d+)?", o)]
    return np.array(v[:7]) if len(v) >= 7 else None


def ang_deg(a, b):
    d = abs(float(np.dot(a, b)) / (np.linalg.norm(a) * np.linalg.norm(b)))
    return float(np.degrees(2 * np.arccos(min(1.0, d))))


print("══ 下发参考姿态（位置不动，只改姿态）══")
call = ('ros2 service call /move_pose interfaces/srv/TargetPose "{speed: 30.0, joint_state: {name: [], '
        'position: []}, pose: {position: {x: %.7f, y: %.7f, z: %.7f}, '
        'orientation: {x: %.7f, y: %.7f, z: %.7f, w: %.7f}}}"'
        % (NEW_POS[0], NEW_POS[1], NEW_POS[2], REF_Q[0], REF_Q[1], REF_Q[2], REF_Q[3]))
try:
    o = orin(call, timeout=90)
    print("  返回: %s" % ("success=True ✓" if "success=True" in o.replace(" ", "") else o.strip()[-160:]))
except subprocess.TimeoutExpired:
    print("  ssh 超时（服务侧30s窗口问题，不影响运动实际执行）")

t0 = time.time()
arr = False
while time.time() - t0 < 100:
    p = read_pose()
    if p is not None and float(np.linalg.norm(p[:3] - NEW_POS)) < 0.0015 and ang_deg(p[3:], REF_Q) < 1.0:
        arr = True
        print("  ✓ 到位 (%.0fs)  z=%.5f" % (time.time() - t0, p[2]))
        break
    time.sleep(4)
if not arr:
    print("  ⚠ 未确认到位")

print()
print("══ 抓帧验证靶标 ══")
subprocess.run(["sshpass", "-p", "ts123", "ssh", "-o", "StrictHostKeyChecking=no", ORIN,
                "bash /tmp/orin_hires_capture.sh"], capture_output=True, timeout=280)
subprocess.run(["sshpass", "-p", "ts123", "scp", "-o", "StrictHostKeyChecking=no",
                "%s:/tmp/hires_color.png" % ORIN, "/tmp/scene/ref_low_color.png"], capture_output=True, timeout=130)
import cv2
img = cv2.imread("/tmp/scene/ref_low_color.png")
if img is None:
    print("  ✗ 无图")
else:
    g0 = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    H, W = g0.shape
    best = None
    for nm, src in (("全图", g0), ("裁剪", g0[max(0, 281):min(H, 668), max(0, 153):min(W, 768)])):
        for z in (1.0, 2.2, 3.0):
            gg = cv2.resize(src, None, fx=z, fy=z, interpolation=cv2.INTER_CUBIC) if z != 1.0 else src
            for pol in (cv2.bitwise_not(gg), gg):
                ok, cc = cv2.findCirclesGrid(pol, (4, 5), flags=cv2.CALIB_CB_ASYMMETRIC_GRID)
                if ok and best is None:
                    best = (nm, z, len(cc))
    print("  靶标: %s" % ("✅ 检出 %s@%.1fx → %d 点 ⇒ **可以开始采集**" % best if best else "✗ 未检出"))
