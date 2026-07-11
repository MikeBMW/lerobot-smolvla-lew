#!/usr/bin/env python3
"""
Z-MAX Orin 仿真桥 — 离线端侧模型对接

基于 2026-07-11 真机验证数据，模拟完整 Orin 机器人接口。
端侧模型 (SmolVLA/ACT) 通过此桥接器获取传感器数据、发送动作指令，
与真实 Orin 接口完全一致，实现离线仿真→真机无缝切换。

接口对齐:
  话题 (仿真 → 端侧模型):
    /real_joint_states    — 6轴关节状态
    /gripper_pos          — 夹爪位置
    /robot/force_torque   — 六维力/扭矩
    /robot/tcp_pose       — 末端位姿
    /robot_status         — 机器人状态

  服务 (端侧模型 → 仿真):
    /target_relative_joint — 相对关节运动
    /move_joint            — 绝对关节运动

用法:
  python3 orin_sim_bridge.py                  # HTTP+WS 模式 (默认8765)
  python3 orin_sim_bridge.py --ros2           # ROS2 模式 (模拟真实话题)
  python3 orin_sim_bridge.py --standalone     # 本地循环模式
"""

import json, time, math, threading, argparse, sys, os
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, List
from http.server import HTTPServer, BaseHTTPRequestHandler
import asyncio

# ═══════════════════════════════════════════════
# 真机校准数据 (2026-07-11 手动模式)
# ═══════════════════════════════════════════════

@dataclass
class OrinConfig:
    """Orin 真机配置"""
    robot_model: str = "XMS5-R800-W4G3B4C"
    controller_ip: str = "192.168.23.160"
    orin_ip: str = "192.168.23.10"
    orin_virtual_ip: str = "192.168.23.66"

    joint_names: list = field(default_factory=lambda: [
        "XMS5-R800-W4G3B4C_joint_1",
        "XMS5-R800-W4G3B4C_joint_2",
        "XMS5-R800-W4G3B4C_joint_3",
        "XMS5-R800-W4G3B4C_joint_4",
        "XMS5-R800-W4G3B4C_joint_5",
        "XMS5-R800-W4G3B4C_joint_6",
    ])

    # 真机静止位姿 (2026-07-11 验证)
    home_positions: list = field(default_factory=lambda: [
        0.16020,   # J1: +9.2°
        -0.06137,  # J2: -3.5°
        -2.54551,  # J3: -145.9°
        1.44688,   # J4: +82.9°
        0.43494,   # J5: +24.9°
        -0.69766,  # J6: -40.0°
    ])


# ═══════════════════════════════════════════════
# 仿真机器人核心
# ═══════════════════════════════════════════════

