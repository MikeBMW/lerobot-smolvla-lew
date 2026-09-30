#!/usr/bin/env bash
# 把机械臂从"循环位置"送回"一号位"(老倪: 标定板不用拿走, 现场安全, 继续)
#   路径: 前进 +X 115 → 向左 +Y 267 → 分步下降 85/60/30 (≤85mm/步, 横梁上限)
# 纪律: 每一步都带**动作意图**过 VL 安全闸; 任一步被拦 ⇒ 立即中止, 臂停在当前安全位, 绝不重发。
set -u
LOG=/home/ubuntu/zmax_data/l2_daemon.log
FIFO=/home/ubuntu/zmax_data/l2_cmd.fifo
SLOT1="0.648836, 0.498292, 0.110378"

TCP() {
  sudo -n timeout 25 docker exec ss-remote-tap bash -c \
    "export ROS_DOMAIN_ID=0; source /opt/ros/humble/setup.bash; timeout 10 ros2 topic echo --once /robot/tcp_pose --field pose" \
    2>&1 | awk '/^  [xyz]:/{printf " %.4f", $2}'
  echo
}

leg() {   # $1=技能 $2=mm $3=描述
  local sk=$1 d=$2 desc=$3 off out t0 v
  off=$(stat -c%s "$LOG"); t0=$(date +%s); out=""; v=""
  printf '{"skill":"%s","d_mm":%s,"speed":50}\n' "$sk" "$d" > "$FIFO"
  while [ $(( $(date +%s) - t0 )) -lt 340 ]; do
    sleep 4
    out=$(tail -c +$((off + 1)) "$LOG" 2>/dev/null)
    if echo "$out" | grep -q "受理:"; then
      if echo "$out" | grep -qE "受理: 🛑|🛑 下发被拦|🛑 阶段|🛑 下发失败"; then v="BLOCKED"; else v="OK"; fi
      break
    fi
  done
  echo "=== $desc  [$sk ${d}mm] -> ${v:-无回执(超时)}"
  echo "$out" | grep -E "🎯|安全闸|已下发|受理" | tail -4 | sed 's/^/    /'
  [ "$v" = "OK" ] || return 1
  sleep $(( 6 + d / 5 ))
  echo "    TCP:$(TCP)"
  return 0
}

echo "起点 TCP:$(TCP)"
leg L2.forward 115 "腿1 前进 +X 115mm → x 回 0.6488" || { echo "⛔ 被拦 → 中止; 臂停在当前安全位"; exit 1; }
leg L2.left    267 "腿2 向左 +Y 267mm → y 回 0.4983" || { echo "⛔ 被拦 → 中止; 臂停在当前安全位"; exit 1; }
echo "--- 已在一号位正上方, 分步下降(原路返回) ---"
leg L2.lower   85 "下降1 -Z 85mm" || { echo "⛔ 被拦 → 中止; 臂停在当前安全位"; exit 1; }
leg L2.lower   60 "下降2 -Z 60mm" || { echo "⛔ 被拦 → 中止; 臂停在当前安全位"; exit 1; }
leg L2.lower   30 "下降3 -Z 30mm" || { echo "⛔ 被拦 → 中止; 臂停在当前安全位"; exit 1; }
echo "=== 返回完成; 目标一号位 $SLOT1"
echo "最终 TCP:$(TCP)"
