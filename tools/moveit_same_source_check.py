#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
moveit_same_source_check.py — **决定性校验**: MoveIt(URDF) 的 FK 与真机 TCP 是否同源
────────────────────────────────────────────────────────────
老倪 2026-09-29: 「轨迹线应该是状态空间工程里 moveit 节点规划出来的」——
  MoveIt 能规划 ≠ 它规划的线能贴到真机画面上。判据只有一条(不猜):
    拿**真机 6 个关节角**喂 MoveIt 的 /compute_fk ⇒ 得到它模型里的 TCP
    与真机 /robot/tcp_pose **比位置(mm) + 姿态(deg)**
  误差在 mm 级 ⇒ 同源, 可以画; 差一大截 ⇒ 不同源, 它的轨迹只是"它自己模型里"的。

跑在 **zmax-moveit 容器**(domain 42)里, 输入 = moveit_real_state_probe.py 抓的真机状态:
    sudo docker cp reports/moveit/real_state.json zmax-moveit:/ws/real_state.json
    sudo docker exec zmax-moveit bash -lc 'source /opt/ros/humble/setup.bash && \
        python3 /ws/moveit_plan_only.py --help'   # (规划用)
    sudo docker exec zmax-moveit bash -lc 'source /opt/ros/humble/setup.bash && \
        python3 /ws/moveit_same_source_check.py --state /ws/real_state.json \
        --rename-prefix XMS5-R800-W4G3B4C_ --out /ws/out/same_source_check.json'

坑(实测): 关节名 URDF 侧是 XMS5-R800-W4G3B4C_joint_N, 真机是 joint_N —— 名字不对会打崩
          move_group 的 computeFKService(服务随后消失), 所以必须先改名再用。
"""
import argparse
import json
import math
import time

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Pose
from moveit_msgs.srv import GetPositionFK
from moveit_msgs.msg import RobotState
from sensor_msgs.msg import JointState


def quat_dist_deg(a, b):
    """两个 (x,y,z,w) 四元数的夹角(度): 2*acos(|dot|)"""
    d = abs(sum(x * y for x, y in zip(a, b)))
    d = max(-1.0, min(1.0, d))
    return math.degrees(2.0 * math.acos(d))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True, help="moveit_real_state_probe.py 输出的 JSON")
    ap.add_argument("--fk-link", default="tool0", help="FK 的末端 link(SRDF 里 arm 组末端)")
    ap.add_argument("--base", default="XMS5-R800-W4G3B4C_base", help="FK 参考系(frame_id)")
    ap.add_argument("--rename-prefix", default="", help="真机 joint_N → <prefix>joint_N")
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--out", default="same_source_check.json")
    a = ap.parse_args()

    st = json.load(open(a.state, encoding="utf-8"))
    real_joints = st["joints"]
    real_tcp = st["tcp_pose_xyzw"]

    rclpy.init()
    n = Node("zmax_moveit_same_source_check")
    cli = n.create_client(GetPositionFK, "/compute_fk")
    if not cli.wait_for_service(timeout_sec=a.timeout):
        print("❌ /compute_fk 不可用 —— move_group 是不是崩了? "
              "(容器内: ps aux | grep move_group)")
        return 2

    names = [(a.rename_prefix + k) if a.rename_prefix else k for k in sorted(real_joints)]
    req = GetPositionFK.Request()
    req.header.frame_id = a.base
    req.fk_link_names = [a.fk_link]
    req.robot_state = RobotState()
    req.robot_state.joint_state = JointState()
    req.robot_state.joint_state.name = names
    req.robot_state.joint_state.position = [float(real_joints[k]) for k in sorted(real_joints)]

    fut = cli.call_async(req)
    t0 = time.time()
    while not fut.done() and time.time() - t0 < a.timeout:
        rclpy.spin_once(n, timeout_sec=0.5)
    if not fut.done():
        print("❌ FK 调用超时")
        return 3
    res = fut.result()
    n.destroy_node()
    rclpy.shutdown()

    if not res.pose_stamped or res.error_code.val != 1:
        print("❌ FK 失败: error_code=%s" % res.error_code.val)
        return 4
    p, q = res.pose_stamped[0].pose.position, res.pose_stamped[0].pose.orientation
    fk = [p.x, p.y, p.z, q.x, q.y, q.z, q.w]
    dpos = math.dist(fk[:3], real_tcp[:3])
    dang = quat_dist_deg(fk[3:7], real_tcp[3:7])

    verdict = "同源(可画)" if (dpos < 0.005 and dang < 2.0) else "不同源(不能贴到真机画面)"
    out = {
        "check": "FK(MoveIt URDF, 真机关节角) vs 真机 /robot/tcp_pose",
        "frame": a.base, "fk_link": a.fk_link, "rename_prefix": a.rename_prefix,
        "real_joints": real_joints, "real_joints_source": st.get("source"),
        "fk_tcp": fk, "real_tcp": real_tcp,
        "pos_err_mm": round(dpos * 1000.0, 2), "ori_err_deg": round(dang, 3),
        "verdict": verdict,
        "criteria": "pos<5mm 且 ori<2° ⇒ 同源",
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    json.dump(out, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("── FK(真关节) vs 真机 TCP ──")
    print("  FK   = [%s]" % ", ".join("%.5f" % v for v in fk))
    print("  真机 = [%s]" % ", ".join("%.5f" % v for v in real_tcp))
    print("  ⇒ 位置差 %.1f mm · 姿态差 %.2f° ⇒ **%s**" % (dpos * 1000.0, dang, verdict))
    print("  已写 %s" % a.out)
    return 0 if dpos < 0.005 else 5


if __name__ == "__main__":
    raise SystemExit(main())
