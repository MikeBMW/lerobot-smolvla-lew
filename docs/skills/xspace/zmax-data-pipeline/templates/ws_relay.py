#!/usr/bin/env python3
"""Z-MAX WebSocket 状态中转 · ECS :8765
Orin 推理服务 WS 长连接推送心跳 → ECS 广播 → 控制台 WS 订阅实时状态

协议 (JSON):
  Orin→ECS:  {"type":"heartbeat","online":true,"model":"...","infer_count":1,"last_infer_ms":770.3}
  ECS→控制台: {"type":"orin_status","online":true,"model":"...","infer_count":1,"last_infer_ms":770.3,"last_seen":"11:11:33"}

控制台订阅: ws://datadrive.world/ws (nginx 已反代到 :8765)
部署: scp 到 /root/zmax-relay/ws_relay.py → bash /root/zmax-relay/start_ws.sh
"""
import asyncio, json, time
import websockets

ORIN_STATE = {"online": False, "model": None, "last_seen": None, "infer_count": 0,
              "last_infer_ms": None, "uptime": None, "error": None}
clients = set()  # 订阅的控制台客户端


async def broadcast(state):
    """推送状态给所有订阅者"""
    if not clients:
        return
    msg = json.dumps({"type": "orin_status", **state}, ensure_ascii=False)
    dead = []
    for c in list(clients):
        try:
            await c.send(msg)
        except Exception:
            dead.append(c)
    for c in dead:
        clients.discard(c)


async def handler(ws):
    """Orin 推理服务或控制台接入"""
    clients.add(ws)
    try:
        # 新客户端接入: 立即推送当前状态 (控制台打开即有数据)
        await ws.send(json.dumps({"type": "orin_status", **ORIN_STATE}, ensure_ascii=False))
        async for raw in ws:
            try:
                data = json.loads(raw)
            except Exception:
                continue
            if isinstance(data, dict) and data.get("type") == "heartbeat":
                ORIN_STATE.update({
                    "online": data.get("online", True),
                    "model": data.get("model"),
                    "infer_count": data.get("infer_count", ORIN_STATE["infer_count"]),
                    "last_infer_ms": data.get("last_infer_ms"),
                    "uptime": data.get("uptime"),
                    "error": data.get("error"),
                    "last_seen": time.strftime("%H:%M:%S"),
                })
                print(f"💓 WS心跳: {ORIN_STATE['model']} · {ORIN_STATE['infer_count']}次", flush=True)
                await broadcast(ORIN_STATE)
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        clients.discard(ws)


async def main():
    print("🚀 Z-MAX WS 状态中转 @ :8765 (Orin心跳 → 控制台订阅)", flush=True)
    async with websockets.serve(handler, "0.0.0.0", 8765):
        await asyncio.Future()  # 永久运行


if __name__ == "__main__":
    asyncio.run(main())
