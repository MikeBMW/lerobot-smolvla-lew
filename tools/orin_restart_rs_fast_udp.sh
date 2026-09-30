#!/usr/bin/env bash
# 用 UDP-only 传输重启 rs_fast_node —— 绕开 FastRTPS 共享内存端口故障(不碰 /dev/shm)
set -u
echo "-- 1) 写 UDP-only 的 FastRTPS 档(只影响本进程) --"
cat > /tmp/fastdds_udp_only.xml <<'EOS'
<?xml version="1.0" encoding="UTF-8"?>
<profiles xmlns="http://www.eprosima.com/XMLSchemas/fastRTPS_Profiles">
  <transport_descriptors>
    <transport_descriptor>
      <transport_id>udp_only</transport_id>
      <type>UDPv4</type>
    </transport_descriptor>
  </transport_descriptors>
  <participant profile_name="udp_only_participant" is_default_profile="true">
    <rtps>
      <userTransports><transport_id>udp_only</transport_id></userTransports>
      <useBuiltinTransports>false</useBuiltinTransports>
    </rtps>
  </participant>
</profiles>
EOS
ls -l /tmp/fastdds_udp_only.xml | sed 's/^/     /'

echo "-- 2) 停掉现有实例 --"
for p in $(pgrep -f "rs_fast""_node.py"); do kill "$p" 2>/dev/null; done
sleep 3
for p in $(pgrep -f "rs_fast""_node.py"); do kill -9 "$p" 2>/dev/null; done
sleep 2
pgrep -f "rs_fast""_node.py" >/dev/null 2>&1 && echo "     ✗ 还有残留" || echo "     ✓ 已清"

echo "-- 3) 带 ROS 环境 + UDP-only 启动 --"
cat > /tmp/rs_fast_launch.sh <<'EOS'
#!/usr/bin/env bash
source /opt/ros/humble/setup.bash
for ws in /home/tashan/0810/*/install/setup.bash; do [ -f "$ws" ] && source "$ws" && break; done
export ROS_DOMAIN_ID=0
export FASTRTPS_DEFAULT_PROFILES_FILE=/tmp/fastdds_udp_only.xml
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
exec python3 /tmp/rs_fast_node.py
EOS
chmod +x /tmp/rs_fast_launch.sh
setsid nohup /tmp/rs_fast_launch.sh > /tmp/rs_fast_node.log 2>&1 < /dev/null &
sleep 12

echo "-- 4) 三次采样(n 必须持续涨) --"
for i in 1 2 3; do
  printf "     %d) " "$i"; curl -s --max-time 8 http://127.0.0.1:8792/st; echo
  sleep 4
done

echo "-- 5) /frame.jpg 两次 md5(不同 = 真在刷新) --"
curl -s --max-time 8 -o /tmp/a.jpg http://127.0.0.1:8792/frame.jpg; md5sum /tmp/a.jpg | awk '{print "     "$1}'
sleep 2
curl -s --max-time 8 -o /tmp/b.jpg http://127.0.0.1:8792/frame.jpg; md5sum /tmp/b.jpg | awk '{print "     "$1}'
echo "-- 6) 日志尾(有无 SHM 报错) --"
tail -5 /tmp/rs_fast_node.log | sed 's/^/     /'
exit 0
