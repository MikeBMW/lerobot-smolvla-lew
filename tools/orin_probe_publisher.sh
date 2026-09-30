#!/usr/bin/env bash
# 判定: 厂商 realsense 发布者究竟有没有在真发帧(只读)
set +u   # ROS setup.bash 内有未绑定变量, 不能开 set -u
source /opt/ros/humble/setup.bash
for ws in /home/tashan/0810/*/install/setup.bash; do [ -f "$ws" ] && source "$ws" && break; done
export ROS_DOMAIN_ID=0
export FASTRTPS_DEFAULT_PROFILES_FILE=/tmp/fastdds_udp_only.xml

echo "-- 1) 节点表里有哪些相机/感知节点(不在表里 = 已从图里退出) --"
ros2 node list 2>/dev/null | grep -iE "realsense|camera|rs_|d405|img" | head -10 || echo "     (无)"

echo "-- 2) 发布者端点全信息(含 QoS) --"
ros2 topic info /realsense/color/image_raw -v 2>/dev/null | grep -iE "publisher|node name|reliability|durability|count" | head -12 || echo "     (取不到)"

echo "-- 3) 第三方订阅实测 10 秒(有没有消息真到达) --"
timeout 12 ros2 topic hz /realsense/color/image_raw 2>&1 | grep -vE "SHM|RTPS_TRANSPORT" | head -5

echo "-- 4) 能否真收到一条消息(取 header 即可) --"
timeout 15 ros2 topic echo --once /realsense/color/image_raw --field header 2>&1 | grep -vE "SHM|RTPS_TRANSPORT" | head -8

echo "-- 5) 相机进程在不在、CPU 多少(挂死常表现为占核不干活) --"
ps -eo pid,etimes,pcpu,pmem,comm,args --sort=-pcpu 2>/dev/null | grep -iE "realsense|camera|node" | grep -v grep | head -8 | sed 's/^/     /'

echo "-- 6) 话题带宽(=发帧体积速率, 0 就是没发) --"
timeout 10 ros2 topic bw /realsense/color/image_raw 2>&1 | grep -vE "SHM|RTPS_TRANSPORT" | head -4
exit 0
