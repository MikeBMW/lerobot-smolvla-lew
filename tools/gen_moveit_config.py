#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_moveit_config.py — 由真 URDF 生成 MoveIt2 配置包 (本机规划用; 老倪: MoveIt 装本机, 不动 Orin)

产物 (config/moveit_xms5/): urdf/ · config/{srdf,kinematics,joint_limits,ompl_planning}.yaml · launch/plan_only.launch.py
限位/速度**从 URDF 解析**, 不编造; 组 = 6 轴链 base→tool0; 仅规划 (plan-only), 执行交给 Orin SDK 桥/ROS2 SRV。
"""
from __future__ import annotations

import os
import re
import shutil
import xml.etree.ElementTree as ET

SRC_URDF = "/home/ubuntu/zmax_data/rokae_sdk/urdf/xms5_r800_w4g3b4c.urdf"
DST = "/home/ubuntu/zmax_rel/config/moveit_xms5"
ROBOT = "xms5_r800_w4g3b4c"
JOINTS = ["XMS5-R800-W4G3B4C_joint_%d" % i for i in range(1, 7)]
BASE_LINK = "XMS5-R800-W4G3B4C_base"
TIP_LINK = "tool0"


def main() -> int:
    root = ET.parse(SRC_URDF).getroot()
    limits = {}
    for j in root.findall("joint"):
        name = j.get("name")
        lim = j.find("limit")
        if lim is not None:
            limits[name] = {"lower": float(lim.get("lower", -3.14)), "upper": float(lim.get("upper", 3.14)),
                            "effort": float(lim.get("effort", 100)), "velocity": float(lim.get("velocity", 1.0))}
    os.makedirs(os.path.join(DST, "urdf"), exist_ok=True)
    os.makedirs(os.path.join(DST, "config"), exist_ok=True)
    os.makedirs(os.path.join(DST, "launch"), exist_ok=True)
    shutil.copy2(SRC_URDF, os.path.join(DST, "urdf", ROBOT + ".urdf"))

    # ── SRDF ──
    srdf = ['<?xml version="1.0"?>', '<robot name="%s">' % ROBOT,
            '  <!-- 生成自真 URDF (%s); 仅规划, 执行走 Orin SDK 桥 / ROS2 SRV -->' % os.path.basename(SRC_URDF),
            '  <virtual_joint name="virtual_joint" type="fixed" parent_frame="world" child_link="%s"/>' % BASE_LINK,
            '  <group name="arm">', '    <chain base_link="%s" tip_link="%s"/>' % (BASE_LINK, TIP_LINK), '  </group>',
            '  <group_state name="home" group="arm">']
    for i, jn in enumerate(JOINTS):
        srdf.append('    <joint name="%s" value="0"/>' % jn)
    srdf += ['  </group_state>', '  <end_effector name="tool" parent_link="tool0" group="arm"/>', '</robot>']
    open(os.path.join(DST, "config", ROBOT + ".srdf"), "w", encoding="utf-8").write("\n".join(srdf) + "\n")

    # ── kinematics ──
    open(os.path.join(DST, "config", "kinematics.yaml"), "w", encoding="utf-8").write(
        "arm:\n  kinematics_solver: kdl_kinematics_plugin/KDLKinematicsPlugin\n"
        "  kinematics_solver_search_resolution: 0.005\n  kinematics_solver_timeout: 0.05\n")

    # ── joint_limits (真 URDF 值) ──
    lines = ["joint_limits:"]
    for jn in JOINTS:
        L = limits.get(jn, {})
        lines.append("  %s:" % jn)
        lines.append("    has_velocity_limits: true")
        lines.append("    max_velocity: %.4f" % L.get("velocity", 1.0))
        lines.append("    has_acceleration_limits: true")
        lines.append("    max_acceleration: %.4f" % (L.get("velocity", 1.0) * 0.5))
        lines.append("    has_position_limits: true")
        lines.append("    min_position: %.6f" % L.get("lower", -3.14))
        lines.append("    max_position: %.6f" % L.get("upper", 3.14))
    open(os.path.join(DST, "config", "joint_limits.yaml"), "w", encoding="utf-8").write("\n".join(lines) + "\n")

    # ── ompl_planning ──
    open(os.path.join(DST, "config", "ompl_planning.yaml"), "w", encoding="utf-8").write(
        "planning_plugin: ompl_interface/OMPLPlanner\n"
        "request_adapters: >-\n  default_planner_request_adapters/AddTimeOptimalParameterization\n"
        "  default_planner_request_adapters/ResolveConstraintFrames\n"
        "  default_planner_request_adapters/FixWorkspaceBounds\n"
        "  default_planner_request_adapters/FixStartStateBounds\n"
        "  default_planner_request_adapters/FixStartStateCollision\n"
        "  default_planner_request_adapters/FixStartStatePathConstraints\n"
        "start_state_max_bounds_error: 0.1\nplanner_configs:\n  RRTConnect:\n    type: geometric::RRTConnect\n"
        "arm:\n  default_planner_config: RRTConnect\n  planner_configs:\n    - RRTConnect\n")

    # ── launch (仅规划) ──
    open(os.path.join(DST, "launch", "plan_only.launch.py"), "w", encoding="utf-8").write(
        '"""MoveIt 仅规划 (不执行) — 执行交给 Orin SDK 桥 / ROS2 SRV。"""\n'
        "import os\nfrom launch import LaunchDescription\nfrom launch_ros.actions import Node\n"
        "from ament_index_python.packages import get_package_share_directory\n\n"
        "def generate_launch_description():\n"
        "    cfg = os.environ.get('ZMAX_MOVEIT_CFG', '/ws/moveit_cfg')\n"
        "    urdf = open(os.path.join(cfg, 'urdf', '%s.urdf')).read()\n"
        "    return LaunchDescription([\n"
        "        Node(package='robot_state_publisher', executable='robot_state_publisher',\n"
        "             parameters=[{'robot_description': urdf}]),\n"
        "        Node(package='moveit_ros_move_group', executable='move_group', output='screen',\n"
        "             parameters=[os.path.join(cfg, 'config', '%s.srdf'),\n"
        "                         os.path.join(cfg, 'config', 'kinematics.yaml'),\n"
        "                         os.path.join(cfg, 'config', 'joint_limits.yaml'),\n"
        "                         os.path.join(cfg, 'config', 'ompl_planning.yaml'),\n"
        "                         {'robot_description': urdf, 'use_sim_time': False}]),\n"
        "    ])\n" % (ROBOT, ROBOT))

    print("✅ MoveIt 配置已生成 → %s" % DST)
    print("   关节限位(来自 URDF):")
    for jn in JOINTS:
        L = limits.get(jn, {})
        print("     %-28s [%.4f, %.4f] rad · vmax %.4f rad/s" % (jn, L.get("lower", 0), L.get("upper", 0), L.get("velocity", 0)))
    print("   文件:", sorted(os.listdir(os.path.join(DST, "config"))), "+ urdf/ + launch/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
