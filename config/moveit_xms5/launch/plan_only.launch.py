"""MoveIt2 仅规划 (不执行) — 执行交给 Orin SDK 桥 / ROS2 SRV。

⚠️ 2026-09-26 实测踩坑: 不能把 srdf/kinematics/joint_limits 用 `--params-file` 传
   (ros2 params 文件要求 `/**/ros__parameters:` 结构, MoveIt 的 kinematics.yaml 是 MoveIt 格式 → rcl 解析失败)。
   正确做法: SRDF 传字符串参数 `robot_description_semantic`, 其余作为**嵌套 dict 参数**注入。
"""
import os

import yaml
from launch import LaunchDescription
from launch_ros.actions import Node


def _load(p):
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)


def generate_launch_description():
    cfg = os.environ.get("ZMAX_MOVEIT_CFG", "/ws/moveit_cfg")
    urdf = open(os.path.join(cfg, "urdf", "xms5_r800_w4g3b4c.urdf"), encoding="utf-8").read()
    # 🐛 MESH_FIX 2026-09-26: URDF 里 mesh 是**相对路径**(meshes/...), 而 URDF 作为字符串参数传入时
    #    相对路径按进程 CWD 解析 → 容器内找不到 (冒烟实测 7 个 mesh 报错)。改为**绝对路径**。
    urdf = urdf.replace('filename="meshes/', 'filename="%s/urdf/meshes/' % cfg)
    srdf = open(os.path.join(cfg, "config", "xms5_r800_w4g3b4c.srdf"), encoding="utf-8").read()
    kin = _load(os.path.join(cfg, "config", "kinematics.yaml"))
    lim = _load(os.path.join(cfg, "config", "joint_limits.yaml"))
    ompl = _load(os.path.join(cfg, "config", "ompl_planning.yaml"))
    moveit_params = {
        "robot_description": urdf,
        "robot_description_semantic": srdf,
        "robot_description_kinematics": kin,
        "robot_description_planning": lim,
        "planning_pipelines": ["ompl"],
        "ompl": ompl,
        "use_sim_time": False,
        "allow_trajectory_execution": False,      # 仅规划: 绝不执行 (执行由 SDK 桥/ROS2 SRV 收口)
        "publish_planning_scene": True,
    }
    return LaunchDescription([
        Node(package="robot_state_publisher", executable="robot_state_publisher",
             parameters=[{"robot_description": urdf}], output="log"),
        Node(package="moveit_ros_move_group", executable="move_group", output="screen",
             parameters=[moveit_params]),
    ])
