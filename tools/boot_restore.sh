#!/bin/bash
# Z-MAX 关机前记录 / 开机后复原清单 (2026-09-28 v5.15.43 现场状态)
#
# 用法:
#   bash tools/boot_restore.sh check     # 逐项查现在什么活着/什么死了(只读，不动任何东西)
#   bash tools/boot_restore.sh local     # 只把本机(4060)这 5 个进程重新拉起来
#   bash tools/boot_restore.sh orin      # 提示 Orin 侧要做什么(不自动执行)
#   bash tools/boot_restore.sh aoi       # 提示工控机侧要做什么(不自动执行)
#
# ── 关机后会**自动回来**的(不用管) ────────────────────────────
#   systemd(enabled): zmax-dds-agg / zmax-dds-pub / zmax-dds-ss / zmax-hil-bridge
#                     zmax-data-mount / zmax-net-optimize / hermes-gateway
#   docker(--restart unless-stopped): rokae_tcp_sampler / ss-remote-tap / zmax-arm-raw
#
# ── 关机后会**丢**、必须手动拉起的 ──────────────────────────────
#   本机 : cam_live_stream(8791+8793) · l5_live_mark · vl_safety_monitor · l2_daemon · demo_recorder · studio.py
#   Orin : 机器人栈(手工拉起) + rs_fast_node(:8792 arm 取流)   ← 关键: 栈起来后厂商节点会抢相机, 必须重跑取流
#   工控机: 10082 金手指 / 10083 表面  ← 注意 ZMAX_AOI_KeepAlive 现为 Disabled(手动控制期), 不拉就没人起
set -u
ROOT=/home/ubuntu/zmax_rel
CD="cd $ROOT"
PY=./gui-venv311/bin/python

c_green="\033[32m"; c_red="\033[31m"; c_yel="\033[33m"; c_off="\033[0m"

check() {
  echo "=== ① 本机(4060) 进程 ==="
  for pat in "cam_live_stream.py --port 8791" "l5_live_mark" "vl_safety_monitor" "l2_daemon" "demo_recorder" "studio.py"; do
    p=$(pgrep -f "[${pat:0:1}]${pat:1}" 2>/dev/null | head -1)
    [ -n "$p" ] && echo -e "  ${c_green}✓${c_off} $pat   pid $p" || echo -e "  ${c_red}✗${c_off} $pat   (未运行)"
  done
  echo "=== ② docker 常驻 ==="
  sudo -n docker ps --format "  {{.Names}}\t{{.Status}}" 2>/dev/null || echo "  (读不到 docker，需 sudo)"
  echo "=== ③ systemd Z-MAX 服务 ==="
  systemctl list-units --type=service --state=running 2>/dev/null | grep -iE "zmax|hermes" | awk '{print "  "$1}' || true
  echo "=== ④ Orin :8792 arm 取流 ==="
  s=$(curl -s -m 6 http://192.168.23.66:8792/status 2>/dev/null)
  [ -n "$s" ] && echo "  $s" || echo -e "  ${c_red}✗${c_off} 无响应 ⇒ Orin 上 rs_fast_node 没在跑(重启后会丢)"
  echo "=== ⑤ 工控机 10082/10083 ==="
  for p in 10082 10083; do
    c=$(curl -s -m 5 -o /dev/null -w '%{http_code}' "http://192.168.23.23:$p/last_result" 2>/dev/null)
    [ "$c" = "200" ] && echo -e "  ${c_green}✓${c_off} $p  200" || echo -e "  ${c_red}✗${c_off} $p  $c (000=没起来)"
  done
  echo "=== ⑥ 工作区是否有未入库改动 ==="
  git -C "$ROOT" status --short | head -6 | sed 's/^/  /'
  echo "=== ⑦ 当前版本 ==="
  echo "  $(git -C "$ROOT" log --oneline -1)"
}

local_up() {
  cd "$ROOT" || exit 1
  echo "=== 拉本机进程 ==="
  # 推流服务(8791 看板 + 8793 工位总览)
  if ! pgrep -f "[c]am_live_stream.py --port 8791" >/dev/null; then
    nohup $PY tools/cam_live_stream.py --port 8791 --station-port 8793 --quality 72 --fps 30 \
      --arm-http http://192.168.23.66:8792/frame.jpg --arm-fps 30 --local-dev 2 --local2-dev 0 \
      --depth-fps 4 --aoi-fps 1.0 --ctl-motion --overlay --overlay-src all --overlay-fps 10 \
      > /tmp/cam_live_stream.out 2>&1 &
    echo "  ✓ 起了推流服务"
  else echo "  · 推流服务已在跑"; fi
  # 实时标注器(守护壳, 5Hz)
  if ! pgrep -f "[l]5_live_mark_run.sh" >/dev/null; then
    nohup bash tools/l5_live_mark_run.sh > /tmp/l5_live_mark_run.out 2>&1 &
    echo "  ✓ 起了实时标注器"
  else echo "  · 实时标注器已在跑"; fi
  # VL 安全监控(单轮上限 300s)
  if ! pgrep -f "[v]l_safety_monitor.py" >/dev/null; then
    ZMAX_VL_CYCLE_TIMEOUT_S=300 nohup $PY -u tools/vl_safety_monitor.py --every 20 \
      > /home/ubuntu/zmax_data/vl_safety_monitor.log 2>&1 &
    echo "  ✓ 起了 VL 安全监控"
  else echo "  · VL 安全监控已在跑"; fi
  # L2 执行器(位姿读 SDK 直采; 下发通道禁 SHM)
  if ! pgrep -f "[l]2_daemon.py" >/dev/null; then
    nohup $PY -u tools/l2_daemon.py > /tmp/l2_daemon.out 2>&1 &
    echo "  ✓ 起了 L2 执行器"
  else echo "  · L2 执行器已在跑"; fi
  sleep 12
  echo "  复核:"
  curl -s -o /dev/null -w "    8793/station → %{http_code}\n" -m 8 http://127.0.0.1:8793/station
  curl -s -o /dev/null -w "    8791/        → %{http_code}\n" -m 8 http://127.0.0.1:8791/
  echo "  控制台 GUI:  cd $ROOT && DISPLAY=:0 ./gui-venv311/bin/python tools/gui/studio.py"
}

case "${1:-check}" in
  check) check ;;
  local) local_up ;;
  orin) cat <<'TXT'
