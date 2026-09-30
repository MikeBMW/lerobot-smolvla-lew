#!/usr/bin/env python3
"""
PC Full Async Launch — starts gRPC policy_server + ROS2 bridge node.

Two processes:
  1. policy_server: LeRobot gRPC async GPU inference (background)
  2. bridge_node: ROS2 ↔ gRPC bridge, subscribes Orin topics, publishes actions

Usage:
  # First build the ROS workspace:
  cd ros_pc_ws && colcon build && source install/setup.bash && cd ..

  # Then launch:
  ros2 launch launch/pc_full_async.launch.py \
      pretrained_name_or_path:=outputs/smolvla_pusht/checkpoint-500
"""

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    ExecuteProcess,
    SetEnvironmentVariable,
)
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    # ── Launch arguments ──
    pretrained_arg = DeclareLaunchArgument(
        "pretrained_name_or_path",
        default_value="",
        description="Path or HuggingFace ID of pretrained SmolVLA model",
    )
    policy_type_arg = DeclareLaunchArgument(
        "policy_type",
        default_value="smolvla",
        description="Policy type (smolvla, act, diffusion, etc.)",
    )
    actions_per_chunk_arg = DeclareLaunchArgument(
        "actions_per_chunk",
        default_value="50",
        description="Number of actions per inference chunk",
    )
    grpc_host_arg = DeclareLaunchArgument(
        "grpc_host",
        default_value="127.0.0.1",
        description="gRPC policy_server host",
    )
    grpc_port_arg = DeclareLaunchArgument(
        "grpc_port",
        default_value="8080",
        description="gRPC policy_server port",
    )
    infer_hz_arg = DeclareLaunchArgument(
        "infer_hz",
        default_value="20.0",
        description="Inference loop frequency (Hz)",
    )

    pretrained_path = LaunchConfiguration("pretrained_name_or_path")
    policy_type = LaunchConfiguration("policy_type")
    actions_per_chunk = LaunchConfiguration("actions_per_chunk")
    grpc_host = LaunchConfiguration("grpc_host")
    grpc_port = LaunchConfiguration("grpc_port")
    infer_hz = LaunchConfiguration("infer_hz")

    # ── Process 1: gRPC policy_server (background) ──
    start_policy_server = ExecuteProcess(
        cmd=[
            "python3",
            "-m", "lerobot.async_inference.policy_server",
            "--host", grpc_host,
            "--port", grpc_port,
            "--fps", "30",
        ],
        output="screen",
        name="smolvla_policy_server",
    )

    # ── Process 2: ROS2-gRPC bridge node ──
    ros_bridge = Node(
        package="smolvla_grpc_bridge",
        executable="bridge_node",
        name="smolvla_grpc_bridge",
        output="screen",
        parameters=[{
            "grpc_host": grpc_host,
            "grpc_port": grpc_port,
            "policy_type": policy_type,
            "pretrained_name_or_path": pretrained_path,
            "actions_per_chunk": actions_per_chunk,
            "infer_hz": infer_hz,
        }],
    )

    return LaunchDescription([
        pretrained_arg,
        policy_type_arg,
        actions_per_chunk_arg,
        grpc_host_arg,
        grpc_port_arg,
        infer_hz_arg,
        start_policy_server,
        ros_bridge,
    ])
