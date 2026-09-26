#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""handeye_collect16.py — 手眼标定采集（双轴版：世界Z偏航 + 世界X倾斜）

为什么必须双轴（前几版失败的确证根因）:
  绕世界Z单轴旋转 ⇒ R_i = Rz(ψ_i)·R_ref ⇒ 相对旋转 R_iᵀR_j 的转轴恒为 R_refᵀ·(0,0,1) ⇒ **恒定** 
  实测: 31 对相对旋转的转轴夹角 中位 0.0° · max 0.0° ⇒ OpenCV 必然退化（5 方法全 NaN/10^7mm）
  ⇒ 手眼标定要求**≥2 条不平行的转轴** ⇒ 必须再加一条 X 向倾斜

安全: /move_pose 指定 TCP 位姿 ⇒ 位置不变只改姿态（零刀尖位移）; 抬高70mm(红线≤90) ⇒ 刀尖离板75mm
稳定性: speed=50(20°偏转实测3s, 旧版speed15要>30s会顶满服务窗口) + 轮询TCP到位才继续 + 绝不重发
"""
import json
import math
import os
import re
import subprocess
import sys
import time

import numpy as np

ORIN = "tashan@192.168.23.66"
PRE = ("source /opt/ros/humble/setup.bash; for ws in /home/tashan/0810/*/install/setup.bash; "
       "do [ -f \"$ws\" ] && source \"$ws\" && break; done; export ROS_DOMAIN_ID=0; ")
REF_POS = np.array([0.53372, 0.23132, 0.22711])
LIFT = 0.000
REF_Q = np.array([0.8114265263133928, 0.0545364276727192, 0.5813654658319766, -0.02503928093312072])
OUT = "/tmp/scene/he17"
SPEED = 50.0


def orin(cmd, timeout=80):
    return subprocess.run(["sshpass", "-p", "ts123", "ssh", "-o", "StrictHostKeyChecking=no",
                           "-o", "ConnectTimeout=8", ORIN, PRE + cmd],
                          capture_output=True, text=True, timeout=timeout)


def qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return np.array([aw * bx + ax * bw + ay * bz - az * by,
                     aw * by - ax * bz + ay * bw + az * bx,
                     aw * bz + ax * by - ay * bx + az * bw,
                     aw * bw - ax * bx - ay * by - az * bz])


def qaxis(axis, deg):
    t = math.radians(deg) / 2.0
    v = np.zeros(3); v["xyz".index(axis)] = 1.0
    return np.array([v[0] * math.sin(t), v[1] * math.sin(t), v[2] * math.sin(t), math.cos(t)])


def send_pose(pos, quat, speed=SPEED):
    call = ('ros2 service call /move_pose interfaces/srv/TargetPose "{speed: %s, joint_state: {name: [], '
            'position: []}, pose: {position: {x: %.7f, y: %.7f, z: %.7f}, '
            'orientation: {x: %.7f, y: %.7f, z: %.7f, w: %.7f}}}"'
            % (speed, pos[0], pos[1], pos[2], quat[0], quat[1], quat[2], quat[3]))
    r = orin(call, timeout=140)
    out = (r.stdout or "") + (r.stderr or "")
    return "success=True" in out.replace(" ", ""), out.strip()[-240:]


def read_pose():
    r = orin("timeout 8 ros2 topic echo --once /robot/tcp_pose --field pose 2>/dev/null", timeout=45)
    v = [float(x) for x in re.findall(r"-?\d+\.?\d*(?:e-?\d+)?", r.stdout or "")]
    return np.array(v[:7]) if len(v) >= 7 else None


def ang_deg(qa, qb):
    d = abs(float(np.dot(qa, qb)) / (np.linalg.norm(qa) * np.linalg.norm(qb)))
    return float(np.degrees(2 * np.arccos(min(1.0, d))))


def wait_target(pos_t, q_t, max_wait=150):
    t0 = time.time()
    last = None
    while time.time() - t0 < max_wait:
        p = read_pose()
        if p is not None:
            last = p
            if float(np.linalg.norm(p[:3] - pos_t)) < 0.0015 and ang_deg(p[3:], q_t) < 1.0:
                return True, p, time.time() - t0
        time.sleep(5)
    return False, last, time.time() - t0


def robot_status():
    r = orin("timeout 10 ros2 topic echo --once /robot_status 2>/dev/null")
    m = re.search(r"has_error\D+(true|false)", r.stdout or "")
    e = re.search(r"error_code\D*\"([^\"]*)\"", r.stdout or "")
    return (m.group(1) if m else "?"), (e.group(1) if e else "?")


def grab(tag):
    subprocess.run(["sshpass", "-p", "ts123", "ssh", "-o", "StrictHostKeyChecking=no", ORIN,
                    "bash /tmp/orin_hires_capture.sh"], capture_output=True, timeout=280)
    for remote, local in (("/tmp/hires_color.png", "%s/c_%s.png" % (OUT, tag)),
                          ("/tmp/hires_depth.npy", "%s/d_%s.npy" % (OUT, tag))):
        subprocess.run(["sshpass", "-p", "ts123", "scp", "-o", "StrictHostKeyChecking=no",
                        "%s:%s" % (ORIN, remote), local], capture_output=True, timeout=130)
    p = read_pose()
    if p is not None:
        open("%s/tcp_%s.txt" % (OUT, tag), "w").write(
            "position:\n  x: %.9f\n  y: %.9f\n  z: %.9f\norientation:\n  x: %.9f\n  y: %.9f\n  z: %.9f\n  w: %.9f\n" % tuple(p))
    f = "%s/c_%s.png" % (OUT, tag)
    return os.path.exists(f) and os.path.getsize(f) > 10000


def verify(tag):
    import cv2
    img = cv2.imread("%s/c_%s.png" % (OUT, tag))
    if img is None:
        return "无图"
    H, W = img.shape[:2]
    g0 = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    for src, off, nm in ((g0[max(0, 281):min(H, 668), max(0, 153):min(W, 768)], np.array([153, 281]), "裁剪"),
                         (g0, np.array([0, 0]), "全图")):
        for z in (2.2, 1.0, 3.0):
            gg = cv2.resize(src, None, fx=z, fy=z, interpolation=cv2.INTER_CUBIC) if z != 1.0 else src
            for pol in (cv2.bitwise_not(gg), gg):
                ok, cc = cv2.findCirclesGrid(pol, (4, 5), flags=cv2.CALIB_CB_ASYMMETRIC_GRID)
                if ok:
                    return "✓%d[%s@%.1fx]" % (len(cc), nm, z)
    return "✗"


os.makedirs(OUT, exist_ok=True)
log = open("%s/collect.log" % OUT, "w")


def P(s):
    print(s); log.write(s + "\n"); log.flush()


P("══ 前置 ══")
he, ec = robot_status()
P("  has_error=%s error_code=%s" % (he, ec))
p0 = read_pose()
P("  起始位姿: %s" % (["%.5f" % v for v in p0] if p0 is not None else "读取失败"))

# ★ 双轴：世界Z偏航(yaw) × 世界X倾斜(tilt) ⇒ 相对转轴不再平行
POSES = [(0, 0), (35, 0), (-35, 0), (0, 14), (0, -14),
         (35, 14), (-35, 14), (35, -14), (-35, -14), (50, 0), (0, 20)]
P("计划 %d 个位姿（世界Z偏航 × 世界X倾斜 ⇒ 双轴）· speed=%.0f" % (len(POSES), SPEED))

results, aborted = [], False
for i, (yaw, tilt) in enumerate(POSES):
    tag = ("y%+03d_t%+03d" % (yaw, tilt)).replace("+", "p").replace("-", "m")
    q = qmul(qmul(qaxis("z", yaw), qaxis("x", tilt)), REF_Q)   # ★ 世界系左乘（z 再 x）
    pos = REF_POS.copy(); pos[2] += LIFT
    ok, msg = send_pose(pos, q)
    arrived, actual, took = wait_target(pos, q, max_wait=150)
    P("[%02d/%02d] %-14s yaw=%+4d tilt=%+3d svc=%s 到位=%s(%.0fs)"
      % (i + 1, len(POSES), tag, yaw, tilt, "T" if ok else "F", "✓" if arrived else "✗", took))
    if not arrived:
        P("      ✗ 未到位(等了 %.0fs): %s" % (took, msg))
        P("      ⇒ 中止（绝不在未到位状态下采数据）")
        aborted = True
        break
    okc = grab(tag)
    v = verify(tag) if okc else "无图"
    time.sleep(12)
    P("        采图=%s 靶标=%s" % ("✓" if okc else "✗", v))
    results.append((tag, yaw, tilt, ok, okc, v))

P("")
P("══ 收尾：回参考位姿 ══")
send_pose(REF_POS, REF_Q)
arr, _, tk = wait_target(REF_POS, REF_Q, max_wait=150)
P("  回位: %s (%.0fs)" % ("✓" if arr else "✗", tk))
he, ec = robot_status()
P("  收尾状态: has_error=%s error_code=%s" % (he, ec))

P("")
P("══ 汇总 ══")
good = [r for r in results if r[5].startswith("✓")]
for r in results:
    P("  %-14s yaw=%+4d tilt=%+3d 图%s 靶标%s" % (r[0], r[1], r[2], "✓" if r[4] else "✗", r[5]))
P("  靶标可检出: %d/%d %s" % (len(good), len(results), "（中途中止）" if aborted else ""))
json.dump([{"tag": r[0], "yaw": r[1], "tilt": r[2], "svc_ok": r[3], "img": r[4], "target": r[5]} for r in results],
          open("%s/summary.json" % OUT, "w"), indent=1)
log.close()
