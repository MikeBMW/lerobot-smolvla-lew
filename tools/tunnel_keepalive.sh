#!/usr/bin/env bash
# 隧道保活 —— 解决 "tunnel inactivity timeout" 导致的地址漂移。
#
# 真因(2026-09-27 实测): localhost.run 会在**隧道内没有真实流量**时踢连接:
#   Received disconnect from 54.161.197.247 port 22:11: tunnel inactivity timeout
# ssh 自己的 ServerAliveInterval 保活不算他们的"隧道活动" ⇒ 必须走 HTTP 真取一次。
# 每分钟取一帧(15KB, 一天 21MB, 可忽略), 地址就不再漂了 ⇒ 给用户的链接能长期有效。
#
# 只读: 走 /wall.jpg(白名单内), 不碰任何控制接口。
set -u
LOG=/tmp/zmax_tunnel_keepalive.log
touch "$LOG" 2>/dev/null || LOG=/tmp/zmax_tunnel_keepalive_$$.log
TOKEN=zmax-live
URL=$(grep -oE "https://[a-z0-9]+\.lhr\.life" /var/log/zmax-tunnel.log 2>/dev/null | tail -1)
if [ -z "$URL" ]; then echo "$(date '+%F %T') 取不到隧道地址" >> "$LOG"; exit 0; fi

CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 25 \
       "$URL/wall.jpg?k=$TOKEN&w=240&q=45" 2>/dev/null)
TS=$(date '+%F %T')

if [ "$CODE" = "200" ]; then
    # 只在整十分钟记一行, 免得日志刷屏
    case "$(date +%M)" in
        00|20|40) echo "$TS OK $URL" >> "$LOG" ;;
    esac
else
    echo "$TS ✗ HTTP=$CODE 地址=$URL  (隧道可能刚被踢, 等 systemd 重连后地址会变 ⇒ 需重新发布)" >> "$LOG"
    # 地址变了就顺手重新发布一次(发布器自己判断"变了才推")
    cd /home/ubuntu/zmax_rel && ./gui-venv311/bin/python tools/publish_live_url.py >> "$LOG" 2>&1
fi
# 日志超过 2000 行就截断
if [ "$(wc -l < "$LOG" 2>/dev/null || echo 0)" -gt 2000 ]; then
    tail -500 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi
