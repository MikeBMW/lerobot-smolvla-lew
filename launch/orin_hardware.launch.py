#!/usr/bin/env python3
"""
Orin Hardware Launch — starts all three Orin hardware nodes.

  1. camera_pub: RGB capture + JPEG compress + publish
  2. joint_state_pub: encoder readings + publish
  3. action_sub: subscribe PC actions + execute motors

Usage (on Jetson Orin):
  cd ros_orin_ws && colcon build && source install/setup.bash && cd ..
  ros2 launch launch/orin_hardware.launch.py
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    use_dummy_arg = DeclareLaunchArgument(
        "use_dummy",
        default_value="true",
        description="Use dummy sensor data (true) or real hardware (false)",
    )
    num_joints_arg = DeclareLaunchArgument(
        "num_joints",
        default_value="6",
        description="Number of robot arm joints",
    )

    use_dummy = LaunchConfiguration("use_dummy")
    num_joints = LaunchConfiguration("num_joints")

    camera_pub = Node(
        package="arm_hardware_driver",
        executable="camera_pub",
        name="camera_publisher",
        output="screen",
        parameters=[{"use_dummy": use_dummy}],
    )

    joint_pub = Node(
        package="arm_hardware_driver",
        executable="joint_state_pub",
        name="joint_state_publisher",
        output="screen",
        parameters=[{
            "use_dummy": use_dummy,
            "num_joints": num_joints,
        }],
    )

    action_exec = Node(
        package="arm_hardware_driver",
        executable="action_sub",
        name="action_subscriber",
        output="screen",
        parameters=[{
            "use_dummy": use_dummy,
            "num_joints": num_joints,
        }],
    )

    return LaunchDescription([
        use_dummy_arg,
        num_joints_arg,
        camera_pub,
        joint_pub,
        action_exec,
    ])
