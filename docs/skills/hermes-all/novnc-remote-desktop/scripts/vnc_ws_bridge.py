#!/usr/bin/env python3
"""vnc_ws_bridge.py — 干净的双向 WebSocket↔TCP 代理 (替代坏掉的 websockify)
监听 :6080 → 转发到 127.0.0.1:5900 (VNC)。纯 asyncio + websockets 库。
实测: stock websockify 0.10/0.13 转发 VNC 二进制数据坏 (RFB 能收到但安全类型字节为空),
本 bridge 公网全链路验证通过。允许任意 Origin (nginx 层已做 HTTPS/路径限制)。
ECS 部署: /etc/systemd/system/vncbridge.service, Restart=always。
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
    """一个 VNC 客户端连接"""
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


def process_request(path, request_headers):
    """完全忽略 Origin 校验 (返回 None = 继续处理)"""
    return None


async def main():
    print(f"[bridge] VNC WS 代理监听 :{LISTEN_PORT} → {VNC_TARGET[0]}:{VNC_TARGET[1]}")
    async with websockets.serve(handle, "127.0.0.1", LISTEN_PORT,
                                max_size=None, ping_interval=None,
                                process_request=process_request):
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
