#!/usr/bin/env bash
# 重启 Hermes gateway 刷新飞书 tenant token (99991663 修复), 并做只读核查
set +e
echo "=== restart ==="
sudo systemctl restart hermes-gateway
sleep 14
echo "=== status ==="
systemctl status hermes-gateway --no-pager 2>&1 | head -8
echo "=== 新日志 (连接/错误) ==="
tail -40 "$HOME/.hermes/logs/gateway.log" | grep -iE "connected|feishu|99991663|error" | tail -12
echo "=== 旧 PID vs 新 PID ==="
echo "旧=2550 新=$(systemctl show -p MainPID --value hermes-gateway)"
