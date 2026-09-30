#!/bin/bash
# gateway 系统级守护 v2: 由系统 cron 每分钟调用, 完全独立于 Hermes/gateway 自身
# 解决 v1 死锁: 旧版守护跑在 gateway 进程内, gateway 死 → 守护死 → 无人拉起
# 进程存在 = 活着(含启动中); 死了 → flock 防并发 → 清理 stale 锁 → setsid 拉起
# 有动作才输出(触发 cron 邮件/日志), 正常静默

# cron 自愈: 容器重启后系统 cron 不会自动起, 由 Hermes 内每3m 调用本脚本时拉起 (2026-08-17)
# 外部 cron 调用时 cron 必活 → 无操作; Hermes 内调用且 cron 死 → 拉起恢复每分钟守护
pgrep -x cron >/dev/null 2>&1 || /usr/sbin/cron

# 检测模式: 匹配 bin/hermes 即可(裸 `hermes` 与 `hermes gateway run` 都算),
#           不能用 "hermes gateway run" — gateway 实际以裸命令启动会误判死亡(2026-08-17)
GATEWAY_PROC=$(pgrep -f "/root/.hermes/venv/bin/hermes" | head -1)
if [ -n "$GATEWAY_PROC" ]; then
  exit 0  # 活着 → 静默
fi

# 防并发: 同一分钟多个 cron 触发时只让一个拉起
exec 9>/tmp/gateway_watchdog.lock
flock -n 9 || exit 0  # 拿不到锁 = 别人正在拉起

# 死了 → 清理 stale 锁 + 拉起 (setsid 脱离会话, nohup 防 HUP)
rm -f ~/.hermes/gateway.lock ~/.hermes/gateway.pid
setsid nohup ~/.hermes/venv/bin/hermes gateway run > ~/.hermes/gateway-run.log 2>&1 &
echo "$(date '+%F %T') ⚠ Gateway 曾死亡, 已自动拉起 (等待飞书连接 ~2min)"
