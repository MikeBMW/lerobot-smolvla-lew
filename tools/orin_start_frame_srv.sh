#!/bin/bash
# 临时拉起 Orin 侧图像转发服务节点 (4060 控制台"打开输入图像"按需调用)
# 纪律: 临时进程 · 单实例(脚本内 pid 守卫) · 无调用自动退出 · 绝不自启/不写 systemd
set +e
pkill -f 'orin_frame_[s]rv' 2>/dev/null
sleep 0.5
source /opt/ros/humble/setup.bash
for ws in /home/tashan/0810/*/install/setup.bash; do
  [ -f "$ws" ] && source "$ws" && break
done
export ROS_DOMAIN_ID=0
cd /home/tashan/zmax_yolo || exit 1
setsid nohup python3 tools/orin_frame_srv.py \
  --device "${ZMAX_UVC_DEVICE:-2}" --quality "${ZMAX_JPEG_Q:-70}" --fps "${ZMAX_SRV_FPS:-10}" \
  --idle-seconds 25 </dev/null >/tmp/frame_srv.log 2>&1 &
sleep 9
echo "--- 进程 ---"
pgrep -af 'orin_frame_[s]rv' | head -3
echo "--- 日志 ---"
tail -14 /tmp/frame_srv.log 2>/dev/null
