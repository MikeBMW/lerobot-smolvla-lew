# Z-MAX MoveIt 镜像 (本机 4060 专用; 老倪 2026-09-26: 装本机, **绝不动 Orin 环境**)
# 用途: MoveIt2 规划 (IK/碰撞/轨迹) — 执行仍走 Orin SDK 桥 或 ROS2 SRV (两条后端都不在 Orin 装任何东西)
FROM ros:humble-ros-base

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        ros-humble-moveit \
        ros-humble-moveit-py \
        ros-humble-moveit-setup-assistant \
        ros-humble-robot-state-publisher \
        ros-humble-joint-state-publisher \
        ros-humble-xacro \
        ros-humble-tf2-tools \
        python3-colcon-common-extensions \
        python3-numpy \
    && rm -rf /var/lib/apt/lists/*

# 规划用的 URDF/配置从宿主机挂进来: -v ~/zmax_rel/config/robot:/ws/robot:ro -v <moveit_config>:/ws/moveit_cfg:ro
WORKDIR /ws
CMD ["bash"]
