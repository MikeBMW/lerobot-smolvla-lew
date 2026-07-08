#!/usr/bin/env python3
"""
Hermes Gateway — 纯Python版 (不需要ROS2!)

通过SSH订阅Orin话题，通过HTTP API暴露给Hermes本体

启动:
    python3 gateway_pure.py --orin-host 192.168.23.10
"""

import json
import time
import threading
import subprocess
import argparse
import os
from typing import Optional


class HermesGatewayPure:
    """纯Python Gateway — SSH轮询Orin ROS2话题"""

    def __init__(self, orin_host: str = "192.168.23.10",
                 orin_user: str = "nvidia",
                 poll_interval: float = 0.1):
        self.orin_host = orin_host
        self.orin_user = orin_user
        self.poll_interval = poll_interval
        self._running = False
        self._lock = threading.Lock()

        # 状态缓存
        self.state = {
            "joint_names": [],
            "joint_positions": [],
            "gripper_pos": None,
            "sim_joints": None,
            "last_update": 0.0,
            "error": None,
        }

    def _ssh(self, cmd: str, timeout: int = 5) -> str:
        """执行SSH命令（通过expect wrapper处理密码）"""
        wrapper = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ssh_wrapper.exp")
        full_cmd = [wrapper, self.orin_host, cmd]
        try:
            r = subprocess.run(full_cmd, capture_output=True, text=True, timeout=timeout)
            # Parse expect output: remove spawn line and password prompt, keep actual result
            out = r.stdout.strip()
            # Remove spawn line and password prompt lines
            lines = []
            skip = True
            for line in out.split("\n"):
                if skip and ("password:" in line):
                    skip = False
                    continue
                if skip:
                    continue
                lines.append(line)
            return "\n".join(lines).strip()
        except Exception as e:
            return ""

    def _poll_orin(self):
        """轮询Orin数据"""
        while self._running:
            try:
                # 关节状态
                joint_raw = self._ssh(
                    "ros2 topic echo --once /real_joint_states 2>/dev/null", timeout=10
                )
                if joint_raw:
                    self._parse_joint_states(joint_raw)

                # 夹爪
                grip_raw = self._ssh(
                    "ros2 topic echo --once /gripper_pos 2>/dev/null", timeout=8
                )
                if grip_raw:
                    try:
                        with self._lock:
                            self.state["gripper_pos"] = float(grip_raw.split()[-1])
                            self.state["last_update"] = time.time()
                    except ValueError:
                        pass

            except Exception as e:
                with self._lock:
                    self.state["error"] = str(e)

            time.sleep(self.poll_interval)

    def _parse_joint_states(self, raw: str):
        """解析ros2 topic echo YAML格式输出的joint_states"""
        names = []
        positions = []
        mode = None  # 'names' or 'positions'

        for line in raw.split("\n"):
            line = line.strip()
            if not line:
                continue
            if line.startswith("name:"):
                mode = "names"
                continue
            elif line.startswith("position:"):
                mode = "positions"
                continue
            elif line.startswith("velocity:") or line.startswith("effort:"):
                mode = None
                continue
            if mode == "names" and line.startswith("- "):
                names.append(line[2:].strip())
            elif mode == "positions" and line.startswith("- "):
                try:
                    positions.append(float(line[1:].strip()))
                except ValueError:
                    pass

        if names and positions and len(names) == len(positions):
            with self._lock:
                self.state["joint_names"] = names
                self.state["joint_positions"] = positions
                self.state["last_update"] = time.time()

    def start(self):
        """启动后台轮询"""
        self._running = True
        t = threading.Thread(target=self._poll_orin, daemon=True)
        t.start()
        print(f"🔍 开始轮询 Orin @ {self.orin_user}@{self.orin_host}")
        return t

    def stop(self):
        self._running = False

    def get_state(self) -> dict:
        with self._lock:
            return dict(self.state)

    def get_joints(self) -> dict:
        with self._lock:
            if self.state["joint_names"] and self.state["joint_positions"]:
                return dict(zip(self.state["joint_names"], self.state["joint_positions"]))
            return {}

    def get_gripper(self) -> float | None:
        with self._lock:
            return self.state["gripper_pos"]

    def send_cmd(self, command: str) -> dict:
        """通过SSH发送ROS2指令到Orin"""
        if "回零" in command or "home" in command.lower():
            cmd = 'ros2 service call /robot_stop std_srvs/srv/Trigger 2>/dev/null'
        elif "开" in command or "open" in command.lower():
            cmd = 'ros2 topic pub /gripper_cmd std_msgs/msg/Float64 "data: 200.0" --once 2>/dev/null'
        elif "关" in command or "close" in command.lower():
            cmd = 'ros2 topic pub /gripper_cmd std_msgs/msg/Float64 "data: 0.0" --once 2>/dev/null'
        else:
            cmd = f'ros2 topic pub /hermes_cmd std_msgs/msg/String "data: {command}" --once 2>/dev/null'

        result = self._ssh(cmd)
        return {"command": command, "result": result[:200] if result else "ok"}

    def list_topics(self) -> list:
        """列出Orin上所有ROS2话题"""
        raw = self._ssh("ros2 topic list 2>/dev/null", timeout=5)
        return [t for t in raw.split("\n") if t and not t.startswith("/parameter")]


