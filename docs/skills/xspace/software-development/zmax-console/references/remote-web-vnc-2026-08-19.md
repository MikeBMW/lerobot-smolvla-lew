# 容器 GUI 远程可视化 — 公网 noVNC 通道 (2026-08-19 实测全通)

## 触发场景
- VcXsrv 崩/用户看不到窗口, 且用户**不愿做 Windows 侧操作**
- 容器无 wsl.exe interop (无法替用户启动/配置 Windows 侧程序)
- Windows→容器网络不通 (Docker bridge 172.17.0.x 隔离, netsh portproxy 也白搭 —
  portproxy 只是本机转发, connectaddress 不可达时照样失败, VNC 报 "connection closed unexpectedly")
- 判定: 容器 5900 无任何 ESTABLISHED 记录 = Windows 侧流量根本没到容器

## 链路 (全部公网, 零 Windows 操作)
```
用户浏览器 → https://datadrive.world/novnc/vnc.html → nginx(^~ /novnc/ + basic auth)
  → websockify(ECS 127.0.0.1:6080) → SSH反向隧道(ECS 127.0.0.1:5900 ← 容器 5900)
  → x11vnc(:99) → Xvfb → 控制台
```

## 搭建步骤 (每步实测)
1. **SSH 反向隧道** (容器 → ECS, 常驻):
   `sshpass -p <pw> ssh -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes -N -R 127.0.0.1:5900:127.0.0.1:5900 root@<ECS>`
   验证: ECS `ss -tln | grep 5900` 出现 LISTEN。
   ⚠️ 公网 5900 裸奔风险: 实测阿里云安全组默认拦截 5900 入站 → 隧道只在 ECS 内网被
   websockify 消费。**必须验证**: 容器 `timeout 3 bash -c 'echo > /dev/tcp/<ECS公网IP>/5900'` 不通才安全。
2. **ECS 装 websockify + noVNC**:
   `pip3 install --break-system-packages websockify` (Ubuntu 24.04 PEP668 必须 break)
   noVNC: 下载 v1.5.0 tarball 解压到网站目录 `/www/wwwroot/datadrive.world/novnc/`
3. **websockify 启动**: `setsid nohup websockify --web=<novnc目录> 127.0.0.1:6080 127.0.0.1:5900 &`
   (target=127.0.0.1:5900 即隧道入口)
4. **nginx 反代 + 认证** (宝塔面板: 配置写 extension/datadrive.world/novnc.conf,
   datadrive.world.conf 里已有 `include extension/datadrive.world/*.conf`):
   ```
   location ^~ /novnc/ {
       auth_basic "Z-MAX Console";
       auth_basic_user_file /www/server/nginx/conf/.novnc_passwd;
       proxy_pass http://127.0.0.1:6080/;
       proxy_http_version 1.1;
       proxy_set_header Upgrade $http_upgrade;
       proxy_set_header Connection "upgrade";
       proxy_set_header Host $host;
       proxy_read_timeout 3600s;
       proxy_send_timeout 3600s;
   }
   ```
   密码文件: `echo "zmax:$(openssl passwd -apr1 <pw>)" > /www/server/nginx/conf/.novnc_passwd`
5. **重载宝塔 nginx**: `kill -HUP $(cat /www/server/nginx/logs/nginx.pid)` —
   `nginx -s reload` 会找错 PID 文件 (系统 apt nginx 的 /run/nginx.pid)。

## 关键坑 (全部实测)
1. **必须 `^~ /novnc/` 前缀**: 网站配置里有 `location ~ .*\.(html|htm)?$` 正则,
   正则优先级高于普通前缀 location → /novnc/vnc.html 被静态服务抢走 (无认证直接 200)。
   `^~` 表示命中前缀后不再查正则 → auth 才生效 (401/200 验证)。
2. **两套 nginx 并存** (宝塔编译版 + apt 系统版): `nginx -T` 用的是系统版,
   看不到宝塔配置! 必须 `/www/server/nginx/sbin/nginx -T` 验证。curl 测本地必须带
   `-H "Host: datadrive.world"` 否则落到 default server 404。
3. **noVNC URL 必须显式 path**: vnc.html 默认 websocket 路径是相对页面的 'websockify',
   页面在 /novnc/ 下时默认连 /websockify (根路径 404)。完整参数:
   `?host=datadrive.world&port=443&path=novnc/websockify&autoconnect=1&reconnect=1&reconnect_delay=2000`
   (reconnect 参数让控制台崩溃重启后画面自动恢复, 用户无感)
4. **链路验证**: python websocket 客户端连 `ws://host/novnc/websockify` (带
   `Authorization: Basic base64(user:pw)` 头), 收到 `RFB 003.008\n` = 全链路通。
5. **安全双保险**: 公网 VNC 端口被安全组拦 + nginx basic auth (401 拦截在 websocket 握手前)。

## 与 VcXsrv 的关系
- VcXsrv 通道 (容器→Windows 6000) 零配置但 VcXsrv 本身不稳 (当日崩 2 次)。
- 公网通道稳定, 手机也能看, 是"用户不看配置"时的终极方案。
- 用户明确"别让我操作"时: 优先公网通道, 别让用户粘 netsh/portproxy。
