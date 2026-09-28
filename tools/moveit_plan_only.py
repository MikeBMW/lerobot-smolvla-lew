#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
moveit_plan_only.py — **只规划、不执行** 的 MoveIt2 规划入口 (老倪 2026-09-29)
──────────────────────────────────────────────────────────────
背景: 状态空间画布里 🧭 MoveIt 节点(n_moveit) 是"最后一级执行", 但一直没有 plan-only 客户端 ⇒
      轨迹线只能手写替代。本脚本补上这个入口: 调 move_group 的 IK / 规划 / FK 服务, 输出
      **TCP 位姿折线**(给叠加层画线) + 关节轨迹(留证)。

安全: 目标容器是 plan_only.launch.py 起的 move_group, 其参数含 allow_trajectory_execution=False
      ⇒ 本脚本**不可能**让机器人动; 只调 compute_ik / plan_kinematic_path / compute_fk。

用法(容器内):
  python3 moveit_plan_only.py --group arm --base XMS5-R800-W4G3B4C_base \
      --start-xyz 0.51268 0.2706 0.21822 --start-quat -0.02314 0.99795 -0.04317 -0.04113 \
      --goal-xyz  0.64736 0.20593 0.10769 --goal-quat 0.738262 0.019596 0.674223 0.0 \
      --out /out/plan_slot7.json
