#!/usr/bin/env python3
"""
Z-MAX 仿真服务器 (Server) — 运行在 WSL2 端 (供 xspace/静静 使用)

角色: 接收仿真传感器数据 → SmolVLA推理 → 返回动作指令
通信: WebSocket JSON ← Mac仿真客户端

用法:
    # 启动服务器
    python3 simulation_server.py
    
    # 指定模型和端口
    python3 simulation_server.py --policy lerobot/smolvla_base --port 8765
    
    # 使用本地训练的模型
    python3 simulation_server.py --policy ./outputs/train/smolvla_lew_mini

架构:
    Mac (小芳)                          WSL2 (xspace/静静)
    ┌────────────────────┐            ┌────────────────────┐
    │ simulation_client   │  WebSocket│ simulation_server   │
    │                     │◄─────────►│ ┌────────────────┐  │
    │ sensor_data ────────│──────────►│ │ PolicyInference │  │
    │                     │           │ │  SmolVLA/ACT    │  │
    │ ◄──────── action ───│◄──────────│ │  ActionPredict  │  │
    │                     │           │ └────────────────┘  │
    └────────────────────┘            └────────────────────┘

依赖:
    pip install websockets torch
    (需要lerobot环境用于SmolVLA推理)
"""

import asyncio
import json
import time
import argparse
import signal
import sys
import os
from dataclasses import asdict
from typing import Optional, Set

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from simulation_protocol import (
    MessageType, Action, Heartbeat, SimConfig,
    encode_message, decode_message, build_action,
)

try:
    import websockets
    from websockets.server import serve, WebSocketServerProtocol
except ImportError:
    websockets = None


# ═══════════════════════════════════════════════
# 推理引擎 (占位 — xspace需替换为实际SmolVLA推理)
# ═══════════════════════════════════════════════

class InferenceEngine:
    """
    SmolVLA 推理引擎
    
    注意: 此为占位实现。xspace需要集成实际的 lerobot 推理代码。
    参考: ~/lerobot-smolvla-lew/hermes_gateway_mac/infer_realtime.py
    """
    
    def __init__(self, policy_path: str = "lerobot/smolvla_base", device: str = "cuda"):
        self.policy_path = policy_path
        self.device = device
        self.model = None
        self.is_loaded = False
        self.inference_count = 0
        self.total_inference_time = 0.0
    
    def load(self) -> bool:
        """加载模型"""
        print(f"[Server] 🔄 加载模型: {self.policy_path} (device={self.device})")
        
        try:
            # === xspace: 在此处集成实际推理代码 ===
            # from lerobot.policies.smolvla.configuration import SmolVLAPolicyConfig
            # from lerobot.policies.smolvla.modeling import SmolVLAPolicy
            # ... 加载模型 ...
            
            # 占位: 模拟加载
            time.sleep(0.5)
            self.is_loaded = True
            print(f"[Server] ✅ 模型加载成功 (模拟)")
            
        except Exception as e:
            print(f"[Server] ⚠️  模型加载失败: {e}")
            print("[Server] 使用零动作占位模式")
            self.is_loaded = True  # 占位模式仍然可用
        
        return self.is_loaded
    
    def infer(self, sensor_data: dict) -> tuple:
        """
        执行推理
        
        Args:
            sensor_data: 传感器数据字典 (来自 simulation_protocol.SensorData)
        
        Returns:
            (joint_positions, gripper_cmd, inference_time_ms)
        """
        start = time.time()
        
        try:
            # === xspace: 在此处集成实际推理代码 ===
            # 输入: sensor_data["camera"], sensor_data["joint_state"], sensor_data["force_torque"]
            # 输出: 6D关节位置 + 夹爪开度
            
            # 占位: 返回当前关节位置 (零动作)
            joint_state = sensor_data.get("joint_state", {})
            positions = joint_state.get("positions", [0.0] * 6)
            
            # 微小的正弦扰动模拟推理输出
            t = time.time()
            positions = [p + 0.001 * (2 * (i % 2) - 1) * __import__('math').sin(t * 2 + i)
                        for i, p in enumerate(positions)]
            
            gripper_cmd = 0.5
            
            inference_time = (time.time() - start) * 1000
            self.inference_count += 1
            self.total_inference_time += inference_time
            
            return positions, gripper_cmd, inference_time
            
        except Exception as e:
            print(f"[Server] ⚠️  推理失败: {e}")
            return [0.0] * 6, 0.0, 0.0


# ═══════════════════════════════════════════════
# 仿真服务器
# ═══════════════════════════════════════════════

