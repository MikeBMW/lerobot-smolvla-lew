"""
Z-MAX Robot 抽象 · 实现 LeRobot Robot 接口

L2: ZmaxL2Robot — 基线版, 纯ROS2 Service规则
L3: ZmaxL3Robot — 增强版, ACT引擎 + 触觉/力控
L4: ZmaxL4Robot — 旗舰版, SmolVLA + 因果世界模型

映射 Orin ROS2 Topic → LeRobot observation/action
"""
from __future__ import annotations
import numpy as np
from dataclasses import dataclass
from typing import Optional

from lerobot.robots.robot import Robot
from lerobot.robots.config import RobotConfig
from lerobot.types import RobotAction, RobotObservation
from lerobot.motors import MotorCalibration

from .hardware_tree import ZMAX_HARDWARE_TREE, ZmaxLevel, flatten_tree


@dataclass
class ZmaxRobotConfig(RobotConfig):
    """Z-MAX 机器人配置"""
    level: str = "L2"          # L2/L3/L4
    source: str = "sim"        # sim / orin / local
    orin_host: str = "192.168.23.10"
    orin_port: int = 50051
    mock: bool = True          # 仿真模式下使用模拟数据


class ZmaxBaseRobot(Robot):
    """Z-MAX 机器人基类 · 实现 LeRobot Robot 接口"""

    config_class = ZmaxRobotConfig

    def __init__(self, config: ZmaxRobotConfig):
        super().__init__(config)
        self._config = config
        self._level = ZmaxLevel(config.level)
        self._connected = False
        self._hw_nodes = flatten_tree(ZMAX_HARDWARE_TREE)
        self._joint_count = self._count_joints()
        # 动作空间: 12DoF (6左+6右) + 2夹爪
        self._action_dim = 14
        # 观测空间: 关节(12) + 力(6) + 触觉(16) + 夹爪(2) = 36
        self._obs_dim = 36

    def _count_joints(self) -> int:
        return sum(1 for n in self._hw_nodes if n["type"] == "joint")

    @property
    def hardware_tree(self) -> list[dict]:
        return self._hw_nodes

    @property
    def level(self) -> ZmaxLevel:
        return self._level

    # ━━━ LeRobot Robot 接口 ━━━

    def connect(self):
        """连接机器人 (Orin gRPC / 仿真Mock)"""
        if self._config.mock:
            self._connected = True
            return
        # TODO: gRPC连接到Orin
        # import grpc
        # self._stub = ZmaxServiceStub(grpc.insecure_channel(f"{self._config.orin_host}:{self._config.orin_port}"))
        self._connected = True

    def disconnect(self):
        self._connected = False

    def send_action(self, action: RobotAction):
        """发送动作指令 → Orin ROS2 Action Server"""
        if self._config.mock:
            return
        # TODO: gRPC SendAction(action)
        pass

    def get_observation(self) -> RobotObservation:
        """获取观测数据 ← Orin ROS2 Topic"""
        if self._config.mock:
            return self._mock_observation()
        # TODO: gRPC GetObservation()
        return self._mock_observation()

    def _mock_observation(self) -> RobotObservation:
        """模拟观测数据 (仿真模式)"""
        return {
            "joint_positions": np.random.randn(self._joint_count).astype(np.float32) * 0.5,
            "joint_velocities": np.random.randn(self._joint_count).astype(np.float32) * 0.3,
            "force_torque": np.random.randn(6).astype(np.float32) * 0.5,
            "gripper_left": np.float32(np.random.randint(0, 255)),
            "gripper_right": np.float32(np.random.randint(0, 255)),
            "tactile": np.random.randn(16).astype(np.float32) * 0.1 if self._level in [ZmaxLevel.L3, ZmaxLevel.L4] else np.zeros(16, dtype=np.float32),
        }

    def teleop_safety_stop(self):
        """紧急停止"""
        if self._config.mock:
            return
        # TODO: gRPC EmergencyStop()

    def calibrate(self):
        """标定"""
        pass

    def teleop_step(self, *args, **kwargs):
        """遥操作步进"""
        pass


class ZmaxL2Robot(ZmaxBaseRobot):
    """Z700F · L2 基线版 · 纯ROS2规则引擎"""
    name = "zmax_l2"

    def __init__(self, config: ZmaxRobotConfig = None):
        if config is None:
            config = ZmaxRobotConfig(level="L2")
        super().__init__(config)

    # L2 无AI推理, 纯Rule-based
    def rule_based_action(self, obs: RobotObservation) -> RobotAction:
        """预设规则: 定序动作"""
        return np.zeros(14, dtype=np.float32)  # 占位


class ZmaxL3Robot(ZmaxBaseRobot):
    """Z700 · L3 增强版 · ACT引擎 + 触觉/力控"""
    name = "zmax_l3"

    def __init__(self, config: ZmaxRobotConfig = None):
        if config is None:
            config = ZmaxRobotConfig(level="L3")
        super().__init__(config)

    def _mock_observation(self) -> RobotObservation:
        obs = super()._mock_observation()
        # L3额外: 力传感器 + 触觉
        obs["force_torque"] = np.random.randn(6).astype(np.float32) * 1.0
        obs["tactile"] = np.random.randn(16).astype(np.float32) * 0.3
        return obs


class ZmaxL4Robot(ZmaxBaseRobot):
    """Z700 · L4 旗舰版 · SmolVLA + 因果世界模型"""
    name = "zmax_l4"

    def __init__(self, config: ZmaxRobotConfig = None):
        if config is None:
            config = ZmaxRobotConfig(level="L4")
        super().__init__(config)

    def _mock_observation(self) -> RobotObservation:
        obs = ZmaxL3Robot._mock_observation(self)
        # L4额外: 深度图 + IMU + 热成像
        obs["depth_image"] = np.random.rand(480, 640).astype(np.float32) * 3.0
        obs["imu"] = np.random.randn(9).astype(np.float32) * 0.1
        return obs
