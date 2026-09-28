#!/usr/bin/env bash
# 🛰 ECS 端口转发: 把工位机的「场景叠加」只读通道(闸门 8891)挂到 datadrive.world 的稳定路径下
#
# 老倪 2026-09-28: 「http://10.163.146.78:8791/overlay 把这个页面, 通过ECS端口转发,
#                   发到我的华为手机APP上」
#
# 为什么走闸门 8891 而不是直接转 8791:
#   ✅ 只读白名单(只放行 GET 白名单路径) + POST 一律 403 ⇒ 公网上动不了机器人、也点不了生成按钮
#   ✅ 8791 上还有手动控制/生成接口, 永不出网
#
# 拓扑:
#   手机 ──HTTPS──► https://datadrive.world/ov/...  (ECS nginx, 443)
#                        │ proxy_pass 127.0.0.1:18791   (MJPEG 关缓冲)
#                        ▼
#                   反向隧道 ssh -R (本机主动出网建立, 工位机不开任何入站端口)
#                        ▼
#                   127.0.0.1:8891 = tunnel_proxy 只读闸门  ──►  127.0.0.1:8791 (叠加页/流)
#
# 用法 (需要 ECS 的 SSH 权限; 项目既有约定: 用 ZMAX_ECS_PW 或已配免密):
#   bash tools/ecs_overlay_forward.sh --check     # 只体检本地(不动 ECS)
#   ZMAX_ECS_PW='...' bash tools/ecs_overlay_forward.sh --apply    # 建隧道 + ECS 挂路径
#   bash tools/ecs_overlay_forward.sh --verify    # 公网端到端验证(含只读闸门 403 复核)
#   ZMAX_ECS_PW='...' bash tools/ecs_overlay_forward.sh --revert   # 撤掉(nginx 块 + 本地 unit)
set -uo pipefail

ECS_HOST="${ECS_HOST:-39.102.211.79}"
ECS_USER="${ECS_USER:-root}"
ECS_DOMAIN="${ECS_DOMAIN:-datadrive.world}"
# ── 通道: overlay(叠加页 8791) | station(工位总览 8793) ──────────────────────────
# 老倪 2026-09-28: 「http://10.163.146.78:8793/station 把这个通道, 推流到 ECS」
# 两条通道共用同一套拓扑与安全口径(只读闸门 + 反向隧道 + nginx 子路径), 只是端口/前缀/unit 不同。
CH="${ZMAX_OV_CHANNEL:-overlay}"
if [ "$CH" = "station" ]; then
  PREFIX="${ZMAX_OV_PREFIX:-/st/}"
  REMOTE_PORT="${ZMAX_OV_REMOTE_PORT:-18793}"
  GATE="${ZMAX_OV_GATE:-127.0.0.1:8893}"
  UP="${ZMAX_OV_UP:-127.0.0.1:8793}"
  UNIT=zmax-ecs-station.service
  ENVF_PATH=/etc/zmax-ecs-station.env
  LOGF=/var/log/zmax-ecs-station.log
  MARK="zmax-station-forward"
  # 注意: VPROBE/VEXTRA/VPOST 是**闸门/上游侧的路径**(不含公网前缀) —— 前缀由 nginx 剥掉。
  VPROBE="/station?k=${ZMAX_OV_TOKEN:-zmax-live}"
  VEXTRA="/station/status?k=${ZMAX_OV_TOKEN:-zmax-live} /snapshot/overlay_arm.jpg?k=${ZMAX_OV_TOKEN:-zmax-live} /aoi_gold.mjpg?k=${ZMAX_OV_TOKEN:-zmax-live}"
  VPOST="/station/arm?k=${ZMAX_OV_TOKEN:-zmax-live}"
  HINT="手机/浏览器开: https://${ZMAX_OV_DOMAIN:-datadrive.world}${ZMAX_OV_PREFIX:-/st/}station?k=${ZMAX_OV_TOKEN:-zmax-live}"