=== Orin(192.168.23.66, tashan) 侧要做的 ===
  1) 机器人栈是**手工**拉起的(不自启):
       cd /home/tashan/0810/tashan_robot_so_20260807_174920_6983506_aarch64
       source /opt/ros/humble/setup.bash ; source install/setup.bash
       ros2 launch launch/start.launch.py project:=sr5_guangmokuai_4   # 参见现场原有启动方式
  2) 相机被厂商节点抢回后, arm 取流会挂 ⇒ 重跑取流节点(这就是今天恢复用的):
       bash /tmp/rsfix_arm.sh        # 或直接:
       setsid nohup python3 /home/tashan/zmax/rs_fast_node.py > /tmp/rs_fast.log 2>&1 < /dev/null &
       # ⚠ source 环境时**不要用 set -u**、**不要把 source 接进管道**
  3) 验收: curl -s http://127.0.0.1:8792/status   → {"n":>0,...,"err":""}
          连取两次 frame.jpg, md5 必须**不同**(同=又卡住了)
  4) 未做: @reboot 自启(需老倪点头) —— 所以每次重启都要走一遍 2)
TXT
  ;;
  aoi) cat <<'TXT'
=== 工控机(192.168.23.23) 侧要做的 ===
  ⚠ ZMAX_AOI_KeepAlive 现在是 **Disabled**(手动控制期) ⇒ 不拉就没人起这两个服务
  就地(管理员 PowerShell)执行:
    # 想恢复自愈(推荐):  Enable-ScheduledTask -TaskName 'ZMAX_AOI_KeepAlive'
    # 手工起(与部署脚本同款):
    $d='D:\xspace\ultralytics_AOI'; $py="$d\venv\Scripts\python.exe"
    $sh=New-Object -ComObject WScript.Shell
    $sh.Run("cmd /c cd /d $d && $py cam_finger_10082_work_v6.py  > $d\v6f.log 2>&1",0,$false) | Out-Null
    $sh.Run("cmd /c cd /d $d && $py cam_surface_10083_work_v6.py > $d\v6s.log 2>&1",0,$false) | Out-Null
  验收(本机跑): for p in 10082 10083; do curl -s -o /dev/null -w "$p %{http_code}\n" http://192.168.23.23:$p/last_result; done
  ⚠ 远程通道已死(agent 23h 没取件) ⇒ 任何远程更新/巡检都不可用, 只能就地操作
TXT
  ;;
  *) echo "用法: bash tools/boot_restore.sh {check|local|orin|aoi}" ;;
esac
