# noVNC 网页远程桌面实测 (2026-09-06) — websockify 二进制 bug + 自写桥

需求: 手机/浏览器远程看并真实操作 Linux 桌面 (控制台 Qt 窗口)。链路: 浏览器 noVNC → nginx(https) → WebSocket 桥 → VNC 服务 (x11vnc) → X 桌面。

## ★ websockify 转发二进制数据有 bug (0.10 与 0.13 都实测)
- 症状: WS 连上 + 收到 RFB 版本后, 后续二进制 (安全类型字节 `\x01\x02`) 永远收不到 — recv 返回空/连接断; x11vnc 日志 `rfbProcessClientProtocolVersion: client gone`
- **决定性验证**: 用一个最简单的 TCP 回显服务器 (非 VNC) 过 websockify → 照样空 → 证明是 websockify 转发层坏, 不是 x11vnc/隧道/nginx
- 排查顺序建议: 先本机 TCP 直连 VNC (`python3` socket 连 5900, 收 RFB + 发版本 + 收安全类型 `\x01\x01`) 确认 VNC 正常 → 再 ECS 隧道出口测 → 再 websockify → 逐层隔离

## 自写 asyncio 双向桥替代 (验证可用, ~50 行)
```python
# vnc_ws_bridge.py — WebSocket ↔ TCP 双向透传 (websockets 库, 无 websockify bug)
import asyncio, websockets
async def pipe(ws, r, w):          # WS → TCP
    try:
        while True:
            msg = await ws.recv()
            data = msg if isinstance(msg, bytes) else msg.encode()
            if data: w.write(data); await w.drain()
    except Exception: pass
    finally:
        try: w.close()
        except Exception: pass
async def pipe_back(ws, r, w):     # TCP → WS
    try:
        while True:
            data = await r.read(65536)
            if not data: break
            await ws.send(data)
    except Exception: pass
async def handle(ws):
    r, w = await asyncio.open_connection("127.0.0.1", 5900)
    t1 = asyncio.create_task(pipe(ws, r, w)); t2 = asyncio.create_task(pipe_back(ws, r, w))
    done, pending = await asyncio.wait([t1,t2], return_when=asyncio.FIRST_COMPLETED)
    for t in pending: t.cancel()
    try: w.close()
    except Exception: pass
async def main():
    async with websockets.serve(handle, "127.0.0.1", 6080,
                                max_size=None, ping_interval=None,
                                process_request=lambda p,h: None):  # 忽略 Origin
        await asyncio.Future()
asyncio.run(main())
```
- **必须 `process_request` 忽略 Origin 校验** — 经 nginx 转发后 websockets 库报 `invalid Origin header: multiple values` (HTTP/2 → 后端时 nginx 重复/多值 Origin)
- 部署用 systemd (`Restart=always`) 或 ECS 上 setsid, 别裸 nohup (ssh 断开杀进程)

## nginx 配置: 静态文件 vs WebSocket 端点必须分离
- **坑: `/novnc/` 全部代理给纯 WS 桥 → 普通 GET vnc.html 返回 426 Upgrade Required** (页面都打不开)
- 正确: `location ^~ /novnc/` 静态 alias 到 noVNC 目录 + 内嵌 `location /novnc/websockify` 走桥
- **noVNC 页面默认连 `/websockify` (根路径, 不是 `/novnc/websockify`)** — 裸 URL 打开页面但 WS 连根路径 → 404 "连不上"; 加 `location = /websockify` 或 URL 带 `?path=novnc/websockify`
- 响应头 `www-authenticate: Basic realm="..."` = nginx auth_basic; 密码文件权限要 644 (600 root 时 nginx www 用户读不了 → 500)

## 其他实测
- x11vnc 无密码: `-nopw` (客户端收安全类型 `\x01\x01`); 有密码 `-rfbauth ~/.vnc/zmax.pass` (`\x01\x02`)
- 反向隧道: `ssh -N -R 5900:localhost:5900 root@ECS` — 之前占用 5900 的旧 sshd 转发先 `kill -9` 释放再建; `ServerAliveInterval=30` 防断
- 本机 headless 验证受限 (snap chromium/firefox 沙箱写不了 /tmp) → 装 playwright venv: `python3 -m venv` + `pip install playwright` + `playwright install chromium --with-deps`, launch 加 `--use-gl=swiftshader --enable-unsafe-swiftshader` 软件渲染 (WebGL 页面也能验)
- 验证链: 页面 200 → 静态资源全 200 → WS 连上收 RFB → 发版本收安全类型 → 才算通
