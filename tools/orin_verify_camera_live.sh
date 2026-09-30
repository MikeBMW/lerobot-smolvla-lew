#!/usr/bin/env bash
# 判定 Orin 相机当前到底在不在真采集: ① n 是否增长 ② 与 21:17 那张冻结旧帧是否不同
set +u
echo "-- 1) 桥的帧计数 n 连采 3 次(10 秒内应涨 ~150) --"
for i in 1 2 3; do
  printf "     "; curl -s --max-time 6 http://127.0.0.1:8792/st; echo
  sleep 4
done

echo "-- 2) 旧冻结帧(21:17 那张) vs 现在这张 --"
if [ -f /tmp/f.jpg ]; then
  md5sum /tmp/f.jpg | awk '{print "     旧(/tmp/f.jpg)  "$1"  "$2}'
  ls -l /tmp/f.jpg | awk '{print "                     "$5"B  "$6" "$7" "$8}'
fi
curl -s --max-time 8 -o /tmp/new_now.jpg http://127.0.0.1:8792/frame.jpg
md5sum /tmp/new_now.jpg | awk '{print "     新(现在)      "$1}'
ls -l /tmp/new_now.jpg | awk '{print "                     "$5"B  "$6" "$7" "$8}'
if [ -f /tmp/f.jpg ] && cmp -s /tmp/f.jpg /tmp/new_now.jpg; then
  echo "     ⇒ ✗ 与旧帧完全相同 = 仍在吐缓存旧文件"
else
  echo "     ⇒ ✓ 与旧帧不同 = 是真采集的新画面"
fi

echo "-- 3) 相机节点是否还在、有没有报错 --"
ps -eo pid,etimes,pcpu,args 2>/dev/null | grep -i "realsense_source" | grep -v grep | cut -c1-120 | sed 's/^/     /'
tail -4 /tmp/realsense_source.log | sed 's/^/     /'

echo "-- 4) 话题实测帧率(6 秒) --"
export ROS_DOMAIN_ID=0
source /opt/ros/humble/setup.bash 2>/dev/null
for ws in /home/tashan/0810/*/install/setup.bash; do [ -f "$ws" ] && source "$ws" && break; done
timeout 9 ros2 topic hz /realsense/color/image_raw 2>&1 | grep -vE "SHM|RTPS_TRANSPORT|^$" | head -3 | sed 's/^/     /'
exit 0
