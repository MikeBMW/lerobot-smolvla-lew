#!/usr/bin/env python3
"""vnc_ws_bridge.py — WebSocket↔TCP VNC 代理 (websockify 替代, 2026-09-06 实测可靠)

背景: websockify (0.10 Ubuntu / 0.13 pip 都试过) 转发 VNC 二进制数据有 bug —
用最简单 TCP 回显服务器验证: 服务端主动发的数据经 websockify 后变空 (安全类型 b''),
不是 x11vnc/隧道/nginx 的问题, 是 websockify 本身 TCP→WS 方向损坏。
自写 asyncio 双向透传 bridge 后 RFB + 安全类型 (\\x01\\x01) 完整到达。

部署: ECS 上放 /usr/local/bin/, systemd 服务 (Restart=always) 保活 —
ssh 会话断开会杀 nohup/setsid 后台进程, systemd 才可靠。

注意:
- websockets>=16 默认校验 Origin, nginx 转发可能带多个 Origin → 400 "multiple values";
  用 origins=None 放行 (nginx 已做 HTTPS/路径层限制)。
- 监听 127.0.0.1:6080, 由 nginx location ^~ /novnc/ (及 location = /websockify) 代理到此处。
"""
import asyncio
import websockets

VNC_TARGET = ("127.0.0.1", 5900)
LISTEN_PORT = 6080


async def pipe(ws, reader, writer):
    """WebSocket → TCP 方向"""
    try:
        while True:
            try:
                msg = await ws.recv()
            except Exception:
                break
            data = msg if isinstance(msg, bytes) else msg.encode()
            if not data:
                continue
            writer.write(data)
            await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def pipe_back(ws, reader, writer):
    """TCP → WebSocket 方向"""
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            await ws.send(data)
    except Exception:
        pass


async def handle(ws):
    try:
        r, w = await asyncio.open_connection(*VNC_TARGET)
    except Exception as e:
        print(f"[bridge] 连 VNC 失败: {e}")
        await ws.close()
        return
    print("[bridge] 客户端已连接 → VNC")
    t1 = asyncio.create_task(pipe(ws, r, w))
    t2 = asyncio.create_task(pipe_back(ws, r, w))
    done, pending = await asyncio.wait([t1, t2], return_when=asyncio.FIRST_COMPLETED)
    for t in pending:
        t.cancel()
    try:
        w.close()
    except Exception:
        pass
    print("[bridge] 连接关闭")


async def main():
    print(f"[bridge] VNC WS 代理监听 :{LISTEN_PORT} → {VNC_TARGET[0]}:{VNC_TARGET[1]}")
    async with websockets.serve(handle, "127.0.0.1", LISTEN_PORT,
                                max_size=None, ping_interval=None,
                                origins=None):  # 允许所有 Origin (nginx 层已限路径)
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
