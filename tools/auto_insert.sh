#!/usr/bin/env bash
# 自主插孔: 从一号位反向上安全梯 → 孔边高度 → 交 L2.lissa_insert 力控插入
# 每步带意图过闸(现场授权在场); 任一步被拦立即中止, 臂停在当前安全位, 绝不重发。
set -u
LOG=/home/ubuntu/zmax_data/l2_daemon.log
TCP(){ sudo -n timeout 25 docker exec ss-remote-tap bash -c "export ROS_DOMAIN_ID=0; source /opt/ros/humble/setup.bash; timeout 10 ros2 topic echo --once /robot/tcp_pose --field pose" 2>&1 | awk '/^  [xyz]:/{printf " %.4f", $2}'; echo; }

leg(){ local sk=$1 d=$2 desc=$3 off out t0 v; off=$(stat -c%s "$LOG"); t0=$(date +%s); out=""; v=""
  if [ "$sk" = "L2.lissa_insert" ]; then printf '{"skill":"L2.lissa_insert","allow_unlocked_retract":true}\n' > /home/ubuntu/zmax_data/l2_cmd.fifo
  elif [ "$d" = "-" ]; then printf '{"skill":"%s"}\n' "$sk" > /home/ubuntu/zmax_data/l2_cmd.fifo
  else printf '{"skill":"%s","d_mm":%s,"speed":50}\n' "$sk" "$d" > /home/ubuntu/zmax_data/l2_cmd.fifo; fi
  while [ $(( $(date +%s) - t0 )) -lt 300 ]; do sleep 3
    out=$(tail -c +$((off+1)) "$LOG" 2>/dev/null)
    echo "$out" | grep -qE "受理:|回执:" && { echo "$out" | grep -qE "受理: 🛑|🛑 下发被拦|🛑 阶段|success=False|❌" && v="BLOCKED" || v="OK"; break; }
  done
  echo "=== $desc [$sk $d] -> ${v:-无回执}"
  echo "$out" | grep -E "🎯|人工一次性放行|目标|阶段|回执|🛑|已下发|受理:|success" | tail -5 | cut -c1-170 | sed 's/^/    /'
  [ "$v" = "OK" ] || return 1
  sleep $([ "$d" = "-" ] && echo 14 || echo $(( 6 + d/5 ))); echo "    TCP:$(TCP)"; return 0; }

echo "起点 TCP:$(TCP)   (一号位)"
leg L2.lift    85 "① 抬85 → z≈0.195"                    || { echo "⛔ 停"; exit 1; }
leg L2.lift    85 "② 抬85 → z≈0.280"                    || { echo "⛔ 停"; exit 1; }
leg L2.lift    20 "③ 抬20 → z≈0.300(安全高度)"           || { echo "⛔ 停"; exit 1; }
leg L2.forward 102 "④ 前进 +X 102 → x 到 0.7505"         || { echo "⛔ 停"; exit 1; }
leg L2.right   270 "⑤ 向右 -Y 270 → y 到 0.2279"         || { echo "⛔ 停"; exit 1; }
leg L2.lower   85 "⑥ 降85 → z≈0.215"                     || { echo "⛔ 停"; exit 1; }
leg L2.lower   25 "⑦ 降25 → z≈0.190(孔边高度)"           || { echo "⛔ 停"; exit 1; }
echo "--- 已到孔边高度, 交力控插入收口 ---"
leg L2.lissa_insert - "⑧ L2.lissa_insert 力控插入(退60mm→推进→李萨如6N)" || { echo "⛔ 停"; exit 1; }
echo "=== 插孔流程结束; 最终 TCP:$(TCP)"
