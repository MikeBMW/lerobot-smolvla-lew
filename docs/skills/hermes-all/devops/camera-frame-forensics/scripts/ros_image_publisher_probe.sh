#!/bin/bash
# ros_image_publisher_probe.sh — 图像话题"一帧都没收到"时的只读取证探针
# 用法:  bash ros_image_publisher_probe.sh <image_topic> [<source_pid>]
#        例: bash ros_image_publisher_probe.sh /realsense/color/image_raw 4694
# 只读: 不发布话题、不调服务、不杀进程 —— 可直接对产线/Orin 设备跑 (ROS_DOMAIN_ID 按现场, 默认 0)
set -u
TOPIC="${1:?用法: ros_image_publisher_probe.sh <image_topic> [pid]}"
PID="${2:-}"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}"
source /opt/ros/humble/setup.bash 2>/dev/null || true
source /opt/ros/"${ROS_DISTRO:-humble}"/setup.bash 2>/dev/null || true
C="timeout 15 ros2"

echo "=== 1) 话题端点 (决定性: Publisher count) ==="
$C topic info -v "$TOPIC" 2>&1 | grep -E 'Type|Publisher count|Subscription count|Node name|Endpoint type|Reliability' | head -20

pub=$($C topic info "$TOPIC" 2>/dev/null | awk '/Publisher count/{print $3}')
echo
if [ "${pub:-X}" = "0" ]; then
  echo ">>> Publisher count = 0 ⇒ 源头没人发。像素统计/曝光/DDS 都不是变量, 查发布端进程。"
else
  echo ">>> Publisher count = ${pub} ⇒ 有人发。再看是否真在流动(传感器话题订阅端需 BEST_EFFORT):"
  echo "    (humble 的 topic hz 不接受 --qos-reliability, 用信息里的 Reliability 判断即可)"
  timeout 12 ros2 topic hz "$TOPIC" 2>&1 | head -4
fi

echo
echo "=== 2) 全部 Image 话题的发布者数 (扫一遍, 别只看一个) ==="
for t in $($C topic list -t 2>/dev/null | awk '/sensor_msgs\/msg\/Image|sensor_msgs\/msg\/CompressedImage/{print $1}' | head -10); do
  p=$($C topic info "$t" 2>/dev/null | awk '/Publisher count/{print $3}')
  echo "  $t : Publisher count = ${p:-?}"
done

if [ -n "$PID" ]; then
  echo
  echo "=== 3) 源头进程是不是'活着但僵死' (pid=$PID) ==="
  ps -o pid,stat,etime,rss,cmd -p "$PID" 2>/dev/null | cut -c1-120
  echo -n "  在 ROS 图里吗: "; $C node list 2>/dev/null | grep -iE "$(ps -o comm= -p "$PID" 2>/dev/null)" || echo "❌ 图里没有它 ⇒ 僵死/初始化未完成"
  echo "  握着哪些设备:"; ls -l /proc/$PID/fd 2>/dev/null | grep -E 'video|media' | head -8
  echo -n "  主线程 wchan: "; cat /proc/$PID/wchan 2>/dev/null; echo
  echo "  各线程 wchan(前5):"; for t in $(ls /proc/$PID/task 2>/dev/null | head -5); do echo -n "    tid$t: "; cat /proc/$PID/task/$t/wchan 2>/dev/null; echo; done
  echo
  echo "=== 4) 该节点原参数文件 (若还在, 可 1:1 原参数重启同一二进制) ==="
  PSF=$(ps -o cmd= -p "$PID" 2>/dev/null | grep -oE '\-\-params-file [^ ]+' | awk '{print $2}')
  echo "  params-file = ${PSF:-未取到}"
  [ -n "${PSF:-}" ] && ls -l "$PSF" 2>/dev/null
  echo
  echo "=== 5) 重启前必查: launch 里该节点有没有 respawn / required ==="
  echo "  普通 Node(无 respawn/非 required) ⇒ 杀掉不自愈也不带崩线体, 恢复=重启节点或整条 launch"
  echo "  required=True ⇒ 杀掉会带崩整条 launch(含机器人驱动), 生产线上先问再动"
fi
