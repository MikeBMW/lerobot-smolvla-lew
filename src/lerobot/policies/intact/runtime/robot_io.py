# -*- coding: utf-8 -*-
"""🔌 输出接口 (intact_node.robot_io) — 节点 → 机器人硬件 (预留可插拔)。

契约 (真机侧只需实现这 3 个方法):
    send_chunk(chunk[H,D]) -> None   下发一个动作块 (或块内逐步下发, 由实现决定)
    reset()               -> None    复位 (清动作历史/使能)
    estop()               -> None    急停 (必须真实切断, 不许静默)

· SimRobotIO      — 调试用: 接到 L4 引擎 (metaworld) 或任意回调
· HardwareRobotIO — **预留**: 真机 (EtherCAT / ROS2 / 串口 / 厂商 SDK)。未接硬件时
                    构造即抛 NotImplementedError, 绝不写假实现冒充"已接硬件"。
"""
from __future__ import annotations

import abc
from typing import Callable

import numpy as np


class RobotIO(abc.ABC):
    """动作块输出接口 (节点唯一对外硬件出口)。"""

    name = "abstract"

    @abc.abstractmethod
    def send_chunk(self, chunk: np.ndarray) -> None:
        """下发 [H,D] 动作块。实现需自行处理: 限幅/插值/时序/看门狗。"""

    @abc.abstractmethod
    def reset(self) -> None: ...

    @abc.abstractmethod
    def estop(self) -> None: ...

    def capabilities(self) -> dict:
        return {"name": self.name, "max_chunk": None, "rate_hz": None}


class SimRobotIO(RobotIO):
    """调试输出: 把动作块交给回调 (L4 引擎逐步执行 / 记录轨迹)。"""

    name = "sim"

    def __init__(self, apply_fn: Callable[[np.ndarray], None] | None = None,
                 rate_hz: float = 20.0, clip: float = 1.0) -> None:
        self.apply_fn = apply_fn or (lambda a: None)
        self.rate_hz = float(rate_hz)
        self.clip = float(clip)
        self.log: list[np.ndarray] = []
        self.reset()

    def send_chunk(self, chunk: np.ndarray) -> None:
        ch = np.clip(np.asarray(chunk, dtype=np.float32), -self.clip, self.clip)
        for step in ch:                       # 逐步下发 = 真实控制器的时序语义
            self.apply_fn(step)
            self.log.append(np.asarray(step, dtype=np.float32))
        self.n_chunks += 1

    def reset(self) -> None:
        self.n_chunks = 0
        self.estop_flag = False

    def estop(self) -> None:
        self.estop_flag = True
        raise RuntimeError("SimRobotIO 急停 (调试实现)")

    def capabilities(self) -> dict:
        return {"name": self.name, "max_chunk": None, "rate_hz": self.rate_hz,
                "clip": self.clip, "impl": "回调/L4 引擎"}


class HardwareRobotIO(RobotIO):
    """**预留**: 真机输出。签名固定, 实现留白 (按现场总线填)。

    实现指引 (三者任一):
      · EtherCAT: 把 chunk 写入 PDO 映射 (周期 1kHz) + 关节/笛卡尔跟踪器
      · ROS2:     publish sensor_msgs/JointTrajectory 或自定义 Action
      · 串口/SDK: 厂商指令帧 + 状态回读 + 看门狗
    ⚠️ 必须自带: 限幅、速度/加速度限制、通信超时急停。未接入前禁用。
    """

    name = "hardware"

    def __init__(self, endpoint: str | None = None, **kwargs) -> None:
        raise NotImplementedError(
            "HardwareRobotIO 为预留接口: 现场总线 (EtherCAT/ROS2/串口/SDK) 未接入。"
            "调试阶段请使用 SimRobotIO; 接入时实现 send_chunk/reset/estop 三个方法即可插拔。")

    def send_chunk(self, chunk: np.ndarray) -> None:  # pragma: no cover
        raise NotImplementedError

    def reset(self) -> None:  # pragma: no cover
        raise NotImplementedError

    def estop(self) -> None:  # pragma: no cover
        raise NotImplementedError