class SimulationServer:
    """Z-MAX 仿真服务器 — 接收传感器, 推理, 返回动作"""
    
    def __init__(self, policy_path="lerobot/smolvla_base", 
                 host="0.0.0.0", port=8765, device="cuda"):
        self.host = host
        self.port = port
        self.device = device
        
        # 推理引擎
        self.engine = InferenceEngine(policy_path, device)
        
        # 客户端管理
        self.clients: Set[WebSocketServerProtocol] = set()
        self.client_count = 0
        
        # 统计
        self.stats = {
            "connections": 0,
            "sensor_packets": 0,
            "actions_sent": 0,
            "errors": 0,
            "start_time": time.time(),
            "last_packet_time": 0.0,
        }
        
        # 配置
        self.config = SimConfig(
            policy_path=policy_path,
            inference_device=device,
        )
        
        self.seq = 0
        self.running = False
    
    async def handle_client(self, ws: WebSocketServerProtocol):
        """处理客户端连接"""
        client_id = self.client_count
        self.client_count += 1
        self.clients.add(ws)
        self.stats["connections"] += 1
        
        addr = ws.remote_address if hasattr(ws, 'remote_address') else f"client_{client_id}"
        print(f"[Server] 🔗 客户端连接: {addr} (ID={client_id})")
        
        # 发送就绪信号
        await ws.send(json.dumps({
            "msg_type": MessageType.READY,
            "server_version": "1.0.0",
            "model": self.engine.policy_path,
            "device": self.device,
            "model_loaded": self.engine.is_loaded,
        }))
        
        # 发送配置
        await ws.send(encode_message(self.config))
        
        try:
            async for raw in ws:
                try:
                    msg = decode_message(raw)
                    response = await self.process_message(ws, msg, client_id)
                    if response:
                        await ws.send(json.dumps(response, ensure_ascii=False))
                        
                except json.JSONDecodeError:
                    print(f"[Server] ⚠️  无效JSON来自 {addr}")
                    self.stats["errors"] += 1
                    
        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as e:
            print(f"[Server] ⚠️  客户端异常 {addr}: {e}")
        finally:
            self.clients.discard(ws)
            print(f"[Server] 🔌 客户端断开: {addr} (活跃: {len(self.clients)})")
    
    async def process_message(self, ws, msg: dict, client_id: int) -> Optional[dict]:
        """处理消息"""
        msg_type = msg.get("msg_type", "")
        
        if msg_type == MessageType.SENSOR_DATA:
            self.stats["sensor_packets"] += 1
            self.stats["last_packet_time"] = time.time()
            
            # 执行推理
            positions, gripper_cmd, inference_ms = self.engine.infer(msg)
            
            self.seq += 1
            action = build_action(self.seq, positions, gripper_cmd, inference_ms)
            self.stats["actions_sent"] += 1
            
            # 返回动作 (或广播给所有客户端)
            return asdict(action) if hasattr(action, '__dataclass_fields__') else action
        
        elif msg_type == MessageType.HEARTBEAT:
            return {
                "msg_type": MessageType.HEARTBEAT,
                "seq": self.seq,
                "timestamp": time.time(),
                "source": "server",
            }
        
        elif msg_type == MessageType.STATUS:
            print(f"[Server] 📊 客户端{client_id} 状态: {msg}")
        
        return None
    
    def print_status(self):
        """打印状态"""
        elapsed = time.time() - self.stats["start_time"]
        rate = self.stats["sensor_packets"] / elapsed if elapsed > 0 else 0
        avg_inference = (self.engine.total_inference_time / self.engine.inference_count
                        if self.engine.inference_count > 0 else 0)
        
        print(f"\r[Server] 🔵 客户端: {len(self.clients)} "
              f"| 传感器包: {self.stats['sensor_packets']} "
              f"| 动作: {self.stats['actions_sent']} "
              f"| 频率: {rate:.1f} Hz "
              f"| 推理: {avg_inference:.1f}ms "
              f"  ", end="", flush=True)
    
    async def run(self):
        """启动服务器"""
        # 加载模型
        self.engine.load()
        
        print(f"""
╔══════════════════════════════════════════════╗
║   Z-MAX 仿真服务器 v1.0                       ║
║   模型: {self.engine.policy_path}
║   设备: {self.device}
║   监听: ws://{self.host}:{self.port}
║   等待 Mac 仿真客户端连接...
╚══════════════════════════════════════════════╝
""")
        
        self.running = True
        
        try:
            async with serve(self.handle_client, self.host, self.port):
                # 定期打印状态
                while self.running:
                    self.print_status()
                    await asyncio.sleep(2.0)
                    
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"\n[Server] ❌ 服务器异常: {e}")
        finally:
            self.running = False
        
        # 打印统计
        elapsed = time.time() - self.stats["start_time"]
        avg_inference = (self.engine.total_inference_time / self.engine.inference_count
                        if self.engine.inference_count > 0 else 0)
        print(f"""
┌──────────────────────────────────────────────┐
│          仿真服务器 — 运行统计                 │
├──────────────────────────────────────────────┤
│  运行时间:     {elapsed:.1f}s
│  客户端连接:   {self.stats['connections']}
│  传感器包:     {self.stats['sensor_packets']} 包
│  发送动作:     {self.stats['actions_sent']} 条
│  平均推理:     {avg_inference:.1f}ms
│  模型:         {self.engine.policy_path}
│  设备:         {self.device}
└──────────────────────────────────────────────┘
""")


def main():
    parser = argparse.ArgumentParser(description="Z-MAX 仿真服务器")
    parser.add_argument("--policy", default="lerobot/smolvla_base", help="模型路径")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址")
    parser.add_argument("--port", type=int, default=8765, help="监听端口")
    parser.add_argument("--device", default="cuda", help="推理设备 (cuda/cpu)")
    args = parser.parse_args()
    
    server = SimulationServer(
        policy_path=args.policy,
        host=args.host,
        port=args.port,
        device=args.device,
    )
    
    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        print("\n[Server] ⏹  用户中断")


if __name__ == "__main__":
    main()
