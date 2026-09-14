---
name: novnc-remote-desktop
description: Use when 要浏览器/手机远程看+操作 Linux 桌面或 websockify 转发 VNC 失败.
---

# noVNC 远程桌面 (X 桌面 → 公网浏览器)

给不在同一网络的用户提供「网页里实时看 + 真实鼠标操作」远程桌面。数据流:
**浏览器 → nginx(https) → WebSocket bridge → 反向隧道 → x11vnc(本机 :0)**

## 架构总览
```
手机浏览器
  → https://datadrive.world/novnc/vnc.html   (nginx 直服务静态文件)
  → wss://datadrive.world/novnc/websockify    (nginx 仅代理此路径)
  → ECS 127.0.0.1:6080  [自定义 asyncio bridge 或 websockify]
  → ECS 127.0.0.1:5900  (sshd 反向隧道 -R)
  → 本机 5900  x11vnc -display :0 -nopw
```

## 关键步骤
1. **本机 x11vnc**（无密码模式最省事）:
   `XAUTHORITY=$(tr '\0' '\n' < /proc/<gnome-shell-pid>/environ | grep ^XAUTHORITY | cut -d= -f2-)`
   `x11vnc -display :0 -nopw -forever -shared -noxdamage -bg`
   验证: python3 `socket.create_connection(('127.0.0.1',5900))` → recv 应见 `RFB 003.008`
2. **反向隧道**（ECS 5900 → 本机 5900）:
   `sshpass -p <pw> ssh -N -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes -R 5900:localhost:5900 root@datadrive.world`
   隧道断了要**先杀 ECS 侧占用 5900 的 sshd 转发进程**再重建: `ss -tlnp | grep :5900` 取 pid kill。
3. **WebSocket bridge**: ⚠️ 不要用 stock websockify 转发 VNC——见下方 bug。用 `scripts/vnc_ws_bridge.py`（ECS 上 systemd 常驻 `/etc/systemd/system/vncbridge.service`, `Restart=always`）。ECS 起服务用 `setsid ... &` 或 systemd，ssh 会话内 `nohup &` 会被杀。
4. **nginx**: 静态文件与 WebSocket 必须分开两个 location（bridge 不服务静态文件; 全代理会让 vnc.html 都 426）:
   - `location ^~ /novnc/` → `alias /www/wwwroot/datadrive.world/novnc/; try_files $uri $uri/ /novnc/vnc.html;` + 内嵌 `location /novnc/websockify { proxy_pass http://127.0.0.1:6080/websockify; proxy_http_version 1.1; proxy_set_header Upgrade $http_upgrade; proxy_set_header Connection "upgrade"; proxy_set_header Origin $http_origin; }`
   - 去掉密码: 删 `auth_basic`/`auth_basic_user_file` 两行。
   - reload 用 BT 面板路径 `/etc/init.d/nginx reload`（`nginx -s reload` 因 PID 文件错位常失败）。
5. **验证全链路**（python websocket-client）: 连 `wss://datadrive.world/novnc/websockify` → recv RFB → send `RFB 003.008\n` → recv 安全类型 `\x01\x01`(None) / `\x01\x02`(VNC auth)。见 `scripts/verify_ws.py`。

## 手机 URL
`https://datadrive.world/novnc/vnc.html?autoconnect=1&resize=scale&reconnect=1`
- `resize=scale` 自动缩放适配手机; 用户也可在 ⚙️ → Scaling Mode → Local Scaling。
- 手机: 单指移动鼠标/点击, 双指滚动。

## ⚠️ Pitfalls
- **websockify 0.10/0.13 转发 VNC 二进制数据坏**: 症状 = RFB 版本能收到, 但安全类型字节永远为空(0B), x11vnc 日志 `rfbProcessClientProtocolVersion: client gone`。用最简 TCP 回显服务器过 websockify 也会空 → 证明是 websockify 转发 bug 而非 VNC 侧。**修复 = 自写 ~70 行 asyncio bridge**（见 scripts/, 实测公网全通）。
- **websockets 库报 "invalid Origin header: multiple values"** → nginx 加 `proxy_set_header Origin $http_origin;` 规范化; bridge 侧 `process_request` 返回 None 忽略校验。
- **noVNC 静态资源 404/页面 426**: 分清「静态文件由谁服务」; vnc.html 是 ES module 页, 资源缺一个 UI 就白屏。逐个 curl 200 检查 app/ui.js core/rfb.js core/util/*.js。
- **ssh 会话杀后台进程**: ECS 上 `nohup cmd &` 在 ssh 断开后被杀 → 用 `setsid ... < /dev/null &` 或 systemd。
- **x11vnc -ncache 与协议**: 排查问题时去掉 `-ncache` 减少变量。

## 相关文件
- `scripts/vnc_ws_bridge.py` — 干净的 asyncio WebSocket↔TCP 双向透传 bridge（替代坏 websockify）
- `scripts/verify_ws.py` — 公网 VNC 握手验证脚本
