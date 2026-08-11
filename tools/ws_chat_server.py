#!/usr/bin/env python3
"""Z-MAX 群聊 WebSocket 服务端 (2026-08-10 静静 · 修复 chat.html 无消息)
协议 (chat.html):
  客户端发: {type:"hello", from} / {type:"msg", from, msg}
  服务端回: {type:"history", msgs:[{from,msg,time,id}]}  (连接时)
           {type:"msg", from, msg, time, id}             (广播)
用法:
  python ws_chat_server.py                # 默认 0.0.0.0:8765
  python ws_chat_server.py --port 8765 --history 200
  # 配合 nginx: location /chat { proxy_pass http://127.0.0.1:8765; proxy_http_version 1.1; Upgrade 头 }
依赖: pip install websockets
"""
import argparse, asyncio, json, time, uuid, os

import websockets

# 历史消息 (内存; 生产可换 SQLite/Redis)
HISTORY = []          # [{id, from, msg, time}]
HISTORY_MAX = 200
# 在线用户
CLIENTS = {}          # ws -> name

USERS = {"dani": "大倪", "jingjing": "静静", "xiaofang": "小芳", "web": "web"}


def add_history(from_name, msg):
    rec = {"id": uuid.uuid4().hex[:8], "from": from_name, "msg": msg,
           "time": time.strftime("%H:%M:%S")}
    HISTORY.append(rec)
    if len(HISTORY) > HISTORY_MAX:
        del HISTORY[: len(HISTORY) - HISTORY_MAX]
    return rec


async def broadcast(payload, exclude=None):
    """广播给所有连接 (exclude=发送者)"""
    data = json.dumps(payload, ensure_ascii=False)
    dead = []
    for ws, name in CLIENTS.items():
        if ws is exclude:
            continue
        try:
            await ws.send(data)
        except Exception:
            dead.append(ws)
    for ws in dead:
        CLIENTS.pop(ws, None)


async def handle(ws):
    """每连接处理: hello → history, msg → 存+广播"""
    name = "访客"
    try:
        async for raw in ws:
            try:
                data = json.loads(raw)
            except Exception:
                continue
            t = data.get("type")
            if t == "hello":
                name = str(data.get("from", "访客"))[:20]
                CLIENTS[ws] = name
                await ws.send(json.dumps(
                    {"type": "history", "msgs": list(HISTORY)}, ensure_ascii=False))
            elif t == "msg":
                msg = str(data.get("msg", "")).strip()
                if not msg:
                    continue
                rec = add_history(name, msg)
                payload = {"type": "msg", "from": name, "msg": msg,
                           "time": rec["time"], "id": rec["id"]}
                # 广播 (含发送者, 让发送者也能看到自己消息同步)
                await broadcast(payload)
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        CLIENTS.pop(ws, None)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--history", type=int, default=200)
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args()
    global HISTORY_MAX
    HISTORY_MAX = args.history
    # 启动横幅
    print(f"💬 Z-MAX 群聊 WS 服务端 · ws://{args.host}:{args.port}")
    print(f"  历史容量: {HISTORY_MAX} 条 · 在线: {len(CLIENTS)}")
    async with websockets.serve(handle, args.host, args.port):
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    asyncio.run(main())
