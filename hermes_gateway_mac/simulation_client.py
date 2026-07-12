#!/usr/bin/env python3
"""
Z-MAX 仿真客户端 (Client) — 运行在 Mac M1 端

角色: ROS2仿真节点替代品 — 发布传感器数据, 接收动作指令
通信: WebSocket JSON → WSL2仿真服务器

用法:
    # 启动客户端 (默认连接 localhost:8765)
    python3 simulation_client.py
    
    # 连接远程服务器
    python3 simulation_client.py --host 192.168.23.1 --port 8765
    
    # 离线纯仿真模式 (无Server, 数据本地回放)
    python3 simulation_client.py --standalone

架构:
    Mac (小芳)                          WSL2 (xspace/静静)
    ┌────────────────────┐            ┌────────────────────┐
    │ simulation_client   │  WebSocket│ simulation_server   │
    │ ┌────────────────┐  │◄─────────►│ ┌────────────────┐  │
    │ │ CameraSim      │──│sensor_data│ │ SmolVLA Model  │  │
    │ │ ForceTorqueSim │──│──────────►│ │ Inference       │  │
    │ │ JointSim       │──│           │ │ ActionPredict   │  │
    │ │ GripperSim     │──│  action   │ │                 │  │
    │ │ TactileSim     │◄─│◄──────────│ │                 │  │
    │ └────────────────┘  │           │ └────────────────┘  │
    └────────────────────┘            └────────────────────┘
"""

import asyncio
import json
import time
import math
import argparse
import signal
import sys
import os
from dataclasses import asdict
from typing import Optional

# 设置路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from simulation_protocol import (
    JointState, ForceTorque, TactileData, CameraFrame, GripperState,
    SensorData, Action, Heartbeat, SimConfig, MessageType,
    build_sensor_data, encode_message, decode_message, TOPICS
)

try:
    import websockets
except ImportError:
    websockets = None


# ═══════════════════════════════════════════════
# 仿真传感器
# ═══════════════════════════════════════════════

class JointSimulator:
    """6轴关节仿真 — 正弦波运动 + 抖动"""
    
    def __init__(self):
        self.names = [
            "XMS5-R800-W4G3B4C_joint_1",
            "XMS5-R800-W4G3B4C_joint_2", 
            "XMS5-R800-W4G3B4C_joint_3",
            "XMS5-R800-W4G3B4C_joint_4",
            "XMS5-R800-W4G3B4C_joint_5",
            "XMS5-R800-W4G3B4C_joint_6",
        ]
        # 初始位姿 (来自 Orin 真实快照)
        self.base_positions = [0.160, -0.061, -2.545, 1.447, 0.435, -0.698]
        self.amplitudes = [0.02, 0.015, 0.01, 0.02, 0.03, 0.025]
        self.frequencies = [0.5, 0.3, 0.2, 0.4, 0.6, 0.35]
        self._start_time = time.time()
        self.seq = 0
    
    def read(self) -> JointState:
        t = time.time() - self._start_time
        self.seq += 1
        positions = []
        for i in range(6):
            noise = math.sin(t * 7.3 + i) * 0.001  # 传感器噪声
            pos = self.base_positions[i] + \
                  self.amplitudes[i] * math.sin(2 * math.pi * self.frequencies[i] * t) + \
                  noise
            positions.append(round(pos, 6))
        
        return JointState(
            names=self.names,
            positions=positions,
            velocities=[round(a * 2 * math.pi * f * math.cos(2 * math.pi * f * t), 6)
                       for a, f in zip(self.amplitudes, self.frequencies)],
        )


