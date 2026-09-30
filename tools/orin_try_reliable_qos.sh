#!/usr/bin/env bash
# 把桥的订阅 QoS 从 BEST_EFFORT 改成 RELIABLE(大消息丢包重传), 量帧率有无提升
set +u
PAT="rs_fast""_node.py"

echo "-- 1) 备份 + 改 QoS --"
cp /tmp/rs_fast_node.py /tmp/rs_fast_node.py.bak_be 2>/dev/null
sed -i 's/ReliabilityPolicy.BEST_EFFORT/ReliabilityPolicy.RELIABLE/' /tmp/rs_fast_node.py
sed -i 's/depth=2/depth=8/' /tmp/rs_fast_node.py
grep -nE "ReliabilityPolicy|QoSProfile" /tmp/rs_fast_node.py | sed 's/^/     /'

echo "-- 2) 重启桥 --"
for p in $(pgrep -f "$PAT"); do kill "$p" 2>/dev/null; done
sleep 3
for p in $(pgrep -f "$PAT"); do kill -9 "$p" 2>/dev/null; done
sleep 1
setsid nohup /tmp/rs_fast_launch.sh > /tmp/rs_fast_node.log 2>&1 < /dev/null &
sleep 12

echo "-- 3) 量 20 秒帧率(n 的增量 / 秒) --"
n1=$(curl -s --max-time 6 http://127.0.0.1:8792/st | sed -E 's/.*"n":([0-9]+).*/\1/')
sleep 20
n2=$(curl -s --max-time 6 http://127.0.0.1:8792/st | sed -E 's/.*"n":([0-9]+).*/\1/')
echo "     n: $n1 → $n2   ⇒ 实测 $(echo "scale=2; ($n2-$n1)/20" | bc 2>/dev/null || echo "?") fps"
curl -s --max-time 6 http://127.0.0.1:8792/st | sed 's/^/     /'
echo
echo "-- 4) 对照: 同时看话题侧(只读) --"
export ROS_DOMAIN_ID=0
source /opt/ros/humble/setup.bash 2>/dev/null
for ws in /home/tashan/0810/*/install/setup.bash; do [ -f "$ws" ] && source "$ws" && break; done
timeout 9 ros2 topic hz /realsense/color/image_raw 2>&1 | grep -vE "SHM|RTPS_TRANSPORT|^$" | head -2 | sed 's/^/     /'
exit 0