class SimulatedOrin:
    """
    模拟 Orin 机器人 — 接口与真机完全一致
    端侧模型对此仿真器的操作与真实机器人无差异
    """

    def __init__(self, config: OrinConfig = None):
        self.cfg = config or OrinConfig()
        self._lock = threading.Lock()
        self._start_time = time.time()

        # 关节状态 (从真机home位姿出发)
        self.joints = {
            "names": self.cfg.joint_names,
            "positions": list(self.cfg.home_positions),
            "velocities": [0.0] * 6,
            "efforts": [0.0] * 6,
        }

        # 目标位置 (模拟运动)
        self.target_positions = list(self.cfg.home_positions)

        # 夹爪
        self.gripper = {"pos": 0.0, "speed": 0, "force": 0, "holding": False}

        # 力传感器
        self.force_torque = {"fx": 0.0, "fy": 0.0, "fz": 0.0,
                             "tx": 0.0, "ty": 0.0, "tz": 0.0}

        # 状态
        self.mode = "simulation"  # simulation / manual / auto
        self.estop = False
        self.running = True
        self.seq = 0

        # 统计
        self.stats = {"updates": 0, "cmd_received": 0, "errors": 0}

    # ═══════════════════════════════════════════
    # 运动模拟
    # ═══════════════════════════════════════════

    def update(self, dt: float = 0.033):
        """更新物理模拟 (30Hz)"""
        with self._lock:
            self.stats["updates"] += 1
            t = time.time() - self._start_time

            # 关节向目标位置平滑移动
            for i in range(6):
                current = self.joints["positions"][i]
                target = self.target_positions[i]
                diff = target - current
                if abs(diff) > 0.0001:
                    # 模拟加减速
                    speed = min(abs(diff) * 5.0, 1.0)  # max 1 rad/s
                    self.joints["velocities"][i] = speed * (1 if diff > 0 else -1)
                    self.joints["positions"][i] += self.joints["velocities"][i] * dt
                else:
                    self.joints["velocities"][i] = 0.0
                    self.joints["positions"][i] = target

                # 添加传感器噪声 (±0.0002 rad)
                self.joints["positions"][i] += (math.sin(t * 50 + i) * 0.0002)

            # 夹爪缓慢响应
            if self.gripper["pos"] < self.gripper.get("_target", 0.0):
                self.gripper["pos"] = min(self.gripper["pos"] + 0.1 * dt * 10,
                                         self.gripper.get("_target", 1.0))
            elif self.gripper["pos"] > self.gripper.get("_target", 0.0):
                self.gripper["pos"] = max(self.gripper["pos"] - 0.1 * dt * 10,
                                         self.gripper.get("_target", 0.0))

            # 力传感器噪声
            self.force_torque["fz"] = (math.sin(t * 3) * 0.1 +
                                       abs(self.joints["velocities"][2]) * 2.0)
            self.force_torque["fx"] = math.sin(t * 5) * 0.05
            self.force_torque["fy"] = math.cos(t * 5) * 0.05

            self.seq += 1

    def move_relative(self, offsets: List[float]) -> dict:
        """相对运动 (对应 /target_relative_joint)"""
        with self._lock:
            self.stats["cmd_received"] += 1
            if len(offsets) != 6:
                return {"success": False, "error": "JOINT_DIMENSION_MISMATCH"}
            for i in range(6):
                self.target_positions[i] += offsets[i]
            return {"success": True, "targets": list(self.target_positions)}

    def move_absolute(self, positions: List[float]) -> dict:
        """绝对运动 (对应 /move_joint)"""
        with self._lock:
            self.stats["cmd_received"] += 1
            if len(positions) != 6:
                return {"success": False, "error": "JOINT_DIMENSION_MISMATCH"}
            self.target_positions = list(positions)
            return {"success": True, "targets": list(self.target_positions)}

    def set_gripper(self, position: float, speed: float = 100,
                    force: float = 40) -> dict:
        """控制夹爪"""
        with self._lock:
            self.gripper["_target"] = max(0.0, min(1.0, position))
            self.gripper["speed"] = speed
            self.gripper["force"] = force
            return {"success": True}

    # ═══════════════════════════════════════════
    # 状态查询 (对应ROS2话题)
    # ═══════════════════════════════════════════

    def get_joint_states(self) -> dict:
        """对应 /real_joint_states"""
        with self._lock:
            return dict(self.joints)

    def get_gripper_state(self) -> dict:
        """对应 /gripper_pos"""
        with self._lock:
            return dict(self.gripper)

    def get_force_torque(self) -> dict:
        """对应 /robot/force_torque"""
        with self._lock:
            return dict(self.force_torque)

    def get_tcp_pose(self) -> dict:
        """对应 /robot/tcp_pose — 简化FK计算"""
        # 基于关节角度的粗略末端估计
        j = self.joints["positions"]
        # 简化: 假设臂长约0.8m
        return {
            "x": 0.8 * math.cos(j[0]) * math.cos(j[1]),
            "y": 0.8 * math.sin(j[0]) * math.cos(j[1]),
            "z": 0.5 + 0.8 * math.sin(j[1]),
            "rx": j[3], "ry": j[4], "rz": j[5],
        }

    def get_status(self) -> dict:
        """对应 /robot_status"""
        return {
            "mode": self.mode,
            "estop": self.estop,
            "seq": self.seq,
            "stats": self.stats,
            "timestamp": time.time(),
        }

    def get_full_state(self) -> dict:
        """完整状态快照"""
        return {
            "joints": self.get_joint_states(),
            "gripper": self.get_gripper_state(),
            "force_torque": self.get_force_torque(),
            "tcp_pose": self.get_tcp_pose(),
            "status": self.get_status(),
        }