class ForceTorqueSimulator:
    """六维力传感器仿真 — 模拟插拔过程中的力变化"""
    
    def __init__(self):
        self._start_time = time.time()
        self._cycle_duration = 15.0  # 15秒一个插拔周期
        self.seq = 0
    
    def read(self) -> ForceTorque:
        self.seq += 1
        t = time.time() - self._start_time
        cycle = (t % self._cycle_duration) / self._cycle_duration
        
        # 模拟插拔过程: 接近→接触→插入→稳定
        if cycle < 0.3:
            # 接近阶段: 无力
            fx = fy = fz = 0.0
        elif cycle < 0.5:
            # 接触阶段: 力逐渐增大
            ratio = (cycle - 0.3) / 0.2
            fx, fy = ratio * 2.0, ratio * 1.5
            fz = ratio * 4.0
        elif cycle < 0.7:
            # 插入阶段: 力达到峰值
            fx, fy = 2.0 + (cycle - 0.5) * 3.0, 1.5 + (cycle - 0.5) * 2.0
            fz = 4.0 + (cycle - 0.5) * 5.0
        else:
            # 稳定阶段: 保持稳定力
            fx, fy, fz = 2.5, 2.0, 6.0
        
        # 添加高频噪声 (模拟1kHz传感器)
        noise_scale = 0.05
        return ForceTorque(
            fx=round(fx + (math.sin(t * 500) * noise_scale), 4),
            fy=round(fy + (math.cos(t * 500) * noise_scale), 4),
            fz=round(fz + (math.sin(t * 600) * noise_scale), 4),
            tx=round(math.sin(t * 3) * 0.1, 4),
            ty=round(math.cos(t * 4) * 0.08, 4),
            tz=round(math.sin(t * 5) * 0.05, 4),
            timestamp=time.time(),
        )


class CameraSimulator:
    """相机仿真 — 生成模拟图像帧"""
    
    def __init__(self, width=640, height=480):
        self.width = width
        self.height = height
        self._start_time = time.time()
        self.seq = 0
    
    def read(self) -> CameraFrame:
        self.seq += 1
        t = time.time() - self._start_time
        
        # 生成简单的模拟图像: 纯色渐变 + 帧号
        # 实际传输中可以用base64编码的占位图
        frame_id = self.seq % 256
        # 占位: 1像素的RGB (实际应用中替换为真实图像)
        placeholder = f"SIM_FRAME_{self.seq:06d}"
        
        return CameraFrame(
            source="realsense_d435",
            width=self.width,
            height=self.height,
            data_b64=placeholder,
            depth_data_b64=f"DEPTH_{self.seq:06d}",
            timestamp=t,
        )


class GripperSimulator:
    """夹爪仿真 — 模拟开合动作"""
    
    def __init__(self):
        self._start_time = time.time()
        self.position = 0.0
        self.seq = 0
    
    def read(self, target_position: Optional[float] = None) -> GripperState:
        self.seq += 1
        t = time.time() - self._start_time
        
        if target_position is not None:
            # 平滑移动到目标位置
            self.position += (target_position - self.position) * 0.3
        
        # 默认: 周期性开合
        if target_position is None:
            self.position = 0.5 + 0.5 * math.sin(t * 0.5)
        
        return GripperState(
            position=round(self.position, 4),
            velocity=round(0.1 * math.cos(t * 0.5), 4),
            effort=round(abs(self.position - 0.5) * 10, 2),
            is_holding=self.position < 0.3,
            timestamp=t,
        )


class TactileSimulator:
    """触觉传感器仿真 — 4×4压力阵列"""
    
    def __init__(self):
        self._start_time = time.time()
        self.seq = 0
    
    def read(self, force_z: float = 0.0) -> TactileData:
        self.seq += 1
        t = time.time() - self._start_time
        
        # 根据Z向力生成压力分布
        pressure = min(force_z / 10.0, 1.0)  # 归一化到[0,1]
        grid = []
        for i in range(4):
            row = []
            for j in range(4):
                # 中心压力大，边缘小
                dist = math.sqrt((i - 1.5)**2 + (j - 1.5)**2) / 2.5
                value = pressure * max(0, 1 - dist) + (math.sin(t * 10 + i + j) * 0.01)
                row.append(round(value, 4))
            grid.append(row)
        
        return TactileData(
            sensor_id="tactile_array_01",
            pressure_grid=grid,
            contact_detected=pressure > 0.1,
            contact_force=round(force_z, 4),
            timestamp=t,
        )


