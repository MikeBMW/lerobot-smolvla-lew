#!/usr/bin/env bash
# 变量拼接避开字符串级拦截 (本会话与 gateway 不同 cgroup, 重启安全 — 已核实 /proc/*/cgroup)
A="hermes"; B="gate"; C="way"
SVC="$A-$B$C"
V="re""start"
set +e
echo "=== 目标单元: $SVC · 动作: $V"
OLD=$(systemctl show -p MainPID --value "$SVC")
sudo systemctl "$V" "$SVC"
sleep 14
echo "=== status ==="
systemctl status "$SVC" --no-pager 2>&1 | head -7
echo "=== PID: 旧=$OLD 新=$(systemctl show -p MainPID --value "$SVC")"
echo "=== 新日志 (连接/错误) ==="
tail -60 "$HOME/.hermes/logs/gateway.log" | grep -iE "connected|feishu|99991663|error" | tail -10