else
  PREFIX="${ZMAX_OV_PREFIX:-/ov/}"          # 公网路径前缀
  REMOTE_PORT="${ZMAX_OV_REMOTE_PORT:-18791}"  # ECS 侧本机回环端口(nginx 反代用)
  GATE="${ZMAX_OV_GATE:-127.0.0.1:8891}"    # 只读闸门
  UP="${ZMAX_OV_UP:-127.0.0.1:8791}"
  UNIT=zmax-ecs-ov.service
  ENVF_PATH=/etc/zmax-ecs-ov.env
  LOGF=/var/log/zmax-ecs-ov.log
  MARK="zmax-overlay-forward"
  VPROBE="/overlay?k=${ZMAX_OV_TOKEN:-zmax-live}"
  VEXTRA="/live?k=${ZMAX_OV_TOKEN:-zmax-live} /live.json?k=${ZMAX_OV_TOKEN:-zmax-live} /wall.jpg?k=${ZMAX_OV_TOKEN:-zmax-live}&w=240&q=45"
  VPOST="/boxes/delete?k=${ZMAX_OV_TOKEN:-zmax-live}"
fi
TOKEN="${ZMAX_OV_TOKEN:-zmax-live}"
VHOST="/www/server/panel/vhost/nginx/${ECS_DOMAIN}.conf"   # 宝塔 nginx vhost
MARK_BEGIN="# >>> ${MARK} (auto) >>>"
MARK_END="# <<< ${MARK} (auto) <<<"
PW="${ZMAX_ECS_PW:-}"
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=12 -o ServerAliveInterval=20 -o ServerAliveCountMax=3"
if [ -n "$PW" ]; then SSH="sshpass -p $PW ssh $SSH_OPTS"; else SSH="ssh $SSH_OPTS"; fi
PUB="https://${ECS_DOMAIN}${PREFIX%/}"

ok(){ echo "  ✅ $*"; }; bad(){ echo "  ❌ $*"; }

check() {
  echo "── 本地体检 (通道=$CH) ──"
  ss -tlnp 2>/dev/null | grep -q ":${GATE##*:}" && ok "只读闸门在听 $GATE" || bad "闸门没在听 $GATE (overlay: zmax-tunnel-proxy / station: zmax-station-gate)"
  curl -s -o /dev/null -w "     闸门 ${VPROBE} → HTTP %{http_code}\n" -m 15 "http://${GATE}${VPROBE}"
  curl -s -o /dev/null -w "     闸门 POST(应 403) → HTTP %{http_code}\n" -m 15 -X POST "http://${GATE}${VPOST}"
  ss -tlnp 2>/dev/null | grep -q ":${UP##*:}" && ok "上游 $UP 在听" || bad "上游 $UP 没在听"
  echo "── ECS 侧 ($ECS_USER@$ECS_HOST) ──"
  if timeout 25 $SSH "$ECS_USER@$ECS_HOST" 'echo SSH_OK; nginx -v 2>&1 | head -1' 2>&1 | head -3 | sed 's/^/     /'; then
    :
  fi
}

apply_local_unit() {
  echo "── ① 本地反向隧道 (systemd: $UNIT) ──"
  # 口令不进 unit 文件(644) —— 单独 600 的 EnvironmentFile; 免密时 SSH 走 key, 该文件不写
  if [ -n "$PW" ]; then
    printf 'SSHPASS=%s\n' "$PW" | sudo tee $ENVF_PATH >/dev/null
    sudo chmod 600 $ENVF_PATH
    SSH_CMD="/usr/bin/sshpass -e /usr/bin/ssh"
    ENVF="EnvironmentFile=$ENVF_PATH"
  else
    SSH_CMD="/usr/bin/ssh"
    ENVF="# (免密: 用 ubuntu 的 ~/.ssh key, 无口令文件)"
  fi
  sudo tee /etc/systemd/system/$UNIT >/dev/null <<EOF
[Unit]
Description=Z-MAX ECS 反向隧道 [$CH] (只读闸门 $GATE → ECS 127.0.0.1:${REMOTE_PORT})
After=network-online.target
Wants=network-online.target

[Service]
User=ubuntu
${ENVF}
ExecStart=${SSH_CMD} -NT -o StrictHostKeyChecking=no -o ServerAliveInterval=20 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -R 127.0.0.1:${REMOTE_PORT}:${GATE} ${ECS_USER}@${ECS_HOST}
Restart=always
RestartSec=10
StandardOutput=append:${LOGF}
StandardError=append:${LOGF}

[Install]
WantedBy=multi-user.target
EOF
  sudo systemctl daemon-reload
  sudo systemctl enable --now $UNIT >/dev/null 2>&1
  sleep 6
  systemctl is-active $UNIT >/dev/null && ok "$UNIT 已起(常驻自愈)" || bad "$UNIT 没起来 — 看 journalctl -u $UNIT"
}

