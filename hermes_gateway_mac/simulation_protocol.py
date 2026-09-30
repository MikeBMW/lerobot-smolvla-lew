#!/usr/bin/env python3
"""
Z-MAX 仿真协议 — Client-Server 共享消息格式

Mac端(client) ←→ WSL2端(server)
通信: JSON over WebSocket

用法:
    from simulation_protocol import SensorData, Action, Heartbeat, MessageType
"""

import json
import time
from dataclasses import dataclass, field, asdict
from typing import Optional
from enum import Enum


class MessageType(str, Enum):
    """消息类型"""
    SENSOR_DATA = "sensor_data"       # Client → Server: 传感器数据
    ACTION = "action"                  # Server → Client: 动作指令
    HEARTBEAT = "heartbeat"            # 双向心跳
    CONFIG = "config"                  # Server → Client: 配置同步
    STATUS = "status"                  # Client → Server: 状态上报
    ERROR = "error"                    # 双向错误
    READY = "ready"                    # Server → Client: 模型就绪
    SHUTDOWN = "shutdown"              # 双向关闭


@dataclass
class JointState:
    """6轴关节状态"""
    names: list = field(default_factory=lambda: [
        "XMS5-R800-W4G3B4C_joint_1",
        "XMS5-R800-W4G3B4C_joint_2",
        "XMS5-R800-W4G3B4C_joint_3",
        "XMS5-R800-W4G3B4C_joint_4",
        "XMS5-R800-W4G3B4C_joint_5",
        "XMS5-R800-W4G3B4C_joint_6",
    ])
    positions: list = field(default_factory=lambda: [
        0.160, -0.061, -2.545, 1.447, 0.435, -0.698
    ])
    velocities: list = field(default_factory=lambda: [0.0] * 6)
    efforts: list = field(default_factory=lambda: [0.0] * 6)


@dataclass
class ForceTorque:
    """六维力/扭矩传感器 (TS-T-15, 1kHz)"""
    fx: float = 0.0   # N
    fy: float = 0.0
    fz: float = 0.0
    tx: float = 0.0   # Nm
    ty: float = 0.0
    tz: float = 0.0
    timestamp: float = 0.0


@dataclass
class TactileData:
    """触觉传感器数据"""
    sensor_id: str = "tactile_array_01"
    pressure_grid: list = field(default_factory=lambda: [[0.0] * 4 for _ in range(4)])
    contact_detected: bool = False
    contact_force: float = 0.0
    timestamp: float = 0.0


@dataclass
class CameraFrame:
    """相机帧 (模拟 RealSense D435)"""
    source: str = "realsense_d435"     # realsense_d435 / wrist_camera
    width: int = 640
    height: int = 480
    channels: int = 3
    encoding: str = "rgb8"
    # 图像数据: base64编码的JPEG或原始字节的hex
    data_b64: str = ""
    depth_data_b64: str = ""  # 深度图
    timestamp: float = 0.0


@dataclass
class GripperState:
    """夹爪状态 (DH-Robotics)"""
    position: float = 0.0       # 0=全闭, 1=全开
    velocity: float = 0.0
    effort: float = 0.0         # 夹持力
    is_holding: bool = False    # 是否夹持中
    timestamp: float = 0.0


@dataclass
class SensorData:
    """传感器数据包 (Client → Server)"""
    msg_type: str = MessageType.SENSOR_DATA
    seq: int = 0
    timestamp: float = 0.0
    joint_state: dict = field(default_factory=dict)
    force_torque: dict = field(default_factory=dict)
    tactile: dict = field(default_factory=dict)
    camera: dict = field(default_factory=dict)
    gripper: dict = field(default_factory=dict)
    robot_model: str = "XMS5-R800-W4G3B4C"
    mode: str = "simulation"     # simulation / real


@dataclass
class Action:
    """动作指令 (Server → Client)"""
    msg_type: str = MessageType.ACTION
    seq: int = 0
    timestamp: float = 0.0
    joint_positions: list = field(default_factory=lambda: [0.0] * 6)
    joint_velocities: list = field(default_factory=lambda: [0.0] * 6)
    gripper_cmd: float = 0.0     # 0-1
    inference_time_ms: float = 0.0
    model_name: str = "smolvla_base"
    confidence: float = 1.0
    mode: str = "simulation"


@dataclass
class Heartbeat:
    """心跳消息"""
    msg_type: str = MessageType.HEARTBEAT
    seq: int = 0
    timestamp: float = 0.0
    source: str = ""              # client / server


@dataclass
class SimConfig:
    """仿真配置"""
    msg_type: str = MessageType.CONFIG
    # 传感器参数
    camera_fps: int = 30
    force_sample_rate_hz: int = 10000
    joint_publish_rate_hz: int = 100
    # 模型参数
    policy_path: str = "lerobot/smolvla_base"
    inference_device: str = "cuda"
    action_horizon: int = 50
    # 控制参数
    control_mode: str = "position"   # position / velocity / torque
    safety_force_limit_n: float = 5.0
    max_retry_count: int = 3


# ═══════════════════════════════════════════════
# 消息编解码
# ═══════════════════════════════════════════════

def encode_message(obj) -> str:
    """编码消息为JSON字符串"""
    if hasattr(obj, '__dataclass_fields__'):
        return json.dumps(asdict(obj), ensure_ascii=False)
    return json.dumps(obj, ensure_ascii=False)


def decode_message(raw: str) -> dict:
    """解码JSON字符串为字典"""
    return json.loads(raw)


def build_sensor_data(seq: int, joints: JointState = None,
                      ft: ForceTorque = None, tactile: TactileData = None,
                      camera: CameraFrame = None, gripper: GripperState = None) -> SensorData:
    """构建传感器数据包"""
    if joints is None:
        joints = JointState()
    if ft is None:
        ft = ForceTorque()
    if tactile is None:
        tactile = TactileData()
    if camera is None:
        camera = CameraFrame()
    if gripper is None:
        gripper = GripperState()

    return SensorData(
        seq=seq,
        timestamp=time.time(),
        joint_state=asdict(joints),
        force_torque=asdict(ft),
        tactile=asdict(tactile),
        camera=asdict(camera),
        gripper=asdict(gripper),
    )


def build_action(seq: int, positions: list, gripper_cmd: float = 0.0,
                 inference_ms: float = 0.0) -> Action:
    """构建动作指令"""
    return Action(
        seq=seq,
        timestamp=time.time(),
        joint_positions=positions,
        gripper_cmd=gripper_cmd,
        inference_time_ms=inference_ms,
    )


# ═══════════════════════════════════════════════
# 话题名常量 (兼容ROS2命名规范)
# ═══════════════════════════════════════════════

TOPICS = {
    # 传感器话题 (Client发布, Server订阅)
    "joint_states": "/sim/joint_states",
    "force_torque": "/sim/robot/force_torque",
    "tactile": "/sim/tactile_sensor",
    "camera_color": "/sim/realsense/color/image_raw",
    "camera_depth": "/sim/realsense/depth/image_rect_raw",
    "gripper": "/sim/gripper_pos",
    "robot_status": "/sim/robot_status",
    # 控制话题 (Server发布, Client订阅)
    "action": "/sim/action",
    "gripper_cmd": "/sim/gripper_cmd",
    "brake": "/sim/brake_ctrl",
    "estop": "/sim/emergency_stop",
}

print(f"[Protocol] Z-MAX Simulation Protocol v1.0 loaded ({len(TOPICS)} topics)")
