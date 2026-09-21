#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""l2_pose_rot.py — 手腕原地旋转(位置不变, 只改姿态), 走 /move_pose (与 /move_line 同型 TargetPose)

为什么用它: /target_relative_joint 是 rt 通道, **动作后驱动会把伺服下电**(老倪现场: "怎么又下电了");
/move_line /move_pose 走的是目标位姿通道, 实测不掉电 → 手眼标定需要多姿态, 用它就能免去反复上电。

用法:
  gui-venv311/bin/python tools/l2_pose_rot.py --axis z --deg 20          # 打印将要下发的目标(不下发)
  gui-venv311/bin/python tools/l2_pose_rot.py --axis z --deg 20 --send   # 真下发
  axis: z(绕工具光轴转=画面原地旋转) / x / y(倾侧, 画面会平移)
"""
import argparse
import json
import math
import os
import re
import subprocess
import sys

REPO = "/home/ubuntu/lerobot-smolvla-lew"
ORIN = "tashan@192.168.23.66"
CONTAINER = "ss-remote-tap"
PRE = ("source /opt/ros/humble/setup.bash; for ws in /home/tashan/0810/*/install/setup.bash; "
       "do [ -f \"$ws\" ] && source \"$ws\" && break; done; export ROS_DOMAIN_ID=0; ")
NUM = re.compile(r"-?\d+\.?\d*(?:e-?\d+)?")


def read_pose():
    """读当前 TCP 位姿(经本机 tap 容器, 只读): 返回 (x,y,z,qx,qy,qz,qw)"""
    r = subprocess.run(["sudo", "docker", "exec", CONTAINER, "bash", "-lc",
                        "source /opt/ros/humble/setup.bash; export ROS_DOMAIN_ID=0; "
                        "timeout 6 ros2 topic echo --once /robot/tcp_pose --field pose"],
                       capture_output=True, text=True, timeout=25)
    v = [float(x) for x in NUM.findall(r.stdout)]
    if len(v) < 7:
        raise SystemExit("读位姿失败: %s" % (r.stdout + r.stderr)[-200:])
    return v[:7]


def qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return [aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz]


def axis_q(axis, deg):
    t = math.radians(deg) / 2.0
    s, c = math.sin(t), math.cos(t)
    return {"x": [s, 0.0, 0.0, c], "y": [0.0, s, 0.0, c], "z": [0.0, 0.0, s, c]}[axis]


def qnorm(q):
    n = math.sqrt(sum(x * x for x in q))
    return [x / n for x in q]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--axis", default="z", choices=["x", "y", "z"])
    ap.add_argument("--deg", type=float, default=20.0)
    ap.add_argument("--speed", type=float, default=30.0)
    ap.add_argument("--send", action="store_true", help="不加=只算不下发(dry-run)")
    a = ap.parse_args()

    p = read_pose()
    pos, quat = p[:3], qnorm(p[3:7])
    # 绕**工具自身**轴旋转: R_new = R_cur * R_axis(θ)
    q_new = qnorm(qmul(quat, axis_q(a.axis, a.deg)))
    call = ('ros2 service call /move_pose interfaces/srv/TargetPose "{speed: %s, joint_state: {name: [], '
            'position: []}, pose: {position: {x: %.7f, y: %.7f, z: %.7f}, '
            'orientation: {x: %.7f, y: %.7f, z: %.7f, w: %.7f}}}"'
            % (a.speed, pos[0], pos[1], pos[2], q_new[0], q_new[1], q_new[2], q_new[3]))
    print("当前: pos=[%.4f, %.4f, %.4f] quat=[%.4f, %.4f, %.4f, %.4f]" % tuple(pos + quat))
    print("目标: 绕工具 %s 轴 %+.1f° → quat=[%.4f, %.4f, %.4f, %.4f]" % (a.axis, a.deg, *q_new))
    print("调用: %s" % call[:260])
    if not a.send:
        print("(DRY-RUN, 未下发)")
        return 0
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6", ORIN, PRE + call],
                       capture_output=True, text=True, timeout=45)
    out = (r.stdout or "") + (r.stderr or "")
    ok = "success=True" in out.replace(" ", "")
    print("下发结果: %s" % ("success=True" if ok else out.strip()[-300:]))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