quat 一律 (x, y, z, w) —— 与 /robot/tcp_pose(PoseStamped) 同口径。
"""
import argparse, json, math, sys, time

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Pose, Point, Quaternion
from moveit_msgs.srv import GetPositionIK, GetMotionPlan, GetPositionFK
from moveit_msgs.msg import PositionIKRequest, RobotState, Constraints, JointConstraint, PositionConstraint, OrientationConstraint, BoundingVolume
from shape_msgs.msg import SolidPrimitive


class Planner(Node):
    def __init__(self, group, base):
        super().__init__("zmax_moveit_plan_only")
        self.group, self.base = group, base
        self.ik_cli = self.create_client(GetPositionIK, "/compute_ik")
        self.fk_cli = self.create_client(GetPositionFK, "/compute_fk")
        self.mp_cli = self.create_client(GetMotionPlan, "/plan_kinematic_path")

    def _wait(self, c, name, timeout=30.0):
        t0 = time.time()
        while not c.wait_for_service(timeout_sec=1.0):
            if time.time() - t0 > timeout:
                raise RuntimeError("服务不可用: %s" % name)
        return c

    def _pose(self, xyz, quat):
        p = Pose()
        p.position = Point(x=float(xyz[0]), y=float(xyz[1]), z=float(xyz[2]))
        q = [float(v) for v in quat]
        n = math.sqrt(sum(v * v for v in q)) or 1.0
        p.orientation = Quaternion(x=q[0] / n, y=q[1] / n, z=q[2] / n, w=q[3] / n)
        return p

    def ik(self, xyz, quat, seed=None):
        self._wait(self.ik_cli, "/compute_ik")
        req = GetPositionIK.Request()
        r = PositionIKRequest()
        r.group_name = self.group
        r.pose_stamped.header.frame_id = self.base
        r.pose_stamped.pose = self._pose(xyz, quat)
        r.avoid_collisions = True
        r.ik_link_name = ""
        if seed:
            rs = RobotState()
            rs.joint_state.name = list(seed.keys())
            rs.joint_state.position = [float(v) for v in seed.values()]
            r.robot_state = rs
        req.ik_request = r
        fut = self.ik_cli.call_async(req)
        rclpy.spin_until_future_complete(self, fut, timeout_sec=30.0)
        res = fut.result()
        if res is None or res.error_code.val != 1:
            return None, (res.error_code.val if res else None)
        js = res.solution.joint_state
        return dict(zip(js.name, js.position)), 1

    def fk(self, joints):
        self._wait(self.fk_cli, "/compute_fk")
        req = GetPositionFK.Request()
        req.header.frame_id = self.base
        req.fk_link_names = ["tool0"]
        rs = RobotState()
        rs.joint_state.name = list(joints.keys())
        rs.joint_state.position = [float(v) for v in joints.values()]
        req.robot_state = rs
        fut = self.fk_cli.call_async(req)
        rclpy.spin_until_future_complete(self, fut, timeout_sec=30.0)
        res = fut.result()
        if res is None or res.error_code.val != 1 or not res.pose_stamped:
            return None
        p = res.pose_stamped[0].pose
        return [p.position.x, p.position.y, p.position.z,
                p.orientation.x, p.orientation.y, p.orientation.z, p.orientation.w]

    def plan(self, start_joints, xyz, quat, planner="RRTConnect", tries=20):
        self._wait(self.mp_cli, "/plan_kinematic_path")
        req = GetMotionPlan.Request()
        ms = req.motion_plan_request
        ms.group_name = self.group
        ms.num_planning_attempts = int(tries)
        ms.allowed_planning_time = 10.0
        ms.max_velocity_scaling_factor = 0.2
        ms.max_acceleration_scaling_factor = 0.2
        ms.planner_id = planner
        rs = RobotState()
        rs.joint_state.name = list(start_joints.keys())
        rs.joint_state.position = [float(v) for v in start_joints.values()]
        ms.start_state = rs
        con = Constraints()
        jc = JointConstraint()
        jc.joint_name = "__goal_pose_via_ik__"
        pc = PositionConstraint()
        pc.header.frame_id = self.base
        pc.link_name = "tool0"
        bv = BoundingVolume()
        sp = SolidPrimitive()
        sp.type = SolidPrimitive.SPHERE
        sp.dimensions = [0.005]
        bv.primitives = [sp]
        bv.primitive_poses = [self._pose(xyz, quat)]
        pc.constraint_region = bv
        pc.weight = 1.0
        oc = OrientationConstraint()
        oc.header.frame_id = self.base
        oc.link_name = "tool0"
        oc.orientation = self._pose(xyz, quat).orientation
        oc.absolute_x_axis_tolerance = 0.05
        oc.absolute_y_axis_tolerance = 0.05
        oc.absolute_z_axis_tolerance = 0.05
        oc.weight = 1.0
        con.position_constraints = [pc]
        con.orientation_constraints = [oc]
        ms.goal_constraints = [con]
        fut = self.mp_cli.call_async(req)
        rclpy.spin_until_future_complete(self, fut, timeout_sec=60.0)
        res = fut.result()
        if res is None:
            return None, None
        code = res.motion_plan_response.error_code.val
        traj = res.motion_plan_response.trajectory.joint_trajectory
        return (traj, code)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", default="arm")
    ap.add_argument("--base", default="XMS5-R800-W4G3B4C_base")
    ap.add_argument("--start-xyz", nargs=3, type=float, required=True)
    ap.add_argument("--start-quat", nargs=4, type=float, required=True)
    ap.add_argument("--goal-xyz", nargs=3, type=float, required=True)
    ap.add_argument("--goal-quat", nargs=4, type=float, required=True)
    ap.add_argument("--start-joints", default="", help="真机关节角 JSON {name:val}(给了就用它做起状态, 不从 IK 猜)")
    ap.add_argument("--rename-prefix", default="", help="真机 joint_N → <prefix>joint_N 的改名前缀(URDF 与真机命名不同时用)")
    ap.add_argument("--out", default="/out/plan.json")
    a = ap.parse_args()

    rclpy.init()
    n = Planner(a.group, a.base)
    out = {"group": a.group, "base": a.base, "quat_order": "xyzw",
           "start_req": list(a.start_xyz) + list(a.start_quat),
           "goal_req": list(a.goal_xyz) + list(a.goal_quat)}
    try:
        if a.start_joints:
            _raw = {k: float(v) for k, v in json.loads(a.start_joints).items() if k}
            if a.rename_prefix:
                _raw = {("%s%s" % (a.rename_prefix, k)) if k.startswith("joint_") else k: v
                        for k, v in _raw.items()}
                out["renamed_start_joints"] = sorted(_raw.keys())
            sj = _raw
            code = 0
            print("· 起状态 = 真机关节角(%d 轴), 不走 IK" % len(sj))
        else:
            sj, code = n.ik(a.start_xyz, a.start_quat)
        out["start_from_real_joints"] = bool(a.start_joints)
        out["start_ik_ok"] = sj is not None
        out["start_ik_code"] = code
        if sj is None:
            print("✗ 起点 IK 失败 code=%s" % code); print(json.dumps(out, ensure_ascii=False)); return 2
        out["start_joints"] = {k: float(v) for k, v in sj.items() if v}
        fk0 = n.fk(sj)
        out["fk_start_tcp"] = fk0
        if fk0:
            d = math.dist(fk0[:3], [float(v) for v in a.start_xyz])
            out["fk_start_pos_err_mm"] = round(d * 1000.0, 3)
            print("✓ 起点 IK 成功; FK 回算位置误差 %.3f mm (拿它验 URDF/基座系是否与真机同源)" % (d * 1000.0))
        gj, code = n.ik(a.goal_xyz, a.goal_quat, seed=sj)
        out["goal_ik_ok"] = gj is not None
        out["goal_ik_code"] = code
        if gj is None:
            print("✗ 目标 IK 失败 code=%s (目标不可达/姿态不合适)" % code)
            print(json.dumps(out, ensure_ascii=False)); return 3
        out["goal_joints"] = {k: float(v) for k, v in gj.items() if v}
        fkg = n.fk(gj)
        out["fk_goal_tcp"] = fkg
        traj, code = n.plan(sj, a.goal_xyz, a.goal_quat)
        out["plan_code"] = code
        if traj is None or code != 1:
            print("✗ 规划失败 code=%s" % code); print(json.dumps(out, ensure_ascii=False)); return 4
        names = list(traj.joint_names)
        pts = [[float(v) for v in p.positions] for p in traj.points]
        out["joint_names"] = names
        out["n_waypoints"] = len(pts)
        out["joint_trajectory"] = pts
        out["time_from_start"] = [float(p.time_from_start.sec) + float(p.time_from_start.nanosec) * 1e-9
                                  for p in traj.points]
        # FK 每个路点 ⇒ TCP 折线(叠加层画线用)
        tcp = []
        for k, q in enumerate(pts):
            f = n.fk(dict(zip(names, q)))
            if f:
                tcp.append(f)
        out["tcp_path"] = tcp
        out["n_tcp"] = len(tcp)
        print("✓ 规划成功: %d 个关节路点 / %d 个 TCP 路点 / 用时 %.2fs" %
              (len(pts), len(tcp), out["time_from_start"][-1] if out["time_from_start"] else -1))
        if tcp:
            print("  TCP 起点 %s" % [round(v, 4) for v in tcp[0][:3]])
            print("  TCP 终点 %s  (目标请求 %s)" % ([round(v, 4) for v in tcp[-1][:3]], list(a.goal_xyz)))
            print("  末端位置误差 %.3f mm" % (math.dist(tcp[-1][:3], list(a.goal_xyz)) * 1000.0))
    finally:
        try:
            import os
            os.makedirs(os.path.dirname(a.out), exist_ok=True)
            with open(a.out, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=1)
            print("已写出: %s" % a.out)
        except Exception as e:
            print("写文件失败: %s" % e)
        n.destroy_node(); rclpy.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