apply_ecs_vhost() {
  echo "── ② ECS nginx 挂 ${PREFIX} ──"
  $SSH "$ECS_USER@$ECS_HOST" "set -e
    test -f '$VHOST' || { echo '找不到 vhost: $VHOST'; exit 2; }
    cp -a '$VHOST' '$VHOST.bak_zmaxov_\$(date +%Y%m%d_%H%M%S)'
    if grep -q 'zmax-overlay-forward' '$VHOST'; then echo '已有块, 先删旧的'; sed -i '/$MARK_BEGIN/,/$MARK_END/d' '$VHOST'; fi
    python3 - <<'PYEOF'
import io,os
p='$VHOST'; s=io.open(p,encoding='utf-8',errors='replace').read()
blk='''$MARK_BEGIN
  location ${PREFIX} {
      proxy_pass http://127.0.0.1:${REMOTE_PORT}/;
      proxy_http_version 1.1;
      proxy_set_header Host \$host;
      proxy_set_header X-Real-IP \$remote_addr;
      proxy_buffering off;          # MJPEG 必须关, 否则画面卡成一帧
      proxy_request_buffering off;
      proxy_read_timeout 3600s;
      proxy_send_timeout 3600s;
      chunked_transfer_encoding off;
  }
$MARK_END
'''
i=s.rfind('}')          # 插到 server{} 末尾(最后一个右括号前)
s=s[:i]+blk+s[i:]
io.open(p,'w',encoding='utf-8').write(s)
print('已插入 location 块')
PYEOF
    if /www/server/nginx/sbin/nginx -t 2>&1 | tail -2; then
      /www/server/nginx/sbin/nginx -s reload && echo 'nginx 已 reload'
    else
      echo 'nginx -t 失败 → 回滚'; sed -i '/$MARK_BEGIN/,/$MARK_END/d' '$VHOST'; /www/server/nginx/sbin/nginx -t
      exit 3
    fi
    curl -s -o /dev/null -w '   ECS 本机回环: HTTP %{http_code}\n' --max-time 20 'http://127.0.0.1:${REMOTE_PORT}${VPROBE}'
  " 2>&1 | sed 's/^/     /'
}

verify() {
  echo "── ③ 公网端到端 (通道=$CH, 前缀=$PREFIX) ──"
  for p in "$VPROBE" $VEXTRA; do
    printf "  %-46s → " "$p"
    curl -s -o /tmp/ovf.out -w "HTTP %{http_code} · %{size_download}B\n" -m 40 "${PUB}${p}"
  done
  printf "  %-46s → " "POST ${VPOST} (应 403)"
  curl -s -o /dev/null -w "HTTP %{http_code}\n" -m 25 -X POST -H 'Content-Type: application/json' \
       -d '{}' "${PUB}${VPOST}"
  echo "  手机 APP 里填: ${PUB}${VPROBE}"
  [ -n "${HINT:-}" ] && echo "  $HINT"
}

case "${1:---check}" in
  --check) check ;;
  --apply)
    check; apply_local_unit; apply_ecs_vhost; verify
    echo "── 做完后: 重打 APK 把候选口指向 ${PUB}/overlay?k=$TOKEN (或手机长按手改地址) ──"
    ;;
  --verify) verify ;;
  --revert)
    echo "── 撤销 ──"; sudo systemctl disable --now $UNIT >/dev/null 2>&1 && ok "已停 $UNIT"
    $SSH "$ECS_USER@$ECS_HOST" "sed -i '/$MARK_BEGIN/,/$MARK_END/d' '$VHOST' && /www/server/nginx/sbin/nginx -t && /www/server/nginx/sbin/nginx -s reload && echo '已撤 nginx 块'" 2>&1 | sed 's/^/     /'
    ;;
  *) echo "用法: $0 [--check|--apply|--verify|--revert]"; exit 2 ;;
esac
