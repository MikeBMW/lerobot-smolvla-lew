#!/bin/bash
# 在 4060 侧容器里为 x86_64 生成现场 interfaces 子集 (只需一次; 产物在 /ws/install)
# 用法: sudo docker run --rm --network host -v <repo>/tools/ros2_interfaces:/ws ros:humble-ros-base bash /ws/build_x86.sh
set -e
source /opt/ros/humble/setup.bash
echo "=== 装 rosidl 生成器 (容器内, 属 4060 侧, Orin 不动) ==="
apt-get update -qq
apt-get install -y -qq ros-humble-rosidl-default-generators ros-humble-sensor-msgs \
                       ros-humble-geometry-msgs ros-humble-std-msgs python3-colcon-common-extensions >/dev/null
echo "=== colcon build interfaces (仅 srv 子集) ==="
cd /ws
colcon build --packages-select interfaces --cmake-args -DCMAKE_BUILD_TYPE=Release 2>&1 | tail -8
echo "=== 验证生成的 Python 模块 ==="
source /ws/install/setup.bash
python3 - <<'PY'
from interfaces.srv import HmiSnapshot, HmiCommand, CameraData
print("✅ HmiSnapshot :", HmiSnapshot.Request(), HmiSnapshot.Response(success=True, message="ok", snapshot_json="{}"))
print("✅ HmiCommand  :", HmiCommand.Request(command="x"))
print("✅ CameraData  :", CameraData.Request(camera_id=0))
PY
