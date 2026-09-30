#!/usr/bin/env bash
# verify_service.sh — systemd 服务"四件套"核验 (开机会不会跑 / 现在活没活 / 它说了什么 / 有没有真产物)
# 用法: bash verify_service.sh <unit名(可省.service)> [日志路径] [台账glob]
set -u
U="${1:?用法: verify_service.sh <unit名> [日志路径] [台账glob]}"
U="${U%.service}"
LOG="${2:-/var/log/$U.log}"
TAB="${3:-}"
printf '== %s ==\n' "$U"
printf '  is-enabled : %s\n' "$(systemctl is-enabled "$U.service" 2>&1)"
printf '  is-active  : %s\n' "$(systemctl is-active  "$U.service" 2>&1)"
printf '  since      : %s\n' "$(systemctl show -p ActiveEnterTimestamp --value "$U.service" 2>/dev/null)"
printf '  exec       : %s\n' "$(systemctl show -p ExecStart --value "$U.service" 2>/dev/null | cut -c1-160)"
if [ -r "$LOG" ] || sudo -n test -r "$LOG" 2>/dev/null; then
  n=$(sudo -n wc -l < "$LOG" 2>/dev/null || wc -l < "$LOG" 2>/dev/null)
  printf '  日志 %s : %s 行\n' "$LOG" "$n"
  [ "${n:-0}" -eq 0 ] && echo "    ⚠️ 日志为空 → 多半是 Python 输出被缓冲: unit 里加 Environment=PYTHONUNBUFFERED=1 后 restart"
  sudo -n tail -3 "$LOG" 2>/dev/null | sed 's/^/    | /' || tail -3 "$LOG" 2>/dev/null | sed 's/^/    | /'
else
  printf '  日志 %s : 不存在/不可读 → 查 journalctl -u %s -n 20\n' "$LOG" "$U"
fi
if [ -n "$TAB" ]; then
  f=$(ls -t $TAB 2>/dev/null | head -1)
  if [ -n "${f:-}" ]; then printf '  台账最新: %s\n' "$f"; tail -1 "$f" | cut -c1-300 | sed 's/^/    | /'
  else printf '  台账 %s : 没有文件 → 服务可能从未真正跑成功\n' "$TAB"; fi
fi
echo "  手工复跑(必须用 restart, oneshot+RemainAfterExit 时 start 不会重跑): sudo systemctl restart $U.service"
