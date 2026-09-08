# 网页 VNC 显示通道 (noVNC 全链路) — 2026-08-19 实测

> 适用: 容器无 Windows interop + Windows→容器网络隔离 (Docker Desktop 未发布端口) 时,
> 让用户零操作从浏览器看容器 GUI。最终根治 VcXsrv 崩溃 (VcXsrv 一天崩 4 次)。
> 用户铁律: 「别让我操作」— 优先零 Windows 侧操作的方案。

## 链路 (全实测)
```
用户浏览器 → https://datadrive.world/novnc/ (nginx 反代 + basic auth)
           → websockify (ECS 127.0.0.1:6080, --web noVNC)
           → SSH 反向隧道 (ECS 127.0.0.1:5900 ← 容器 127.0.0.1:5900)
           → x11vnc → Xvfb :99 → 控制台
```

## 搭建步骤 (每步实测命令)

1. **容器侧**: Xvfb + x11vnc (必须配 openbox, 见显示通道决策)
   ```bash
   Xvfb :99 -screen 0 1600x900x24 -nolisten tcp &
   DISPLAY=:99 x11vnc -display :99 -forever -shared -nopw -rfbport 5900 &
   DISPLAY=:99 openbox &   # 无 WM → 窗口无标题栏/关闭按钮!
   ```

2. **SSH 反向隧道 (容器→ECS)**:
   ```bash
   sshpass -p '<ECS密码>' ssh -o StrictHostKeyChecking=no \
     -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
     -o ExitOnForwardFailure=yes -N \
     -R 127.0.0.1:5900:127.0.0.1:5900 root@39.102.211.79
   ```
   验证: ECS 上 `ss -tln | grep 5900` 有 LISTEN。
   ⚠️ 实测 ssh -R 127.0.0.1:5900 显示绑 0.0.0.0:5900 — 必须确认安全组拦截公网
   (容器侧 `timeout 3 bash -c 'echo > /dev/tcp/ECS公网IP/5900'` 不通 = 安全)。

3. **ECS 装 websockify + noVNC**:
   ```bash
   pip3 install --break-system-packages websockify   # Ubuntu 24.04 PEP668 需此参数
   wget https://github.com/novnc/noVNC/archive/refs/tags/v1.5.0.tar.gz -O /tmp/novnc.tgz
   tar xzf /tmp/novnc.tgz && cp -r noVNC-1.5.0/* /www/wwwroot/datadrive.world/novnc/
   ```

4. **ECS 启动 websockify**:
   ```bash
   setsid nohup websockify --web=/www/wwwroot/datadrive.world/novnc \
     127.0.0.1:6080 127.0.0.1:5900 > /tmp/websockify.log 2>&1 &
   curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:6080/vnc.html   # 200
   ```

5. **nginx 反代 + basic auth** (宝塔: /www/server/panel/vhost/nginx/extension/<域名>/novnc.conf):
   ```nginx
   location ^~ /novnc/ {          # ⚠️ 必须 ^~, 否则被正则 location (\.html$ 等) 抢走!
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
   ```bash
   echo "zmax:$(openssl passwd -apr1 '<密码>')" > /www/server/nginx/conf/.novnc_passwd
   /www/server/nginx/sbin/nginx -t && kill -HUP $(cat /www/server/nginx/logs/nginx.pid)
   ```

6. **验证链路** (容器侧, gui-venv311 有 websocket 库):
   ```python
   import base64, websocket
   auth = base64.b64encode(b"zmax:<密码>").decode()
   ws = websocket.create_connection("ws://datadrive.world/novnc/websockify",
                                    header=[f"Authorization: Basic {auth}"], timeout=10)
   print(ws.recv())   # 期望: b'RFB 003.008\n' = x11vnc 握手成功
   ```

## 用户访问 URL (noVNC 参数必须显式!)
```
http://datadrive.world/novnc/vnc.html?host=datadrive.world&port=80&path=novnc/websockify&autoconnect=1
```
- ⚠️ noVNC 默认 websocket path = 'websockify' (根路径), 页面在 /novnc/ 下必须显式
  `path=novnc/websockify`, 否则 "Failed to connect to server"。
- https 版: port=443 (wss 自动), 更安全。

## 坑 (全部实测踩过)

1. **netsh portproxy 对 Docker 隔离网络无效**: portproxy 只是 Windows 本机转发,
   目标 172.17.0.2 从 Windows 不通时照样不通。实锤方法: 容器内
   `cat /proc/net/tcp | grep :170C` — 只有 LISTEN 无 ESTABLISHED = 从没收到连接。
   Docker Desktop 未发布端口的容器, Windows 侧任何手段都难通, 别浪费时间。
2. **宝塔双 nginx**: 系统 apt nginx 与宝塔编译版并存, 网站由宝塔版服务。
   系统 `nginx -T` 看不到网站配置; 操作宝塔版: 配置在 /www/server/panel/vhost/nginx/,
   PID 文件 /www/server/nginx/logs/nginx.pid, reload 用 kill -HUP (nginx -s reload 会
   因 PID 路径错位报 invalid PID)。
3. **正则 location 抢前缀**: 宝塔默认配置有 `location ~ .*\.(html|htm)?$` 等正则,
   正则优先级高于前缀 location → /novnc/vnc.html 被正则抢走静态服务 (无认证 200)。
   前缀加 `^~` 才禁止正则再查。症状: 无认证也能 200 且 Last-Modified = 文件时间。
4. **无密码 VNC 公网风险**: x11vnc -nopw 但只暴露在 basic auth 之后; 必须同时确认
   ECS 安全组拦截 5900 公网 (隧道口), 否则任何人可连。
5. **守护常驻**: 隧道进程 + websockify 都是常驻进程, 容器/ECS 重启会断,
   需 watchdog/cron 自动拉起 (与 studio 守护同模式)。
6. **websockify --web 与 nginx 反代同时服务页面**: 页面和 websocket 走同一端口 6080,
   nginx 反代整段 /novnc/ 即可, 不需要单独配 websocket 路径。
