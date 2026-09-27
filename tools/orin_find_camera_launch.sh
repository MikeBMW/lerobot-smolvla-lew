#!/usr/bin/env bash
# 找厂商相机 launch 并看它平时怎么起(只读, 不改任何东西)
set +u
source /opt/ros/humble/setup.bash 2>/dev/null
ROOT=/home/tashan/0810/tashan_robot_so_20260807_174920_6983506_aarch64

echo "-- 1) camera 包里的 launch 文件 --"
find "$ROOT/install/camera" "$ROOT/src" -name "*.launch.py" -o -name "*.launch" 2>/dev/null | grep -iE "camera|realsense" | head -8 | sed 's/^/     /'

echo "-- 2) 谁在引用 realsense_source(找启动点) --"
grep -rl "realsense_source" "$ROOT/src" "$ROOT/install" 2>/dev/null | head -8 | sed 's/^/     /'

echo "-- 3) 有没有总 launch / systemd 托管(决定我该不该手动起) --"
ls "$ROOT"/src/*/launch/*.launch.py 2>/dev/null | head -5 | sed 's/^/     /'
systemctl list-units --type=service --state=running 2>/dev/null | grep -iE "tashan|robot|ros|camera" | head -5 | sed 's/^/     /'
crontab -l 2>/dev/null | grep -iE "ros|launch|camera" | head -5 | sed 's/^/     /'

echo "-- 4) 历史上它启动时的参数(从 ros2 daemon 缓存拿不到就用 launch 默认) --"
grep -nE "realsense_source|color_fps|depth_fps|width|height" "$ROOT"/src/*/launch/*camera*.launch.py 2>/dev/null | head -14 | sed 's/^/     /'
exit 0