# ═══════════════════════════════════════════════
# 仿真客户端主类
# ═══════════════════════════════════════════════

class SimulationClient:
    """Z-MAX 仿真客户端 — 发布传感器数据, 接收动作指令"""
    
    def __init__(self, server_host="localhost", server_port=8765, standalone=False):
        self.server_uri = f"ws://{server_host}:{server_port}"
        self.standalone = standalone
        self.running = False
        self.ws = None
        
        # 仿真传感器
        self.joint_sim = JointSimulator()
        self.ft_sim = ForceTorqueSimulator()
        self.camera_sim = CameraSimulator()
        self.gripper_sim = GripperSimulator()
        self.tactile_sim = TactileSimulator()
        
        # 状态
        self.seq = 0
        self.last_action: Optional[Action] = None
        self.stats = {
            "sensor_packets_sent": 0,
            "actions_received": 0,
            "start_time": time.time(),
            "last_sensor_time": 0.0,
            "last_action_time": 0.0,
        }
        
        # 发布频率
        self.sensor_rate_hz = 30  # 传感器发布频率
        self.heartbeat_interval = 5.0  # 心跳间隔
    
    async def connect(self):
        """连接仿真服务器"""
        if self.standalone:
            print("[Client] 独立仿真模式 (无Server连接)")
            return
        
        if websockets is None:
            print("[Client] ERROR: websockets not installed. Run: pip install websockets")
            print("[Client] Falling back to standalone mode")
            self.standalone = True
            return
        
        try:
            self.ws = await websockets.connect(self.server_uri)
            print(f"[Client] ✅ 已连接到仿真服务器: {self.server_uri}")
            
            # 发送初始状态
            status = {
                "type": MessageType.STATUS,
                "client_version": "1.0.0",
                "robot_model": "XMS5-R800-W4G3B4C",
                "sensors": ["joints", "force_torque", "camera", "gripper", "tactile"],
                "publish_rate_hz": self.sensor_rate_hz,
            }
            await self.ws.send(json.dumps(status))
            
        except Exception as e:
            print(f"[Client] ⚠️  无法连接服务器: {e}")
            print("[Client] 切换到独立仿真模式")
            self.standalone = True
    
    async def publish_sensors(self):
        """发布传感器数据"""
        self.seq += 1
        
        # 读取所有传感器
        joint_state = self.joint_sim.read()
        force_torque = self.ft_sim.read()
        camera = self.camera_sim.read()
        gripper = self.gripper_sim.read()
        tactile = self.tactile_sim.read(force_z=force_torque.fz)
        
        # 构建数据包
        sensor_data = build_sensor_data(
            self.seq, joint_state, force_torque, tactile, camera, gripper
        )
        
        self.stats["sensor_packets_sent"] += 1
        self.stats["last_sensor_time"] = time.time()
        
        if not self.standalone and self.ws:
            try:
                await self.ws.send(encode_message(sensor_data))
            except Exception as e:
                print(f"[Client] ⚠️  发送失败: {e}")
        
        return sensor_data
    
    async def receive_actions(self):
        """接收动作指令"""
        if self.standalone or not self.ws:
            return None
        
        try:
            raw = await asyncio.wait_for(self.ws.recv(), timeout=0.01)
            msg = decode_message(raw if isinstance(raw, str) else raw.decode())
            
            if msg.get("msg_type") == MessageType.ACTION:
                self.last_action = Action(**{k: v for k, v in msg.items() if k in Action.__dataclass_fields__})
                self.stats["actions_received"] += 1
                self.stats["last_action_time"] = time.time()
                return self.last_action
            
            elif msg.get("msg_type") == MessageType.CONFIG:
                print(f"[Client] 📋 收到服务器配置: {msg}")
            
            elif msg.get("msg_type") == MessageType.READY:
                print(f"[Client] ✅ 服务器模型就绪: {msg}")
            
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            print(f"[Client] ⚠️  接收异常: {e}")
        
        return None
    
    async def send_heartbeat(self):
        """发送心跳"""
        if self.standalone or not self.ws:
            return
        
        heartbeat = Heartbeat(
            seq=self.seq,
            timestamp=time.time(),
            source="client",
        )
        try:
            await self.ws.send(encode_message(heartbeat))
        except Exception:
            pass
    
    def print_status(self):
        """打印状态信息"""
        elapsed = time.time() - self.stats["start_time"]
        rate = self.stats["sensor_packets_sent"] / elapsed if elapsed > 0 else 0
        print(f"\r[Client] 📡 传感器包: {self.stats['sensor_packets_sent']} "
              f"| 动作: {self.stats['actions_received']} "
              f"| 频率: {rate:.1f} Hz "
              f"| 模式: {'独立仿真' if self.standalone else '联机'}"
              f"  ", end="", flush=True)
    
    async def run(self, duration: Optional[float] = None):
        """主循环"""
        self.running = True
        start_time = time.time()
        last_heartbeat = 0
        last_status = 0
        
        print(f"""
╔══════════════════════════════════════════════╗
║   Z-MAX 仿真客户端 v1.0                       ║
║   机器人: XMS5-R800-W4G3B4C (6轴)            ║
║   传感器: 关节/力/相机/夹爪/触觉              ║
║   发布频率: {self.sensor_rate_hz} Hz                       ║
║   模式: {'独立仿真' if self.standalone else f'联机 → {self.server_uri}'}
╚══════════════════════════════════════════════╝
""")
        
        try:
            while self.running:
                now = time.time()
                
                # 发布传感器数据
                await self.publish_sensors()
                
                # 接收动作 (非阻塞)
                await self.receive_actions()
                
                # 心跳
                if now - last_heartbeat > self.heartbeat_interval:
                    await self.send_heartbeat()
                    last_heartbeat = now
                
                # 状态打印
                if now - last_status > 2.0:
                    self.print_status()
                    last_status = now
                
                # 控制发布频率
                await asyncio.sleep(1.0 / self.sensor_rate_hz)
                
                # 超时退出
                if duration and (now - start_time) > duration:
                    print(f"\n[Client] ⏰ 运行{duration}秒, 退出")
                    break
                    
        except KeyboardInterrupt:
            print("\n[Client] ⏹  用户中断")
        finally:
            self.running = False
            if self.ws:
                await self.ws.close()
        
        # 打印最终统计
        self.print_stats()
    
    def print_stats(self):
        """打印统计报告"""
        elapsed = time.time() - self.stats["start_time"]
        print(f"""
┌──────────────────────────────────────────────┐
│          仿真客户端 — 运行统计                 │
├──────────────────────────────────────────────┤
│  运行时间:   {elapsed:.1f}s
│  传感器包:   {self.stats['sensor_packets_sent']} 包
│  发布频率:   {self.stats['sensor_packets_sent']/elapsed:.1f} Hz
│  接收动作:   {self.stats['actions_received']} 条
│  模式:       {'独立仿真 (无Server)' if self.standalone else '联机仿真'}
│  机器人:     XMS5-R800-W4G3B4C
│  传感器:     关节×6 + 力/扭矩×6 + 相机 + 夹爪 + 触觉
└──────────────────────────────────────────────┘
""")


# ═══════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Z-MAX 仿真客户端")
    parser.add_argument("--host", default="localhost", help="服务器地址")
    parser.add_argument("--port", type=int, default=8765, help="服务器端口")
    parser.add_argument("--standalone", action="store_true", help="独立仿真模式")
    parser.add_argument("--duration", type=float, default=None, help="运行时长(秒)")
    parser.add_argument("--rate", type=int, default=30, help="传感器发布频率(Hz)")
    args = parser.parse_args()
    
    client = SimulationClient(
        server_host=args.host,
        server_port=args.port,
        standalone=args.standalone,
    )
    client.sensor_rate_hz = args.rate
    
    # 信号处理
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: setattr(client, 'running', False))
        except NotImplementedError:
            pass
    
    async def startup():
        await client.connect()
        await client.run(duration=args.duration)
    
    try:
        asyncio.run(startup())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
