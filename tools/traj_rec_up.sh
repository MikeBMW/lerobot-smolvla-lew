#!/usr/bin/env bash
# traj_rec_up.sh — 起"真机轨迹录制器"(容器内 50Hz 关节角+TCP → /tmp/live_trace.json)
# ═════════════════════════════════════════════════════════════════════════════
# 为什么要有这个薄壳(而不是直接写进 unit):
#   ① 录制器**会自己到点退出**(--seconds), 而且写在**容器**里 —— 容器一重建 /tmp 就空 ⇒
#      systemd 直接 exec docker 也行, 但要自己管轮转;
#   ② /tmp/live_motion.jsonl 是 50Hz 逐帧落盘(实测 ~8KB/s), 不轮转一天能长到几百 MB,
#      而本机磁盘本来就在红线附近 ⇒ 每次起之前按大小轮转一次, 旧的留一份 .old 便于复盘。
# 用法: bash tools/traj_rec_up.sh [容器名] [小时]
set -u
C=${1:-ss-remote-tap}
HOURS=${2:-12}
MAXB=$((200 * 1024 * 1024))

# 容器在不在(不在就等: 它由 ss-remote-tap.service 托管, 会自己回来)
for _ in $(seq 1 60); do
  if sudo docker ps --format '{{.Names}}' | grep -qx "$C"; then break; fi
  echo "[$(date +%H:%M:%S)] 等容器 $C 起来…"; sleep 5
done
if ! sudo docker ps --format '{{.Names}}' | grep -qx "$C"; then
  echo "[$(date +%H:%M:%S)] ✗ 容器 $C 不在, 放弃"; exit 1
fi

# 轮转(只在容器内, 不碰宿主机磁盘上的别的东西)
sudo docker exec "$C" bash -lc '
  p=/tmp/live_motion.jsonl
  if [ -f "$p" ]; then
    sz=$(stat -c%s "$p" 2>/dev/null || echo 0)
    if [ "$sz" -gt '"$MAXB"' ]; then
      mv -f "$p" "$p.old" && echo "已轮转 live_motion.jsonl ($((sz/1024/1024))MB → .old)"
    fi
  fi'

# 🔴 新录制纪元: 录制器一重启, 它自己的计数 n 就从 0 重来, 而"清除线"是按 n 记的 ⇒ 必须同步归 0。
#    不归 0 的后果(实测): 上一纪元的清除线 26479 永远大于新 n(几十), 发布器走 raw[base:] 的兜底
#    只留最后一个点 ⇒ 画面上的轨迹被**永久夹成 1 个点**, 看起来就像"轨迹坏了"。
/home/ubuntu/zmax/gui-venv311/bin/python /home/ubuntu/zmax/tools/traj_display.py baseline 0 >/dev/null 2>&1 || true

echo "[$(date +%H:%M:%S)] 起录制器: $C @50Hz, 目标 --seconds $((HOURS*3600))"
exec sudo docker exec "$C" bash -lc '
  source /opt/ros/humble/setup.bash
  exec python3 /repo/tools/live_motion_recorder.py --seconds '"$((HOURS*3600))"' --hz 50 \
       --jsonl /tmp/live_motion.jsonl --trace /tmp/live_trace.json'
