#!/usr/bin/env python3
# 一次性取证: 把当前规划轨迹逐路点 FK 出来 -> x y z a b c (m / rad, 与真机 tcp_out 同口径)
import json, math, os, sys
import rclpy
from rclpy.node import Node
from moveit_msgs.srv import GetPositionFK
from moveit_msgs.msg import RobotState

d = json.load(open("/ws/plans/live_plan_latest.json"))
NM = list(d["joint_names"]); JP = list(d["joints_path"]); NP = int(d["n_points"])
GQ = list(d.get("goal_quat") or [])

def q2rpy(x, y, z, w):                      # 固定轴 RPY (x-y-z 内旋, 标准 ZYX 分解)
    r = math.atan2(2.0 * (y * z + w * x), 1.0 - 2.0 * (x * x + y * y))
    p = math.asin(max(-1.0, min(1.0, 2.0 * (w * y - z * x))))
    yw = math.atan2(2.0 * (x * y + w * z), 1.0 - 2.0 * (y * y + z * z))
    return r, p, yw

rclpy.init()
n = Node("fk_pose_probe"); n.set_parameters([])
cli = n.create_client(GetPositionFK, "/compute_fk")
if not cli.wait_for_service(timeout_sec=15.0):
    print("✗ /compute_fk 不可用"); sys.exit(1)

def fk(q6):
    req = GetPositionFK.Request()
    req.header.frame_id = d.get("base_frame") or "base"
    req.fk_link_names = ["tool0"]
    rs = RobotState()
    rs.joint_state.name = NM
    rs.joint_state.position = [float(v) for v in q6]
    req.robot_state = rs
    f = cli.call_async(req)
    rclpy.spin_until_future_complete(n, f, timeout_sec=20.0)
    res = f.result()
    if res is None or res.error_code.val != 1 or not res.pose_stamped:
        return None
    p = res.pose_stamped[0].pose
    return (p.position.x, p.position.y, p.position.z,
            p.orientation.x, p.orientation.y, p.orientation.z, p.orientation.w)

idx = [0, NP // 4, NP // 2, (3 * NP) // 4, NP - 1]
print("规划: %s · %d 路点 · plan_code=%s · %s" % (d.get("source"), NP, d.get("plan_code"), d.get("note", "")))
print("goal_xyz = %s m" % [round(v, 4) for v in d["goal_xyz"]])
print()
print("%-6s | %-28s | %s" % ("路点", "x   y   z   (m)", "a   b   c   (rad)"))
print("-" * 78)
for i in idx:
    q6 = JP[i * 6:i * 6 + 6]
    f = fk(q6)
    if not f:
        print("%-6d | FK 失败" % i); continue
    r, p, yw = q2rpy(*f[3:7])
    print("%-6d | %-28s | %s" % (i, " ".join("%8.4f" % v for v in f[:3]), " ".join("%8.4f" % v for v in (r, p, yw))))
if len(GQ) == 4:
    r, p, yw = q2rpy(*GQ)
    print("\n目标姿态 goal_quat -> a b c = %.4f  %.4f  %.4f rad  (= %.2f° %.2f° %.2f°)"
          % (r, p, yw, math.degrees(r), math.degrees(p), math.degrees(yw)))
n.destroy_node(); rclpy.shutdown()
