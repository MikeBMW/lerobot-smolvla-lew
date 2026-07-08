#!/usr/bin/env python3
"""
Hermes Gateway — HTTP API 服务 (Mac M1)

提供REST API让Hermes本体(WSL)远程查询和操控ROS2

端点:
    GET  /status            → 完整状态快照
    GET  /joints            → 关节位置字典
    GET  /gripper           → 夹爪开度
    GET  /topics            → 所有订阅话题列表
    POST /cmd               → 发送HMI指令 (body: {"command": "..."})
    POST /target_pose       → 发送目标位姿
    WS   /ws                → WebSocket实时推送

启动:
    python3 api_server.py
"""

import json
import time
import asyncio
import threading
from typing import Optional

# ── 注意: FastAPI在Mac上安装 ──
# pip install fastapi uvicorn websockets
try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.responses import JSONResponse
    import uvicorn
except ImportError:
    print("请先安装: pip install fastapi uvicorn websockets")
    raise


app = FastAPI(title="Hermes Gateway API", version="1.0.0")

# ── 全局状态 ──
_gateway_node: Optional[object] = None
_ws_clients: list[WebSocket] = []


def set_gateway_node(node):
    """由gateway_node.py注入ROS2节点引用"""
    global _gateway_node
    _gateway_node = node


# ── REST API ──

@app.get("/")
async def root():
    return {"service": "Hermes Gateway", "status": "online", "version": "1.0.0"}


@app.get("/status")
async def get_status():
    """完整状态快照"""
    if _gateway_node is None:
        return JSONResponse({"error": "Gateway not ready"}, status_code=503)
    return _gateway_node.get_state()


@app.get("/joints")
async def get_joints():
    """关节位置字典"""
    if _gateway_node is None:
        return JSONResponse({"error": "Gateway not ready"}, status_code=503)
    joints = _gateway_node.get_joint_positions()
    if joints is None:
        return {"joints": {}, "note": "暂无数据，等待Orin推送..."}
    return {"joints": joints}


@app.get("/gripper")
async def get_gripper():
    """夹爪开度"""
    if _gateway_node is None:
        return JSONResponse({"error": "Gateway not ready"}, status_code=503)
    pos = _gateway_node.get_gripper()
    return {"gripper_pos": pos}


@app.get("/topics")
async def get_topics():
    """所有话题状态"""
    return {
        "subscriptions": [
            "/real_joint_states (JointState)",
            "/gripper_pos (Float64)",
            "/hmi/events (String)",
        ],
        "publishers": [
            "/hermes_cmd (String)",
            "/hermes_target_pose (JointState)",
        ],
    }


@app.post("/cmd")
async def send_command(data: dict):
    """发送HMI指令

    Body: {"command": "回零"} 或 {"command": "home"}
    """
    if _gateway_node is None:
        return JSONResponse({"error": "Gateway not ready"}, status_code=503)

    cmd = data.get("command", "")
    if not cmd:
        return JSONResponse({"error": "command字段不能为空"}, status_code=400)

    _gateway_node.publish_cmd(cmd)

    # 推送到WebSocket客户端
    msg = {"type": "cmd", "command": cmd, "timestamp": time.time()}
    _broadcast_ws(msg)

    return {"status": "ok", "command": cmd}


@app.post("/target_pose")
async def send_target_pose(data: dict):
    """发送目标关节位姿

    Body: {"names": ["joint1","joint2"], "positions": [0.5, -0.3]}
    """
    if _gateway_node is None:
        return JSONResponse({"error": "Gateway not ready"}, status_code=503)

    names = data.get("names", [])
    positions = data.get("positions", [])
    if len(names) != len(positions):
        return JSONResponse({"error": "names和positions长度不一致"}, status_code=400)

    _gateway_node.publish_target_pose(names, positions)
    return {"status": "ok", "joints": dict(zip(names, positions))}


# ── WebSocket实时推送 ──

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    _ws_clients.append(ws)
    try:
        await ws.send_json({"type": "connected", "msg": "Hermes Gateway WebSocket"})
        while True:
            # 每秒推送状态
            await asyncio.sleep(1.0)
            if _gateway_node:
                state = _gateway_node.get_state()
                # 精简推送
                slim = {
                    "type": "state",
                    "joints": state.get("joint_states"),
                    "gripper": state.get("gripper_pos"),
                    "ts": state.get("last_update"),
                }
                try:
                    await ws.send_json(slim)
                except Exception:
                    break
    except WebSocketDisconnect:
        pass
    finally:
        if ws in _ws_clients:
            _ws_clients.remove(ws)


def _broadcast_ws(msg: dict):
    """广播消息到所有WebSocket客户端"""
    dead = []
    for ws in _ws_clients:
        try:
            asyncio.create_task(ws.send_json(msg))
        except Exception:
            dead.append(ws)
    for d in dead:
        if d in _ws_clients:
            _ws_clients.remove(d)


def start_api(host: str = "0.0.0.0", port: int = 8080):
    """启动HTTP API服务"""
    print(f"\n🌐 Hermes Gateway API @ http://{host}:{port}")
    print(f"   GET  http://{host}:{port}/status")
    print(f"   GET  http://{host}:{port}/joints")
    print(f"   POST http://{host}:{port}/cmd")
    print(f"   WS   ws://{host}:{port}/ws")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    start_api()
