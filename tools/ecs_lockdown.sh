#!/usr/bin/env bash
# 🔒 ECS 主页访问限制 —— 只允许「静静的4060」与「小芳的Mac」访问
# 老倪 2026-09-24: "就是除了静静的4060和小芳mac电脑，谁都访问不了ecs主页"
#
# 原理: 宝塔 nginx 站点配置里加 IP 白名单（allow/deny）
#       可只锁主页, 也可锁整站+API（推荐: 整站, 因为只有这两台机器该用）
#
# 用法:
#   ZMAX_ECS_PW='***' bash tools/ecs_lockdown.sh 103.114.194.13 <小芳Mac的公网IP> [--whole-site]
#
# 注意:
#   · nginx 用宝塔二进制 (/www/server/nginx/sbin/nginx), 不是 systemd
#   · 站点配置: /www/server/panel/vhost/nginx/datadrive.world.conf
#   · 改完必须 nginx -t 验证 + reload, 否则整站挂掉
#   · 本机(4060) IP 会自动取当前公网出口, 防写死过期
set -euo pipefail

ECS_HOST="${ECS_HOST:-39.102.211.79}"
IP_4060="${1:-103.114.194.13}"
IP_MAC="${2:-}"
HOME_ONLY="${3:-}"
CONF="/www/server/panel/vhost/nginx/datadrive.world.conf"
NGINX="/www/server/nginx/sbin/nginx"

if [ -z "$IP_MAC" ]; then
  echo "❌ 缺少参数: 小芳 Mac 的公网出口 IP"
  echo "   用法: ZMAX_ECS_PW='***' bash tools/ecs_lockdown.sh $IP_4060 <Mac的IP> [--whole-site]"
  echo "   Mac 上取法: curl -s https://ifconfig.me   (或 ipinfo.io/ip)"
  exit 2
fi
if [ -z "${ZMAX_ECS_PW:-}" ]; then
  echo "❌ 未设置 ZMAX_ECS_PW (ECS root 密码)"
  exit 2
fi

# 白名单规则
if [ "$HOME_ONLY" != "--whole-site" ]; then
  RULES="location = / {
        allow ${IP_4060};
        allow ${IP_MAC};
        deny all;
        # 主页走原逻辑
        try_files \$uri \$uri/ /index.html;
    }"
  SCOPE="只锁主页 / (推荐: 不影响 /api/relay 中转)"
else
  RULES="allow ${IP_4060};
        allow ${IP_MAC};
        deny all;"
  SCOPE="⚠️ 整站(含 /api/relay) —— 会切断 Orin/其他机器中转, 慎用"
fi

echo "════════════════════════════════════════════════════════"
echo "🔒 ECS 访问限制: $SCOPE"
echo "   允许: ${IP_4060} (静静4060) · ${IP_MAC} (小芳Mac)"
echo "   ECS:  ${ECS_HOST}"
echo "════════════════════════════════════════════════════════"

REMOTE=$(cat <<EOS
set -e
CONF="$CONF"
cp "\$CONF" "\${CONF}.bak.\$(date +%Y%m%d_%H%M%S)"   # ★ 先备份, 可秒回滚
python3 - <<'PY'
import re, io
conf = "$CONF"
src = open(conf, encoding='utf-8', errors='replace').read()
if 'ZMAX_ACL_BEGIN' in src:
    print('⚠️ 已存在白名单块 → 先移除再重加')
    src = re.sub(r'# ZMAX_ACL_BEGIN.*?# ZMAX_ACL_END\n', '', src, flags=re.S)
rules = """$RULES"""
block = "# ZMAX_ACL_BEGIN\n    " + rules.replace("\n", "\n    ") + "\n    # ZMAX_ACL_END\n"
# 插到 server { 后的第一行
i = src.find('server')
i = src.find('{', i) + 1
src = src[:i] + "\n" + block + src[i:]
open(conf, 'w', encoding='utf-8').write(src)
print('✅ 白名单已写入')
PY
$NGINX -t && echo "✅ nginx 配置语法OK" || { echo "❌ 语法错, 回滚"; cp \$(ls -t \${CONF}.bak.* | head -1) "\$CONF"; exit 1; }
$NGINX -s reload && echo "✅ 已 reload"
echo "--- 远端验证 ---"
curl -s -o /dev/null -w "  homepage(本机ECS侧): %{http_code}\n" http://127.0.0.1/ || true
EOS
)

echo "$REMOTE" | timeout 120 sshpass -p "$ZMAX_ECS_PW" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=15 \
  "root@${ECS_HOST}" "bash -s" 2>&1 | tail -12

echo
echo "════════════════════════════════════════════════════════"
echo "本地验证(应仍能访问):"
timeout 15 curl -s -o /dev/null -w "  从本机(4060): HTTP %{http_code}\n" https://datadrive.world/ || true
echo "回滚: 到 ECS 上 cp /www/server/panel/vhost/nginx/datadrive.world.conf.bak.* 覆盖后 $NGINX -s reload"
echo "════════════════════════════════════════════════════════"
