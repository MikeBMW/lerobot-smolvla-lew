#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""move_down_50_step.py — 分5步向下50mm，每步读力/力矩做保护

老倪现场授权（"没事，我看着呢"）。补充保险: 10mm/步 + 每步读 /robot/force_torque
  基线力由本步实测；若 |Fz| 相对基线升高 >5N 或 |T| >2.5Nm ⇒ 立即停（等效 09-21 那次的力矩报警）
"""
import re
import subprocess
import time

import numpy as np

ORIN = "tashan@192.168.23.66"
PRE = ("source /opt/ros/humble/setup.bash; for ws in /home/tashan/0810/*/install/setup.bash; "
       "do [ -f \"$ws\" ] && source \"$ws\" && break; done; export ROS_DOMAIN_ID=0; ")
BOARD_Z = 0.2526
SPEED = 25.0
STEP = 0.010
NSTEP = 5


def orin(cmd, timeout=90):
    r = subprocess.run(["sshpass", "-p", "ts123", "ssh", "-o", "StrictHostKeyChecking=no",
                        "-o", "ConnectTimeout=8", ORIN, PRE + cmd],
                       capture_output=True, text=True, timeout=timeout)
    return (r.stdout or "") + (r.stderr or "")


def read_pose():
    o = orin("timeout 10 ros2 topic echo --once /robot/tcp_pose --field pose 2>/dev/null")
    v = [float(x) for x in re.findall(r"-?\d+\.?\d*(?:e-?\d+)?", o)]
    return np.array(v[:7]) if len(v) >= 7 else None


def read_wrench():
    o = orin("timeout 10 ros2 topic echo --once /robot/force_torque --field wrench 2>/dev/null")
    v = [float(x) for x in re.findall(r"-?\d+\.?\d*(?:e-?\d+)?", o)]
    return np.array(v[:6]) if len(v) >= 6 else None   # fx fy fz tx ty tz


def ang_deg(a, b):
    d = abs(float(np.dot(a, b)) / (np.linalg.norm(a) * np.linalg.norm(b)))
    return float(np.degrees(2 * np.arccos(min(1.0, d))))


def send(pos, quat, sp=SPEED):
    call = ('ros2 service call /move_pose interfaces/srv/TargetPose "{speed: %.1f, joint_state: {name: [], '
            'position: []}, pose: {position: {x: %.7f, y: %.7f, z: %.7f}, '
            'orientation: {x: %.7f, y: %.7f, z: %.7f, w: %.7f}}}"'
            % (sp, pos[0], pos[1], pos[2], quat[0], quat[1], quat[2], quat[3]))
    try:
        orin(call, timeout=90)
    except subprocess.TimeoutExpired:
        pass          # 服务侧超时不影响运动实际执行，靠后续轮询确认


def wait_arrive(pos_t, q_t, max_wait=90):
    t0 = time.time()
    while time.time() - t0 < max_wait:
        p = read_pose()
        if p is not None and float(np.linalg.norm(p[:3] - pos_t)) < 0.0015 and ang_deg(p[3:], q_t) < 1.0:
            return True, p
        time.sleep(4)
    return False, read_pose()


print("══ 基线力（3 次采样）══")
ws = []
for _ in range(3):
    w = read_wrench()
    if w is not None:
        ws.append(w)
    time.sleep(2)
if not ws:
    raise SystemExit("  ✗ 读不到力/力矩，为安全不动作")
base = np.mean(ws, axis=0)
print("  基线 F=(%.2f, %.2f, %.2f)N  T=(%.3f, %.3f, %.3f)Nm" % tuple(base))

p0 = read_pose()
if p0 is None:
    raise SystemExit("  ✗ 读位姿失败")
print()
print("══ 起点 ══")
print("  z=%.5f · 离板面 %+.1f mm" % (p0[2], (p0[2] - BOARD_Z) * 1000))

for i in range(1, NSTEP + 1):
    tgt = p0.copy()
    tgt[2] = p0[2] - STEP * i
    print()
    print("── 第 %d/%d 步: z → %.5f (离板面 %+.1f mm) ──" % (i, NSTEP, tgt[2], (tgt[2] - BOARD_Z) * 1000))
    send(tgt[:3], tgt[3:])
    ok, cur = wait_arrive(tgt[:3], tgt[3:], max_wait=90)
    if not ok:
        print("   ✗ 未在 90s 内到位 ⇒ 停止")
        break
    w = read_wrench()
    if w is None:
        print("   ⚠ 读力失败 ⇒ 为安全停止")
        break
    dz = float(w[2] - base[2])
    dt = float(np.linalg.norm(w[3:] - base[3:]))
    print("   到位 ✓ z=%.5f | Fz=%+.2fN(Δ%+.2f) T=%.3fNm(Δ%.3f)" % (cur[2], w[2], dz, np.linalg.norm(w[3:]), dt))
    if abs(dz) > 5.0 or dt > 2.5:
        print("   🔴 **力/力矩异常（ΔFz=%+.2fN ΔT=%.3fNm）⇒ 立即停止，不再下降**" % (dz, dt))
        break

print()
print("══ 结束 ══")
p = read_pose()
w = read_wrench()
if p is not None:
    print("  最终 z=%.5f · 相对起点 %.1f mm · 离板面 %+.1f mm" % (p[2], (p[2] - p0[2]) * 1000, (p[2] - BOARD_Z) * 1000))
if w is not None:
    print("  最终 F=(%.2f, %.2f, %.2f)N · T=(%.3f, %.3f, %.3f)Nm" % tuple(w))