# ── HTTP API 服务器 ──
def run_api_server(gateway: HermesGatewayPure, host: str = "0.0.0.0", port: int = 8080):
    """启动FastAPI HTTP服务"""
    import asyncio
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.responses import JSONResponse
    import uvicorn

    app = FastAPI(title="Hermes Gateway Pure")
    ws_clients = []

    @app.get("/")
    async def root():
        return {"service": "Hermes Gateway (Pure)", "orin": gateway.orin_host, "status": "online"}

    @app.get("/status")
    async def status():
        return gateway.get_state()

    @app.get("/joints")
    async def joints():
        j = gateway.get_joints()
        return {"joints": j, "count": len(j)} if j else {"joints": {}, "note": "Waiting for data..."}

    @app.get("/gripper")
    async def gripper():
        return {"gripper_pos": gateway.get_gripper()}

    @app.get("/topics")
    async def topics():
        return {"topics": gateway.list_topics()}

    @app.post("/cmd")
    async def cmd(data: dict):
        command = data.get("command", "")
        if not command:
            return JSONResponse({"error": "command required"}, status_code=400)
        return gateway.send_cmd(command)

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        ws_clients.append(ws)
        await ws.send_json({"type": "connected"})
        try:
            while True:
                await asyncio.sleep(1.0)
                try:
                    await ws.send_json({
                        "type": "state",
                        "joints": gateway.get_joints(),
                        "gripper": gateway.get_gripper(),
                        "ts": gateway.state.get("last_update", 0),
                    })
                except Exception:
                    break
        except WebSocketDisconnect:
            pass
        finally:
            if ws in ws_clients:
                ws_clients.remove(ws)

    print(f"\n{'='*50}")
    print(f"🌐 Hermes Gateway API @ http://{host}:{port}")
    print(f"   GET  http://{host}:{port}/status")
    print(f"   GET  http://{host}:{port}/joints")
    print(f"   POST http://{host}:{port}/cmd")
    print(f"   WS   ws://{host}:{port}/ws")
    print(f"{'='*50}\n")

    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Hermes Gateway (Pure)")
    parser.add_argument("--orin-host", default=None, help="Orin IP (可选,暂不连接)")
    parser.add_argument("--orin-user", default="nvidia", help="Orin SSH user")
    parser.add_argument("--port", type=int, default=8080, help="API port")
    args = parser.parse_args()

    print(f"🟢 Hermes Gateway (Pure Python)")
    gw = HermesGatewayPure(orin_host=args.orin_host or "none", orin_user=args.orin_user)

    if args.orin_host:
        print(f"   Orin: {args.orin_user}@{args.orin_host}")
        gw.start()
    else:
        print(f"   Orin: 暂不连接 (加 --orin-host 192.168.23.10 连接)")
        print(f"   API 服务正常启动，Orin接入后自动获取数据")

    try:
        run_api_server(gw, port=args.port)
    except KeyboardInterrupt:
        gw.stop()
        print("\n👋 Bye!")
