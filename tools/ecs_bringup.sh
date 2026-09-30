#!/usr/bin/env bash
# 🚀 ECS 开机一键自检 + 恢复 (老倪: "等晚上开启ECS服务器")
#
# 为什么需要它: relay 与 nginx 在 ECS 上**无人监管** → 实例重启后两者常同时死,
#              表现为 https://datadrive.world 返回 000/502 但 ping 通。
# 用法:  ZMAX_ECS_PW='<密码>' bash tools/ecs_bringup.sh
#        (或已配免密: bash tools/ecs_bringup.sh)
# 依据: http-relay-service 技能 §9 恢复阶梯 + ecs-relay.md (relay 在 /root/zmax-relay, 端口 39053)
set -uo pipefail

HOST="${ECS_HOST:-39.102.211.79}"
USER_="${ECS_USER:-root}"
DOMAIN="${ECS_DOMAIN:-datadrive.world}"
PW="${ZMAX_ECS_PW:-}"

SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=10 -o BatchMode=no"
if [ -n "$PW" ]; then
  SSH="sshpass -p $PW ssh $SSH_OPTS $USER_@$HOST"
else
  SSH="ssh $SSH_OPTS $USER_@$HOST"
fi

echo "════════════════════════════════════════════════════════════"
echo "🚀 ECS 自检与恢复  $DOMAIN ($HOST)"
echo "════════════════════════════════════════════════════════════"

echo "── ① 公网三层探测 ──"
code_home=$(curl -s -o /dev/null -w '%{http_code}' --max-time 12 "https://$DOMAIN/" || echo 000)
code_relay=$(curl -s -o /dev/null -w '%{http_code}' --max-time 12 "https://$DOMAIN/api/relay/status" || echo 000)
echo "   首页 HTTP $code_home · relay/status HTTP $code_relay"
if [ "$code_home" = "200" ] && [ "$code_relay" = "200" ]; then
  echo "   ✅ 已健康, 无需恢复"
  curl -s --max-time 10 "https://$DOMAIN/api/relay/status" | head -c 300; echo
  exit 0
fi

echo "── ② 主机可达性 ──"
ping -c 2 -W 3 "$HOST" >/dev/null 2>&1 && echo "   ping 通 (主机活着, 是 web 层挂了)" || echo "   ⚠️ ping 不通 (实例可能还没起)"

echo "── ③ SSH 进去查状态 ──"
$SSH 'echo "  nginx 进程:"; ps aux | grep -c "[n]ginx: master";
     echo "  relay 进程:"; ps aux | grep -c "[z]max_relay";
     echo "  443 监听:"; ss -tlnp 2>/dev/null | grep -c ":443";
     echo "  39053 监听:"; ss -tlnp 2>/dev/null | grep -c ":39053"' 2>&1 | tail -8

echo "── ④ 恢复 nginx (宝塔主机必须起 BT 的二进制!) ──"
# 关键坑: systemd 的 nginx 不加载宝塔 vhost → 起了也是白起
$SSH 'pkill -f "nginx: master" 2>/dev/null; sleep 2; \
      if [ -x /www/server/nginx/sbin/nginx ]; then \
        /www/server/nginx/sbin/nginx && echo "   ✅ 已启动 BT nginx"; \
      else \
        nginx && echo "   ✅ 已启动 systemd nginx"; \
      fi; sleep 1; ss -tlnp 2>/dev/null | grep ":443" | head -2' 2>&1 | tail -4

echo "── ⑤ 恢复 relay ──"
$SSH 'if [ -f /root/zmax-relay/start.sh ]; then cd /root/zmax-relay && bash start.sh; else \
        cd /root/zmax-relay && setsid nohup python3 zmax_relay.py > relay.log 2>&1 < /dev/null & sleep 2; fi; \
      ss -tlnp 2>/dev/null | grep ":39053" | head -2; \
      grep -n "port = " /root/zmax-relay/zmax_relay.py | head -1' 2>&1 | tail -4

echo "── ⑥ 三层验证 (本地 → 公网 → 首页) ──"
$SSH 'curl -s --max-time 8 http://127.0.0.1:39053/status | head -c 200; echo "  ← 本地 relay"' 2>&1 | tail -2
echo "   公网 relay: HTTP $(curl -s -o /dev/null -w '%{http_code}' --max-time 12 "https://$DOMAIN/api/relay/status")"
echo "   公网首页  : HTTP $(curl -s -o /dev/null -w '%{http_code}' --max-time 12 "https://$DOMAIN/")"

echo "════════════════════════════════════════════════════════════"
echo "下一步 (即可传包给备份端):"
echo "  python tools/ecs_publish.py --check                                  # 确认 relay 就绪"
echo "  python tools/ecs_publish.py ~/zmax_replica_T1.tar.zst --part-mb 180  # 分片上传(nginx 限 200m)"
echo "⚠️ 若 relay/status 报 502 但本地 39053 正常 → nginx 配置问题(client_max_body_size/proxy_pass 端口)"
echo "════════════════════════════════════════════════════════════"
