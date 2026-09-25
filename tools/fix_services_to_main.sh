#!/usr/bin/env bash
# fix_services_to_main.sh — 把 6 个 main 线服务从"被切走的共享检出"改指 main worktree, 并复活采集链
# 起因: /home/ubuntu/lerobot-smolvla-lew 被切到 mac-hw 分支 → 那儿没有 main 线的脚本 →
#       重启这些服务会 FileNotFoundError (实测 ss-remote-tap 重启即挂)
set -u
MAIN=/home/ubuntu/zmax_rel
OLD=/home/ubuntu/lerobot-smolvla-lew

echo "=== ① worktree 补 venv 软链 (venv 与分支无关, 复用现成的那份) ==="
[ -e "$MAIN/gui-venv311" ] || ln -s "$OLD/gui-venv311" "$MAIN/gui-venv311"
ls -ld "$MAIN/gui-venv311"
"$MAIN/gui-venv311/bin/python" -c "import sys, cv2, numpy; print('  venv OK', sys.version.split()[0])"

echo "=== ② 目标脚本齐不齐 ==="
for f in tools/ss_remote_tap.py tools/ss_bypass_run.py tools/ss_yolo_on_real.py \
         tools/zmax_net_optimize.sh tools/ss_web_agent.py tools/aoi_feishu_push.py; do
  printf "  %-32s %s\n" "$f" "$([ -f "$MAIN/$f" ] && echo 有 || echo ❌缺)"
done

echo "=== ③ 重指 6 个服务 (备份 unit) ==="
for s in ss-remote-tap ss-bypass ss-yolo-bypass zmax-net-optimize zmax-web-agent-bridge aoi-feishu-push; do
  U=/etc/systemd/system/$s.service
  [ -f "$U" ] || { echo "  $s: 无 unit, 跳过"; continue; }
  sudo cp -n "$U" "$U.bak_preworktree" 2>/dev/null || true
  sudo sed -i "s#$OLD#$MAIN#g" "$U"
  printf "  %-24s → %s\n" "$s" "$(grep -m1 -oE 'ExecStart=.*' "$U" | cut -c1-110)"
done
sudo systemctl daemon-reload
echo "=== ④ 逐个重启 + 状态 ==="
for s in ss-remote-tap ss-bypass ss-yolo-bypass zmax-net-optimize zmax-web-agent-bridge aoi-feishu-push; do
  sudo systemctl restart "$s" 2>/dev/null
done
sleep 20
for s in ss-remote-tap ss-bypass ss-yolo-bypass zmax-net-optimize zmax-web-agent-bridge aoi-feishu-push; do
  printf "  %-24s %s\n" "$s" "$(systemctl is-active $s)"
done
echo "=== ⑤ 采集链复核 (帧龄应 <10s) ==="
for f in /home/ubuntu/zmax_ss_remote/state_*.jsonl /home/ubuntu/zmax_ss_remote/proposal_*.jsonl; do
  [ -f "$f" ] || continue
  printf "  %-46s mtime=%s\n" "$(basename $f)" "$(date -r $f '+%T')"
done
date '+  now %T'
