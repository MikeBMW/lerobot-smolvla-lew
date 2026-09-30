#!/usr/bin/env bash
# 恢复 Orin 相机节点 realsense_source: 先找厂商原参数, 再带同样环境/参数起回来
set +u
ROOT=/home/tashan/0810/tashan_robot_so_20260807_174920_6983506_aarch64
source /opt/ros/humble/setup.bash 2>/dev/null
for ws in /home/tashan/0810/*/install/setup.bash; do [ -f "$ws" ] && source "$ws" && break; done
export ROS_DOMAIN_ID=0

echo "-- 1) 厂商 launch 留下的 params 文件(找相机那份) --"
for f in $(ls -t /tmp/launch_params_* 2>/dev/null | head -12); do
  if grep -qiE "realsense|color_fps|depth_fps|camera" "$f" 2>/dev/null; then
    echo "     ★ $f"; sed -n '1,12p' "$f" | sed 's/^/        /'
  fi
done
echo "     (以上为空 ⇒ 用节点默认参数)"

echo "-- 2) 找不到就用可执行文件自带默认 --"
BIN="$ROOT/install/camera/lib/camera/realsense_source"
ls -l "$BIN" 2>/dev/null | sed 's/^/     /'

echo "-- 3) 启动(脱离会话; 参数与厂商 launch 一致) --"
PARAMS=$(for f in $(ls -t /tmp/launch_params_* 2>/dev/null | head -12); do
  grep -qiE "realsense|color_fps|depth_fps" "$f" 2>/dev/null && { echo "$f"; break; }
done)
cat > /tmp/start_realsense.sh <<EOS
#!/usr/bin/env bash
source /opt/ros/humble/setup.bash
for ws in /home/tashan/0810/*/install/setup.bash; do [ -f "\$ws" ] && source "\$ws" && break; done
export ROS_DOMAIN_ID=0
exec "$BIN" --ros-args -r __node:=realsense_source \${PARAMS:+--params-file "$PARAMS"}
EOS
chmod +x /tmp/start_realsense.sh
setsid nohup /tmp/start_realsense.sh > /tmp/realsense_source.log 2>&1 < /dev/null &
sleep 14

echo "-- 4) 验证: 话题是否真出数据(6 秒) --"
timeout 9 ros2 topic hz /realsense/color/image_raw 2>&1 | grep -vE "SHM|RTPS_TRANSPORT|^$" | head -3 | sed 's/^/     /'

echo "-- 5) 验证: 我的桥(n 必须涨) --"
curl -s --max-time 8 http://127.0.0.1:8792/st | sed 's/^/     /'
echo

echo "-- 6) 日志尾 --"
tail -6 /tmp/realsense_source.log | sed 's/^/     /'
echo "-- 7) 进程 --"
ps -eo pid,etimes,pcpu,args 2>/dev/null | grep -i "realsense_source" | grep -v grep | cut -c1-140 | sed 's/^/     /'
exit 0
