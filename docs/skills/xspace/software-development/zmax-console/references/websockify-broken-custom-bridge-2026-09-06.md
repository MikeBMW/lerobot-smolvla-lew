# websockify 二进制转发损坏 → 自写 asyncio bridge (2026-09-06 决定性实验)

触发: noVNC 页面能开、WebSocket 能连上、RFB 版本能收到，但**安全类型响应永远为空**、
x11vnc 日志同刻 `rfbProcessClientProtocolVersion: client gone`。排 x11vnc/隧道/nginx
全正常后，锁定 websockify 本身。

## 决定性实验 (别猜, 一步定位)
用一个**简单 TCP 回显服务器** (非 VNC) 挂 5999 → `websockify 127.0.0.1:6082 127.0.0.1:5999`
→ Python websocket 客户端连 6082: 服务器主动发的 `RFB 003.008` 收到了, 但客户端发版本后
服务器回的 `\x01\x01` 变成**空** — websockify 0.10 (Ubuntu apt) 与 0.13 (pip 最新) 都坏。
结论: **websockify 的 WebSocket→TCP 转发对二进制数据不可靠, 与版本无关**。别再调参/升级。

## 正解: 自写 ~20 行 asyncio bridge (已实测全通)
`vnc_ws_bridge.py` (本机 /tmp + ECS /usr/local/bin):
- `websockets.serve(handle, "127.0.0.1", 6080, max_size=None, ping_interval=None)`
- handle: `asyncio.open_connection(*VNC_TARGET)` → 两个 task 双向透传:
  - WebSocket→TCP: `data = ws.recv(); data.encode() if isinstance(data,str)` 再 `writer.write`
  - TCP→WebSocket: `reader.read(65536)` → `ws.send(data)`
- `asyncio.wait([t1,t2], return_when=FIRST_COMPLETED)` 后 cancel pending + writer.close()
- **Origin 校验必须彻底关**: websockets 16 的 `origins=None` 仍可能报
  `invalid Origin header: multiple values` (nginx HTTP/2 转发的 Origin 被重复解析) →
  加 `process_request=lambda path, headers: None` (返回 None = 放行, 彻底跳过校验)。

## 部署持久化 (ECS ssh 会话会杀后台进程 — 别用 nohup/setsid 裸跑)
systemd service `/etc/systemd/system/vncbridge.service`:
```
[Service]
ExecStart=/usr/bin/python3 /usr/local/bin/vnc_ws_bridge.py
Restart=always
[Install] WantedBy=multi-user.target
```
`systemctl enable vncbridge && systemctl start vncbridge`。ECS 有 websockets 16.1.1
(系统 python3, 无需 pip)。

## nginx 配套两坑 (vnc.html 全 426 / Origin multiple values)
1. **bridge 不服务静态文件** → nginx 若把整个 `/novnc/` 代理给 bridge, 普通 GET
   (vnc.html/app/ui.js) 全被拒 → 页面 426 Upgrade Required。正解: 静态文件 nginx 直服,
   只有 websockify 端点走代理:
   ```nginx
   location ^~ /novnc/ {
       alias /www/wwwroot/datadrive.world/novnc/;
       index vnc.html;
       try_files $uri $uri/ /novnc/vnc.html;
       location /novnc/websockify {
           proxy_pass http://127.0.0.1:6080/websockify;
           proxy_http_version 1.1;
           proxy_set_header Upgrade $http_upgrade;
           proxy_set_header Connection "upgrade";
           proxy_set_header Origin $http_origin;   # ← 显式规范化, 否则 multiple values
       }
   }
   ```
   BT 面板改 extension conf 后必须 `/etc/init.d/nginx reload` (`nginx -s reload` 用错
   PID 文件会失败)。
2. noVNC 默认 WebSocket path 是相对根 `/websockify` (不是 `/novnc/websockify`) — 若
   页面 200 但连不上, 检查这个默认 path 有没有对应的 nginx location。

## 端到端验证 (替代 502/426 时代的不完整检查)
```python
import websocket, ssl
ws = websocket.create_connection("wss://datadrive.world/novnc/websockify", timeout=10,
    sslopt={"cert_reqs": ssl.CERT_NONE})
print(ws.recv()[:15])            # RFB 003.008
ws.send(b"RFB 003.008\n")
import time; time.sleep(1)
print(ws.recv()[:10])            # b'\x01\x01' (无密码 None) 或 b'\x01\x02' (VNC auth)
```
收到 `\x01\x01` len=2 = 全链路通 (页面 200 + 静态 200 + WS 转发健康)。手机 noVNC URL:
`vnc.html?autoconnect=1&resize=scale&reconnect=1` (resize=scale 手机自动缩放)。
