# 公网中继: 内网真机远程桌面经 ECS 反向隧道 + nginx (2026-09-06 实测)

触发: 本机 x11vnc+noVNC 已起 (见 remote-desktop-x11vnc-novnc.md), 但用户不在同一内网
(192.168.1.x) 连不上 → 走公网 ECS (datadrive.world) 中继。整条链路端到端验证过。

## 链路
```
浏览器 wss://datadrive.world/novnc/websockify
  → ECS nginx (location ^~ /novnc/ → 127.0.0.1:6080)
  → ECS websockify --web=<novnc目录> 127.0.0.1:6080 → 127.0.0.1:5900
  → ECS sshd 5900 (反向隧道 -R 监听点)
  → 反向 SSH 隧道 → 本机 x11vnc :5900
```

## 建链步骤 (已验证)
1. 本机起 x11vnc (取 XAUTHORITY, 见 remote-desktop-x11vnc-novnc.md)。
2. 反向隧道 (ECS 的 5900 → 本机 5900):
   ```bash
   nohup sshpass -p '<ECS密码>' ssh -o StrictHostKeyChecking=no -o ServerAliveInterval=30 \
     -o ExitOnForwardFailure=yes -N -R 5900:localhost:5900 root@datadrive.world \
     > /tmp/vnc_tunnel.log 2>&1 &
   ```
   **先清 ECS 上残留占 5900 的僵尸 sshd 转发** (`ss -tlnp | grep :5900` → kill 其 pid),
   否则 "remote port forwarding failed for listen port 5900"。
3. ECS websockify 若已在跑 (旧进程 `--web=<novnc目录>` 模式) 直接复用; 本地握手验证:
   python socket 连 127.0.0.1:6080 发 `GET /websockify` + Upgrade/Connection/Sec-WebSocket-* 头
   → 必须 **101 Switching Protocols**。

## 验证 (先于交付 — 别让用户当测试员)
- 页面: `curl -s -o /dev/null -w '%{http_code}' https://datadrive.world/novnc/vnc.html` = 200
- **WS 全链路**: python websocket 连 `wss://datadrive.world/novnc/websockify` → 收 `RFB 003.008\n`
  = 服务端到 x11vnc 全通。URL 内嵌凭据 websocket 库**不转 Authorization** → 手动加 header
  `Authorization: Basic base64(user:pass)`。
- ECS 侧 `ss -tln | grep 5900` 有监听 = 隧道活; 本机 x11vnc 日志出现连接记录 = 真正到达。

## 坑 (每个都真实卡过)
- **noVNC 默认 WS 端点 = 同源根路径 `/websockify`, 不是 `/novnc/websockify`** — 页面 200 但
  连接 "vnc连不上" 的隐藏主因。vnc.html 不带全 host/port/path 参数时 JS 拼 `wss://host/websockify`
  (根)。修: nginx 加 `location = /websockify { proxy_pass http://127.0.0.1:6080/websockify; ... }`
  (与 `location ^~ /novnc/` 并存)。两个路径都要代理。
- **BT 面板 nginx (宝塔)**: `nginx -s reload` 报 invalid PID (`/run/nginx.pid` 空) → 必须
  `/etc/init.d/nginx reload` (宝塔 nginx 在 /www/server/nginx/sbin/nginx); 验证加载用
  `/www/server/nginx/sbin/nginx -T | grep <location名>`。extension conf 目录:
  `/www/server/panel/vhost/nginx/extension/datadrive.world/*.conf` (主 conf include)。
- **auth_basic 密码文件权限**: 600 root → nginx worker (www 用户) 读不了 → **500 而非 401**;
  chmod 644。401 vs 500 区分: 401=认证流程正常密码错, 500=文件权限/格式问题。
- ECS 无 htpasswd → `openssl passwd -apr1 <pw>` 生成 hash 手写 `user:hash` 进文件。
- **heredoc 写 nginx conf 的 `\$` 转义 bug**: 普通 heredoc 写 `\$http_upgrade` 会原样留 `\$`
  → nginx 变量变字面量 → Upgrade 头空。用引号 heredoc (`<<'EOF'`) 写 `$http_upgrade` 不转义。
- ECS noVNC 目录是残缺源码版 (缺 core/util.js 等模块) → 页面 UI 起不来: 把本地
  `/usr/share/novnc/` (1.3.0 完整模块树) rsync/scp 覆盖到 ECS websockify 的 --web 目录。
- 用户端老打不开时:**先自己用 python websocket 走完整公网路径握手**证明服务端 OK, 再让用户
  硬刷新/隐身窗 (浏览器缓存旧 401/404 会让"已修复"看起来没修)。
- **用户明确"不要密码"** (老倪: 远程通道不想输认证) → sed 删 auth_basic 两行 + reload 即可;
  裸奔风险提示一句, 别反复劝。
- 交付链接: 用户问"链接给我/打开什么网址"时给**纯 URL 单独成行可点** (飞书渲染); 保留认证时给
  `https://user:pass@host/...` 内嵌链接 (部分浏览器会拦带密码 URL, 拦了就只给裸 URL + 账号密码分行)。

## 会话状态注记 (不要当长期事实)
- 09-06 最终: 网页认证已删 (auth_basic 两行 sed 掉), datadrive.world/novnc/vnc.html 免密可开;
  x11vnc 密码仍 zmax2026 (VNC 层). 反向隧道/websockify 为 nohup 进程, 重启后需重建。
