#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
moveit_plan_live.py — **容器内常驻** 的 MoveIt plan-only 逐轮规划器 (只规划, 绝不动臂)
────────────────────────────────────────────────────────────────────────────
老倪 2026-09-29: 「起 plan-only 的 move_group 容器，把 /plan_kinematic_path 返回的关节轨迹
                 也镜像成 DDS 一条（ss_plan），能在独立窗口里逐帧对。」

它做什么(每 --interval 秒一轮):
  ① 读 /ws/plans/plan_req.json (宿主机写: 真机当前 jpos/tcp + 目标位姿)
  ② IK(目标) → 用**真机关节角**当起状态 → /plan_kinematic_path 真规划 (RRTConnect)
  ③ 对轨迹每个路点做 FK → TCP 折线 (给叠加层画线; 单位 m, base 系)
  ④ 追加一行到 /ws/plans/live_plan.jsonl (宿主机 zmax-dds-ss 守护读最新一行 → DDS ss_plan)
  ⑤ 同时写 /ws/plans/live_plan_latest.json (人看/审计)

安全: 目标容器是 plan_only.launch.py 起的 move_group, 参数 allow_trajectory_execution=False
      ⇒ 本脚本**不可能**让机器人动; 只调 compute_ik / plan_kinematic_path / compute_fk。
      规划容器独立 ROS_DOMAIN_ID=42, 与产线 domain0 隔离。

用法(容器内):
  python3 /ws/moveit_plan_live.py --interval 3.0 --group arm --base XMS5-R800-W4G3B4C_base \
      --rename-prefix XMS5-R800-W4G3B4C_ --req /ws/plans/plan_req.json \
      --jsonl /ws/plans/live_plan.jsonl --latest /ws/plans/live_plan_latest.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import time

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Pose, Point, Quaternion
from moveit_msgs.srv import GetPositionIK, GetMotionPlan, GetPositionFK
from moveit_msgs.msg import (PositionIKRequest, RobotState, Constraints, JointConstraint,
                             PositionConstraint, OrientationConstraint, BoundingVolume)
from shape_msgs.msg import SolidPrimitive

MAX_LINES = 400          # jsonl 只留最近 N 行, 防无限增长


def _log(m):
    print("%s %s" % (time.strftime("%F %T"), m), flush=True)


class LivePlanner(Node):
    def __init__(self, group, base):
        super().__init__("zmax_moveit_plan_live")
        self.group, self.base = group, base
        self.ik_cli = self.create_client(GetPositionIK, "/compute_ik")
        self.fk_cli = self.create_client(GetPositionFK, "/compute_fk")
        self.mp_cli = self.create_client(GetMotionPlan, "/plan_kinematic_path")
        self._goal_cache = {}

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
        rclpy.spin_until_future_complete(self, fut, timeout_sec=20.0)
        res = fut.result()
        if res is None or res.error_code.val != 1 or not res.pose_stamped:
            return None
        p = res.pose_stamped[0].pose
        return [p.position.x, p.position.y, p.position.z,
                p.orientation.x, p.orientation.y, p.orientation.z, p.orientation.w]

    def plan(self, start_joints, xyz, quat, planner="RRTConnect", tries=10, allow_s=5.0):
        self._wait(self.mp_cli, "/plan_kinematic_path")
        req = GetMotionPlan.Request()
        ms = req.motion_plan_request
        ms.group_name = self.group
        ms.num_planning_attempts = int(tries)
        ms.allowed_planning_time = float(allow_s)
        ms.max_velocity_scaling_factor = 0.2
        ms.max_acceleration_scaling_factor = 0.2
        ms.planner_id = planner
        rs = RobotState()
        rs.joint_state.name = list(start_joints.keys())
        rs.joint_state.position = [float(v) for v in start_joints.values()]
        ms.start_state = rs
        con = Constraints()
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
        rclpy.spin_until_future_complete(self, fut, timeout_sec=max(30.0, allow_s * 4))
        res = fut.result()
        if res is None:
            return None, None
        return (res.motion_plan_response.trajectory.joint_trajectory,
                res.motion_plan_response.error_code.val)


def _read_json(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _trim(path, keep=MAX_LINES):
    """jsonl 只留最近 keep 行 (避免长跑无限增长)"""
    try:
        if not os.path.isfile(path) or os.path.getsize(path) < 4_000_000:
            return
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()[-keep:]
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(lines)
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", default="arm")
    ap.add_argument("--base", default="XMS5-R800-W4G3B4C_base")
    ap.add_argument("--rename-prefix", default="XMS5-R800-W4G3B4C_",
                    help="真机 joint_N → <prefix>joint_N (URDF 与真机命名不同时用)")
    ap.add_argument("--req", default="/ws/plans/plan_req.json")
    ap.add_argument("--jsonl", default="/ws/plans/live_plan.jsonl")
    ap.add_argument("--latest", default="/ws/plans/live_plan_latest.json")
    ap.add_argument("--interval", type=float, default=3.0, help="逐轮规划周期(s)")
    ap.add_argument("--once", action="store_true", help="只跑一轮就退出(取证用)")
    ap.add_argument("--max-rounds", type=int, default=0, help="跑够 N 轮退出(0=不限)")
    a = ap.parse_args()

    os.makedirs(os.path.dirname(a.jsonl) or ".", exist_ok=True)
    rclpy.init()
    n = LivePlanner(a.group, a.base)
    _log("🧭 plan-only 逐轮规划器启动: group=%s base=%s interval=%.1fs req=%s"
         % (a.group, a.base, a.interval, a.req))
    rounds = 0
    last_goal_key = None
    goal_joints = None
    try:
        while True:
            t0 = time.time()
            rq = _read_json(a.req)
            if not rq:
                _log("… 等 %s (宿主机写: 真机 jpos/tcp + goal_xyz/goal_quat)" % a.req)
                time.sleep(1.0)
                continue
            try:
                jpos = [float(x) for x in (rq.get("jpos") or [])][:6]
                if len(jpos) != 6:
                    _log("✗ req.jpos 不是 6 维: %s" % jpos)
                    time.sleep(1.0)
                    continue
                names = ["%sjoint_%d" % (a.rename_prefix, i + 1) for i in range(6)]
                sj = dict(zip(names, jpos))
                goal = [float(x) for x in (rq.get("goal_xyz") or [])][:3]
                gq = [float(x) for x in (rq.get("goal_quat") or [])][:4]
                if len(gq) == 3:      # 示教点省略了 w≈0 → 补 0.0 (与旧跑法一致)
                    gq = gq + [0.0]
                if len(goal) != 3 or len(gq) != 4:
                    _log("✗ req 缺 goal_xyz(3)/goal_quat(4)")
                    time.sleep(1.0)
                    continue
                gkey = tuple(round(v, 6) for v in goal + gq)
                if gkey != last_goal_key:            # 目标变了才重算 IK
                    goal_joints, code = n.ik(goal, gq, seed=sj)
                    last_goal_key = gkey
                    _log("· 目标 IK code=%s → %s" % (code, "ok" if goal_joints else "失败"))
                # 每轮都重算 IK 会白烧算力; 只有目标变了才重算 (上面 gkey 判定)
                fk0 = n.fk(sj)
                d0 = math.dist(fk0[:3], [float(x) for x in (rq.get("tcp") or goal)][:3]) if fk0 else -1.0
                traj, code = n.plan(sj, goal, gq)
                rec = {"ts": time.time(), "source": "moveit_plan_only(live)",
                       "group": a.group, "base_frame": a.base,
                       "start_joints": jpos, "goal_xyz": goal, "goal_quat": gq,
                       "plan_code": int(code if code is not None else -1),
                       "fk_start_pos_err_mm": round(d0 * 1000.0, 3) if d0 >= 0 else -1.0,
                       "req_ts": rq.get("ts"), "frame_age_s": (time.time() - float(rq["ts"]))
                       if rq.get("ts") else -1.0}
                if traj is None or code != 1:
                    rec["n_points"] = -1
                    rec["plan_time_s"] = -1.0
                    rec["note"] = "规划失败 code=%s (目标不可达/超时)" % code
                    _log("✗ 规划失败 code=%s" % code)
                else:
                    nm = list(traj.joint_names)
                    pts = [[float(v) for v in p.positions] for p in traj.points]
                    tcp = []
                    for q in pts:
                        f = n.fk(dict(zip(nm, q)))
                        if f:
                            tcp.append(f)
                    rec.update({
                        "joint_names": nm, "n_points": len(pts),
                        "joints_path": [v for row in pts for v in row],
                        "tcp_path": [v for row in tcp for v in row[:3]],
                        "n_tcp": len(tcp),
                        "plan_time_s": (float(traj.points[-1].time_from_start.sec)
                                        + float(traj.points[-1].time_from_start.nanosec) * 1e-9)
                        if traj.points else -1.0,
                        "end_err_mm": round(math.dist(tcp[-1][:3], goal) * 1000.0, 3) if tcp else -1.0,
                        "note": "plan-only, 未执行"})
                    # 同源闸判据 (FK(真关节) vs 真机 TCP): ≤5mm 才算同源
                    if d0 >= 0:
                        rec["gate_same_source"] = 1 if d0 * 1000.0 <= 5.0 else 0
                        rec["gate_reason"] = ("同源闸: FK(真关节)与真机 TCP 差 %.2fmm" % (d0 * 1000.0)
                                              if d0 * 1000.0 <= 5.0 else
                                              ("同源闸不过: FK(真关节)与真机 TCP 差 %.1fmm (>5mm), "
                                               "关节零位/符号口径与 URDF 不同 → 只可当设计态轨迹"
                                               % (d0 * 1000.0)))
                    _log("✓ %d 关节路点 / %d TCP 路点 · 终点误差 %.2fmm · 时长 %.2fs · FK起点差 %.1fmm"
                         % (len(pts), len(tcp), rec.get("end_err_mm", -1), rec["plan_time_s"],
                            d0 * 1000.0 if d0 >= 0 else -1))
                with open(a.jsonl, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                with open(a.latest, "w", encoding="utf-8") as f:
                    json.dump(rec, f, ensure_ascii=False)
                _trim(a.jsonl)
            except Exception as e:                                       # noqa: BLE001
                _log("⚠️ 本轮异常: %s: %s" % (type(e).__name__, str(e)[:160]))
            rounds += 1
            if a.once or (a.max_rounds and rounds >= a.max_rounds):
                _log("· 跑够 %d 轮, 退出" % rounds)
                break
            dt = a.interval - (time.time() - t0)
            if dt > 0:
                time.sleep(dt)
    finally:
        try:
            n.destroy_node()
            rclpy.shutdown()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
