#!/usr/bin/env bash
# 从孔边(0.7505,0.2279,0.1900)回一号位 —— 安全梯: 升到安全高度 → 横移 → 交 L2.slot1 收口
# 每一步带动作意图过闸; 任一步被拦立即中止, 臂停在当前安全位, 绝不重发。
set -u
LOG=/home/ubuntu/zmax_data/l2_daemon.log
TCP(){ sudo -n timeout 25 docker exec ss-remote-tap bash -c "export ROS_DOMAIN_ID=0; source /opt/ros/humble/setup.bash; timeout 10 ros2 topic echo --once /robot/tcp_pose --field pose" 2>&1 | awk '/^  [xyz]:/{printf " %.4f", $2}'; echo; }

leg(){ local sk=$1 d=$2 desc=$3 off out t0 v; off=$(stat -c%s "$LOG"); t0=$(date +%s); out=""; v=""
  if [ "$d" = "-" ]; then printf '{"skill":"%s"}\n' "$sk" > /home/ubuntu/zmax_data/l2_cmd.fifo
  else printf '{"skill":"%s","d_mm":%s,"speed":100}\n' "$sk" "$d" > /home/ubuntu/zmax_data/l2_cmd.fifo; fi
  while [ $(( $(date +%s) - t0 )) -lt 300 ]; do sleep 2
    out=$(tail -c +$((off+1)) "$LOG" 2>/dev/null)
    echo "$out" | grep -qE "受理:|阶段 [0-9]+/[0-9]+ .*回执|✅ L2\." && { echo "$out" | grep -qE "受理: 🛑|🛑 下发被拦|🛑 阶段" && v="BLOCKED" || v="OK"; break; }
  done
  echo "=== $desc [$sk $d] -> ${v:-无回执}"
  echo "$out" | grep -E "🎯|人工一次性放行|目标|阶段|🛑|已下发|受理:" | tail -4 | sed 's/^/    /'
  [ "$v" = "OK" ] || return 1
  sleep $([ "$d" = "-" ] && echo 12 || echo $(( 6 + d/5 ))); echo "    TCP:$(TCP)"; return 0; }

echo "起点 TCP:$(TCP)   (一号位 = 0.648836, 0.498292, 0.110378)"
leg L2.lift     85 "① 抬到安全高度 z≈0.275"          || { echo "⛔ 停"; exit 1; }
leg L2.lift     25 "② 再抬到 z≈0.300"                 || { echo "⛔ 停"; exit 1; }
leg L2.backward 102 "③ 后退 -X 102mm → x 回 0.6488"   || { echo "⛔ 停"; exit 1; }
leg L2.left     270 "④ 向左 +Y 270mm → y 回 0.4983"   || { echo "⛔ 停"; exit 1; }
leg L2.slot1    -   "⑤ 交 L2.slot1 收口(两阶段回槽位)" || { echo "⛔ 停"; exit 1; }
echo "=== 完成; 最终 TCP:$(TCP)   目标 0.648836, 0.498292, 0.110378"