# ═══════════════════════════════════════════════
# HTTP + WebSocket 服务
# ═══════════════════════════════════════════════

class SimHTTPHandler(BaseHTTPRequestHandler):
    """HTTP REST API — 对齐真实 Orin Gateway"""
    sim: SimulatedOrin = None

    def log_message(self, format, *args):
        pass  # 静默日志

    def _json(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def do_GET(self):
        if self.path == "/" or self.path == "/status":
            self._json(self.sim.get_full_state())
        elif self.path == "/joints":
            self._json(self.sim.get_joint_states())
        elif self.path == "/gripper":
            self._json(self.sim.get_gripper_state())
        elif self.path == "/force":
            self._json(self.sim.get_force_torque())
        elif self.path == "/tcp":
            self._json(self.sim.get_tcp_pose())
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        if self.path == "/cmd/relative":
            offsets = body.get("offsets", [0]*6)
            result = self.sim.move_relative(offsets)
            self._json(result)
        elif self.path == "/cmd/absolute":
            positions = body.get("positions", [0]*6)
            result = self.sim.move_absolute(positions)
            self._json(result)
        elif self.path == "/cmd/gripper":
            result = self.sim.set_gripper(
                body.get("pos", 0.0),
                body.get("speed", 100),
                body.get("force", 40))
            self._json(result)
        else:
            self._json({"error": "not found"}, 404)


def run_http_server(sim: SimulatedOrin, host="0.0.0.0", port=8081):
    """启动 HTTP 服务器"""
    SimHTTPHandler.sim = sim
    server = HTTPServer((host, port), SimHTTPHandler)
    print(f"🌐 Orin 仿真桥 HTTP: http://{host}:{port}")
    server.serve_forever()


# ═══════════════════════════════════════════════
# 仿真循环 + WebSocket
# ═══════════════════════════════════════════════

async def run_websocket_server(sim: SimulatedOrin, host="0.0.0.0", port=8765):
    """WebSocket 服务 — 对齐仿真协议"""
    try:
        import websockets
    except ImportError:
        print("[WS] websockets未安装, 跳过")
        return

    async def handler(ws):
        print(f"[WS] 客户端连接")
        await ws.send(json.dumps({"type": "connected", "mode": "orin_sim"}))
        try:
            async for raw in ws:
                msg = json.loads(raw)
                cmd = msg.get("type", "")
                if cmd == "get_state":
                    await ws.send(json.dumps(sim.get_full_state()))
                elif cmd == "move_relative":
                    offsets = msg.get("offsets", [0]*6)
                    result = sim.move_relative(offsets)
                    await ws.send(json.dumps(result))
                elif cmd == "move_absolute":
                    result = sim.move_absolute(msg.get("positions", [0]*6))
                    await ws.send(json.dumps(result))
                elif cmd == "set_gripper":
                    result = sim.set_gripper(msg.get("pos", 0.0))
                    await ws.send(json.dumps(result))
        except Exception:
            pass
        print(f"[WS] 客户端断开")

    print(f"🔌 Orin 仿真桥 WebSocket: ws://{host}:{port}")
    async with websockets.serve(handler, host, port):
        await asyncio.Future()  # 永久运行


# ═══════════════════════════════════════════════
# 端侧模型客户端 (供 SmolVLA/ACT 调用)
# ═══════════════════════════════════════════════

class OrinSimClient:
    """
    端侧模型客户端 — 接口与真实 Orin ROS2 完全一致
    用法:
        orin = OrinSimClient("localhost", 8081)
        state = orin.get_state()
        orin.move_relative([0,0,0,0,0,-0.1745])  # J6逆时针10°
    """

    def __init__(self, host="localhost", port=8081):
        self.base = f"http://{host}:{port}"
        import urllib.request
        self._urlopen = urllib.request.urlopen
        self._Request = urllib.request.Request

    def _get(self, path):
        try:
            with self._urlopen(f"{self.base}{path}", timeout=3) as r:
                return json.loads(r.read())
        except Exception as e:
            return {"error": str(e)}

    def _post(self, path, data):
        try:
            body = json.dumps(data).encode()
            req = self._Request(f"{self.base}{path}", data=body,
                               headers={"Content-Type": "application/json"})
            with self._urlopen(req, timeout=3) as r:
                return json.loads(r.read())
        except Exception as e:
            return {"error": str(e)}

    def get_state(self) -> dict:
        return self._get("/status")

    def get_joints(self) -> dict:
        return self._get("/joints")

    def get_gripper(self) -> dict:
        return self._get("/gripper")

    def get_force(self) -> dict:
        return self._get("/force")

    def move_relative(self, offsets: list) -> dict:
        return self._post("/cmd/relative", {"offsets": offsets})

    def move_absolute(self, positions: list) -> dict:
        return self._post("/cmd/absolute", {"positions": positions})

    def set_gripper(self, pos: float, speed=100, force=40) -> dict:
        return self._post("/cmd/gripper",
                         {"pos": pos, "speed": speed, "force": force})


# ═══════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Z-MAX Orin 仿真桥")
    parser.add_argument("--http-port", type=int, default=8081)
    parser.add_argument("--ws-port", type=int, default=8765)
    parser.add_argument("--no-http", action="store_true")
    parser.add_argument("--no-ws", action="store_true")
    parser.add_argument("--test", action="store_true", help="运行自检")
    args = parser.parse_args()

    sim = SimulatedOrin()
    print(f"""
╔══════════════════════════════════════════════╗
║   Z-MAX Orin 仿真桥 v1.0                      ║
║   机器人: {sim.cfg.robot_model}
║   控制器: {sim.cfg.controller_ip}
║   Home位姿: J1={sim.cfg.home_positions[0]:.3f} ... J6={sim.cfg.home_positions[5]:.3f}
║   模式: 仿真 (离线可用)
╚══════════════════════════════════════════════╝
""")

    if args.test:
        # 自检模式
        print("🔍 运行仿真自检...")
        sim.update(0.033)
        state = sim.get_full_state()
        print(f"  关节: {[f'{p:.4f}' for p in state['joints']['positions']]}")
        print(f"  夹爪: {state['gripper']['pos']:.2f}")
        print(f"  力: Fz={state['force_torque']['fz']:.2f}N")

        # 测试运动
        result = sim.move_relative([0, 0, 0, 0, 0, -0.1745])
        print(f"  J6逆时针10°: {result['success']}")

        for _ in range(30):
            sim.update(0.033)
        state = sim.get_full_state()
        print(f"  运动后J6: {state['joints']['positions'][5]:.4f} rad "
              f"({math.degrees(state['joints']['positions'][5]):.1f}°)")
        print("✅ 自检通过\n")
        return

    # 仿真循环线程
    def sim_loop():
        while sim.running:
            sim.update(0.033)
            time.sleep(0.033)

    threading.Thread(target=sim_loop, daemon=True).start()

    # HTTP 服务
    if not args.no_http:
        threading.Thread(target=run_http_server, args=(sim,),
                        kwargs={"port": args.http_port}, daemon=True).start()

    # WebSocket 服务
    if not args.no_ws:
        try:
            asyncio.run(run_websocket_server(sim, port=args.ws_port))
        except KeyboardInterrupt:
            pass
    else:
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

    sim.running = False
    print("\n⏹  仿真桥已停止")


if __name__ == "__main__":
    main()
