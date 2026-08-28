# 公网 noVNC 网页通道 — Z-MAX 控制台远程画面 (2026-08-19 实测全通)

> 背景: VcXsrv 一天崩 2 次 (segfault, X11 层, offscreen 压测零崩溃实锤 VcXsrv 不稳);
> Windows→容器 172.17.0.2 网络隔离 (Docker Desktop 无 -p 发布), netsh portproxy 也白搭
> (connectaddress 不可达)。终极方案: 控制台跑 Xvfb, 画面经公网 datadrive.world 网页直看,
> 零安装零操作, 手机也能看。**当前控制台显示通道 = 本方案** (2026-08-19 起)。

## 链路
```
用户浏览器 → http://datadrive.world/novnc/vnc.html (nginx 反代 + basic auth)
  → websockify (ECS 127.0.0.1:6080) → SSH 反向隧道 (ECS 127.0.0.1:5900 ← 容器 5900)
  → x11vnc (容器, DISPLAY=:99) → Xvfb :99 → studio.py
```
- 容器: Xvfb :99 + x11vnc -rfbport 5900 + studio.py DISPLAY=:99
- 容器→ECS 隧道: `sshpass ssh -N -R 127.0.0.1:5900:127.0.0.1:5900 root@39.102.211.79`
  (ExitOnForwardFailure=yes + ServerAliveInterval=30 防假活)
- ECS: `websockify --web=/www/wwwroot/datadrive.world/novnc 127.0.0.1:6080 127.0.0.1:5900`
- ECS nginx (宝塔): `location ^~ /novnc/` → proxy_pass 127.0.0.1:6080/ + Upgrade 头 + basic auth

## 安全 (必须)
- ECS 5900 公网被阿里云安全组拦截 (实测不可达) — 隧道只在内网流转
- nginx basic auth 拦网页 + websocket (`auth_basic_user_file` + openssl passwd -apr1 生成)
- 无密码 x11vnc 可接受的前提: 唯一公网入口是带认证的网页通道

## 坑 (全部实测, 2026-08-19)
1. **宝塔有双 nginx**: 系统 apt nginx (/usr/sbin, 配置 /etc/nginx) vs 宝塔 nginx
   (/www/server/nginx/sbin, 配置 /www/server/panel/vhost/nginx)。网站由宝塔版服务。
   - `nginx -T` / `nginx -s reload` 用的是 PATH 里的系统版 → 看不到网站配置 / PID 文件报错
   - 必须用 `/www/server/nginx/sbin/nginx -T` 验证, reload 用
     `kill -HUP $(cat /www/server/nginx/logs/nginx.pid)`
2. **正则 location 抢占前缀 location** (最阴): 宝塔默认配置有
   `location ~ .*\.(html|htm)?$` 等正则, 正则优先级 > 普通前缀 → /novnc/vnc.html
   被静态服务, basic auth 和 proxy 全失效 (无认证 200)。
   **修复: 前缀 location 必须写 `^~`** (`location ^~ /novnc/`) 才跳过正则。
   - 判定法: 无认证 200 + 响应头无 WWW-Authenticate + Last-Modified 是文件复制时间 = 静态服务实锤
3. **curl 127.0.0.1 不带 Host 头** → 匹配不到 server_name → 404 (不是配置错);
   测站点必须 `curl -H "Host: datadrive.world" http://127.0.0.1/...` 或直接公网域名
4. **探测 X 就绪 ≠ VcXsrv 就绪**: TCP 6000 通 (探测) 但 X server 还在初始化 → studio 起
   即崩 (could not connect to display)。切换前必须 `xwininfo -root -display ...` 验证握手。
5. **VcXsrv 崩 2 次特征**: ① 320s 后 `QObject::killTimer: Timers cannot be stopped
   from another thread` (代码已在 08-19 修过 _oneshot 桥, 此为 VcXsrv 下暴露) ② 几分钟后
   纯 X 层 segfault (无 killTimer 警告)。Xvfb 通道同代码零崩溃 → 崩在 VcXsrv。

## 验证命令
```bash
# 网页认证
curl -s -o /dev/null -w "%{http_code}\n" http://datadrive.world/novnc/vnc.html          # 401
curl -s -o /dev/null -w "%{http_code}\n" -u zmax:<pw> http://datadrive.world/novnc/vnc.html  # 200
# websocket 全链路 (python, gui-venv311 有 websocket 库)
ws = websocket.create_connection("ws://datadrive.world/novnc/websockify",
      header=[f"Authorization: Basic {base64.b64encode(b'zmax:<pw>').decode()}"])
ws.recv()[:30]  # 应收到 b'RFB 003.008\n' = x11vnc 握手成功
# 容器侧看 x11vnc 是否收到连接
cat /proc/net/tcp | grep ":170C"  # 有 ESTABLISHED = 有连接
```
