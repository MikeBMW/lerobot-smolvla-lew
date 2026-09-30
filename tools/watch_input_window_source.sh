#!/usr/bin/env bash
# 取证: 「输入图像」窗口到底跑的是哪一路源 (2026-09-17)
# 判据 (进程级, 不靠肉眼看窗口):
#   仿真 → studio 进程里有 mujoco 映射; 服务 cgroup 下没有 ssh 到 Orin / docker exec 客户端
#   真机 → cgroup 下有 ssh tashan@192.168.23.66 (Orin srv) 或 docker ... ss_frame_srv_client, 且 live_frame.jpg 在更新
set -u
export DISPLAY=:0
PID=$(systemctl --user show -p MainPID --value zmax-studio)
DEADLINE=$((SECONDS + 150))
WID=""
while [ $SECONDS -lt $DEADLINE ]; do
  WID=$(wmctrl -l | awk '/输入图像/ {print $1; exit}')
  [ -n "$WID" ] && break
  sleep 3
done
if [ -z "$WID" ]; then
  echo "TIMEOUT: 输入图像窗口还没打开 (studio PID=$PID)"
  exit 0
fi
echo "窗口已开: $WID  $(wmctrl -l | awk '/输入图像/ {$1=$2=$3=""; print}')"
sleep 4
echo
echo "── 进程证据 (studio PID=$PID) ──"
MUJOCO=$(grep -c -i mujoco /proc/$PID/maps 2>/dev/null || echo 0)
echo "mujoco 库映射段数: $MUJOCO   $([ "$MUJOCO" -gt 0 ] && echo '→ 仿真渲染器已加载' || echo '→ 没加载 mujoco')"
echo "子进程 (cgroup):"
systemctl --user status zmax-studio --no-pager | sed -n '/CGroup/,$p' | sed 's/^ *//'
echo
SSH_ORIN=$(pgrep -af "ssh .*tashan@192.168.23.66" | wc -l)
CLI=$(pgrep -af "ss_frame_srv_client" | wc -l)
echo "ssh 到 Orin 的进程数: $SSH_ORIN     Docker 取帧客户端进程数: $CLI"
if [ -f /home/ubuntu/zmax_ss_remote/live_frame.jpg ]; then
  echo "真机帧文件 live_frame.jpg 时间: $(date -r /home/ubuntu/zmax_ss_remote/live_frame.jpg +%H:%M:%S)  现在 $(date +%H:%M:%S)"
else
  echo "真机帧文件 live_frame.jpg: 不存在"
fi
echo
if [ "$MUJOCO" -gt 0 ] && [ "$SSH_ORIN" -eq 0 ] && [ "$CLI" -eq 0 ]; then
  echo "判定: ✅ 仿真源 (metaworld 渲染在 GUI 进程内跑, 没有任何 Orin/真机链路)"
elif [ "$SSH_ORIN" -gt 0 ] || [ "$CLI" -gt 0 ]; then
  echo "判定: ❌ 真机源 (Orin/Docker 链路在跑)"
else
  echo "判定: ⚠️ 两路都没跑起来 (链路可能还在启动, 再等几秒)"
fi
