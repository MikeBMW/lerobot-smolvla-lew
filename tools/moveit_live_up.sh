#!/usr/bin/env bash
# moveit_live_up.sh — 起/停 「MoveIt plan-only → DDS ss_plan」整条镜像链 (老倪 2026-09-29)
# ─────────────────────────────────────────────────────────────────────────────
#  ① 容器 zmax-moveit  : move_group plan-only (ROS_DOMAIN_ID=42, allow_trajectory_execution=False)
#  ② 容器内常驻        : moveit_plan_live.py 逐轮调 /plan_kinematic_path + FK 每路点 → live_plan.jsonl
#  ③ 宿主机常驻        : moveit_plan_req.py 读真机只读 tap → plan_req.json (真机 jpos/tcp)
#  ④ 守护/探针         : zmax-dds-ss (发 DDS ss_plan) + zmax-dataspaces-probe (写 live.json/trace)
# 只规划不执行; 不动机械臂。用法: bash tools/moveit_live_up.sh [up|down|status]
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"
PLAN_DIR="${SS_PLAN_DIR:-$HOME/zmax_moveit_plan}"
CFG="$REPO/config/moveit_xms5"
CT=zmax-moveit
IMG=zmax-moveit:humble
GOAL="${GOAL_POINT:-slot7}"
INTERVAL="${PLAN_INTERVAL:-3.0}"
PY=/usr/bin/python3

case "${1:-up}" in
down)
  echo "■ 停: 容器内规划器 / 宿主机请求器 / 容器"
  sudo docker exec "$CT" bash -lc 'pkill -f moveit_plan_live.py' 2>/dev/null || true
  pkill -f 'tools/moveit_plan_req.py' 2>/dev/null || true
  sudo docker stop "$CT" >/dev/null 2>&1 || true
  echo "✅ 已停 (容器保留, 下次 up 直接重启)"
  exit 0;;
status)
  sudo docker ps -a --filter "name=$CT" --format '容器: {{.Names}} {{.Status}}'
  pgrep -af 'tools/moveit_plan_req.py' | head -2 || echo "宿主机请求器: 未运行"
  echo "--- 最近一条规划 ---"
  tail -n 1 "$PLAN_DIR/live_plan.jsonl" 2>/dev/null | head -c 400 || echo "(无 live_plan.jsonl)"
  echo; echo "--- 规划器日志尾 ---"
  tail -n 4 "$PLAN_DIR/planner.log" 2>/dev/null || echo "(无 planner.log)"
  exit 0;;
up) ;;
*) echo "用法: $0 [up|down|status]"; exit 2;;
esac

echo "═══ ① 起 plan-only move_group 容器 (带 /ws/plans 挂载) ═══"
mkdir -p "$PLAN_DIR"
sudo docker rm -f "$CT" >/dev/null 2>&1 || true
sudo docker run -d --name "$CT" --network host \
  -e ROS_DOMAIN_ID=42 -e ZMAX_MOVEIT_CFG=/ws/moveit_cfg \
  -v "$CFG:/ws/moveit_cfg:ro" -v "$PLAN_DIR:/ws/plans" \
  "$IMG" bash -lc 'source /opt/ros/humble/setup.bash && exec ros2 launch /ws/moveit_cfg/launch/plan_only.launch.py' \
  >/dev/null || { echo "✗ docker run 失败"; exit 3; }
echo "· 等 move_group 就绪 ..."
for i in $(seq 1 40); do
  if sudo docker logs "$CT" 2>&1 | grep -q 'You can start planning now'; then
    echo "✅ move_group 就绪 (${i}s)"; break; fi
  sleep 1
  [ "$i" = 40 ] && { echo "✗ 40s 未就绪, 看: sudo docker logs $CT"; exit 4; }
done
# 只规划不执行 是安全前提, 必须在这份日志里看到
sudo docker logs "$CT" 2>&1 | grep -i 'allow_trajectory_execution' | tail -2 || true

echo "═══ ② 容器内起逐轮规划器 ═══"
sudo docker cp "$HERE/moveit_plan_live.py" "$CT:/ws/moveit_plan_live.py" || { echo "✗ docker cp 失败"; exit 5; }
sudo docker exec "$CT" bash -lc "pkill -f moveit_plan_live.py" 2>/dev/null || true
sudo docker exec -d "$CT" bash -lc "source /opt/ros/humble/setup.bash && cd /ws && \
  nohup python3 /ws/moveit_plan_live.py --interval $INTERVAL \
    --req /ws/plans/plan_req.json --jsonl /ws/plans/live_plan.jsonl \
    --latest /ws/plans/live_plan_latest.json > /ws/plans/planner.log 2>&1 &"
sleep 3
echo "· 规划器日志:"; tail -n 3 "$PLAN_DIR/planner.log" 2>/dev/null || true

echo "═══ ③ 宿主机起真机状态请求器 (只读 tap) ═══"
pkill -f 'tools/moveit_plan_req.py' 2>/dev/null || true
nohup $PY "$HERE/moveit_plan_req.py" --to "$GOAL" --watch > "$PLAN_DIR/req.log" 2>&1 &
sleep 2
tail -n 3 "$PLAN_DIR/req.log" 2>/dev/null || true

echo "═══ ④ 重起守护/探针 (让 ss_plan 生效) ═══"
sudo systemctl restart zmax-dds-ss.service && echo "· zmax-dds-ss 已重起"
sudo systemctl restart zmax-dataspaces-probe.service && echo "· zmax-dataspaces-probe 已重起"
sleep 6
echo "═══ 现况 ═══"
echo -n "ss_plan 在 live.json: "
$PY - <<'PY' 2>/dev/null || echo "(读不到)"
import json
d = json.load(open('/home/ubuntu/zmax_data/dataspace/live.json'))
t = (d.get('topics') or {}).get('ss_plan') or {}
print('hz=%s count=%s age=%s' % (t.get('hz_meas'), t.get('count'), t.get('frame_age_s')))
PY
