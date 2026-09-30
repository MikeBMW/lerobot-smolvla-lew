# websockify 转发 VNC 二进制已证伪 → 自写 asyncio bridge (2026-09-06 决定性实验)

触发: 搭 noVNC 网页远程桌面 (x11vnc + ECS 中继) 时"WS 连上 + 收到 RFB 首帧, 但安全类型
永远空 / `b''`", 或 x11vnc 日志反复 `rfbProcessClientProtocolVersion: client gone`。
**本文件是 remote-desktop-ecs-relay.md 的更正 — 该文件里"websockify 若已在跑直接复用"的
指引已过时, 以本文件为准。**

## 决定性实验 (排除法定位 websockify)
1. 本机直连 x11vnc 5900: RFB 收到 + 安全类型 `\x01\x01` (无密码) / `\x01\x02` (带密码) — 正常
2. ECS 隧道出口 127.0.0.1:5900 直测: 同样正常 → 隧道没坏
3. ECS websockify (0.13) 本地 ws 连: RFB 收到但安全类型空 → websockify 嫌疑
4. **纯 TCP 回显服务器** (bind 5999, accept 后主动 `send(b'RFB 003.008\n')` 再 `send(b'\x01\x01')`)
   过 websockify → 客户端只收到第一段, 服务器主动发的后续字节**全空**
5. 结论: websockify (Ubuntu 0.10 与 pip 0.13 均测) **TCP→WS 方向主动推送损坏** —
   不是 x11vnc / 隧道 / nginx 的问题。老进程能"通"是因为只验证到 RFB 首帧就误判成功。

## 修复: 自写 bridge (scripts/vnc_ws_bridge.py, ~20 行核心)
- 纯 asyncio + `websockets` 库双向透传 (WS→TCP 一个 task, TCP→WS 一个 task, FIRST_COMPLETED 收尾)
- 端到端公网验证: RFB 003.008 + 安全类型 `\x01\x01` 完整到达 → 真正可用
- 目标机需有 `websockets` 库 (ECS: `python3 -c "import websockets"`; 无则 pip 装)
- 监听 127.0.0.1:6080, 由 nginx `location ^~ /novnc/` + `location = /websockify` 代理进入

## 部署坑 (每个都卡过)
- **ssh 会话断开会杀 nohup/setsid 后台进程** (ECS 上反复"启动即死"根因) → 必须 systemd
  服务: `/etc/systemd/system/vncbridge.service` (ExecStart + Restart=always), enable+start
- websockets>=16 默认校验 Origin → nginx 转发多个 Origin 头报 400
  `invalid Origin header: multiple values` → bridge 侧 `origins=None` 放行 (nginx 已限路径)
- websockify `--daemon` 模式在部分环境也退 (日志只到 "In exit") — 别纠缠, 直接换 bridge
- ECS 上起后台进程的可靠姿势: 脚本落盘到 ECS 再 `setsid ... < /dev/null & disown`,
  或直接 systemd — 单条 sshpass ssh 'nohup ... &' 常静默失败 (无输出 exit 0)

## 验证 (交付前自测, 别让用户当测试员)
```python
import websocket, ssl, time
ws = websocket.create_connection('wss://<host>/novnc/websockify', timeout=15,
    sslopt={'cert_reqs': ssl.CERT_NONE}, header={'Origin': 'https://<host>'})
print(ws.recv()[:15])            # 期望 b'RFB 003.008\n'
ws.send(b'RFB 003.008\n')
time.sleep(1)
print(ws.recv()[:10])            # 期望 b'\x01\x01' (无密码) — 之前 websockify 这里恒空
```
注意: websocket-client 库 URL 内嵌 `user:pass@` 不转 Authorization → 手动加 header;
无 Origin header 时测试会过但浏览器 (带 Origin) 可能被拒 → 两个 case 都测。
