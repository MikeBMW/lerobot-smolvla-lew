#!/usr/bin/env bash
# 最终确认: 是否所有图像话题都没数据(排除"它换了话题名"); 并看 realsense_source 进程状态
set +u
source /opt/ros/humble/setup.bash
for ws in /home/tashan/0810/*/install/setup.bash; do [ -f "$ws" ] && source "$ws" && break; done
export ROS_DOMAIN_ID=0
export FASTRTPS_DEFAULT_PROFILES_FILE=/tmp/fastdds_udp_only.xml

echo "-- 1) 所有图像/点云话题, 逐个看有没有发布者与数据 --"
for t in $(ros2 topic list 2>/dev/null | grep -iE "image|points|color|depth" ); do
  pub=$(ros2 topic info "$t" 2>/dev/null | grep -oE "Publisher count: [0-9]+" | head -1)
  printf "     %-46s %s\n" "$t" "${pub:-?}"
done

echo "-- 2) 对最可能的两个话题各测 6 秒有没有消息 --"
for t in /realsense/color/image_raw /camera/color/image_raw; do
  printf "     %-42s " "$t"
  out=$(timeout 7 ros2 topic hz "$t" 2>&1 | grep -vE "SHM|RTPS_TRANSPORT|^$" | head -2 | tr '\n' ' ')
  echo "${out:-(6 秒内无任何消息)}"
done

echo "-- 3) realsense_source 进程(全字段, 不用 head 截断) --"
ps -eo pid,etimes,pcpu,pmem,stat,args 2>/dev/null | grep -i "realsense_source" | grep -v grep | cut -c1-200 | sed 's/^/     /'
echo "     (若上面为空 ⇒ 进程真的不在了)"

echo "-- 4) 相机被谁打开(USB 占用) --"
lsusb -t 2>/dev/null | grep -iE "uvc|video|Class=Video" | head -4 | sed 's/^/     /'
fuser -v /dev/video* 2>&1 | head -6 | sed 's/^/     /'
exit 0
