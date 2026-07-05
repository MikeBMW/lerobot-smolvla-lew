"""
Z-MAX 硬件仿真引擎 · System 0
================================
模拟 Z700 轮式双臂机器人的完整硬件栈:
  - VirtualRobot:  双臂14-DOF关节模拟 (位置/速度/力矩)
  - VirtualCamera: 多路相机流 (头部3D/腕部RGB/鱼眼)
  - VirtualForceSensor: 六维力/力矩传感器
  - VirtualIO:     数字IO模拟 (急停/塔灯/光栅/扫码枪)
  - VirtualGripper: 左右夹爪模拟 (位置/力控)

设计原则:
  - 与真实 ROS2 topic 接口保持一致，仿真→真机只需切换模式
  - 独立的 QThread 周期更新，不阻塞 GUI
  - 可配置噪声/延迟/故障注入，模拟真实工况
"""

import math
import time
import random
import threading
from dataclasses import dataclass, field
from typing import Optional, Callable

import numpy as np


# ═══════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════

@dataclass
class JointState:
    """单关节状态"""
    name: str
    position: float = 0.0       # rad
    velocity: float = 0.0       # rad/s
    torque: float = 0.0         # Nm
    target: float = 0.0         # 目标位置
    enabled: bool = True
    temperature: float = 35.0   # °C
    current: float = 0.0        # A


@dataclass
class CameraFrame:
    """单帧图像"""
    name: str
    width: int = 640
    height: int = 480
    fps: float = 30.0
    encoding: str = "rgb8"      # rgb8 / mono8 / depth32
    timestamp: float = 0.0
    data: Optional[np.ndarray] = None


@dataclass
class ForceData:
    """六维力数据"""
    fx: float = 0.0; fy: float = 0.0; fz: float = 0.0   # N
    tx: float = 0.0; ty: float = 0.0; tz: float = 0.0   # Nm
    timestamp: float = 0.0


@dataclass
class IOState:
    """数字IO状态"""
    estop: bool = False         # 急停 (常开, True=按下)
    tower_light: int = 0        # 塔灯 0=灭 1=红 2=黄 3=绿
    light_curtain: bool = True  # 光栅 (True=未触发)
    barcode_scanner: str = ""   # 扫码枪数据
    gripper_left: float = 0.0   # 左夹爪开度 0-1
    gripper_right: float = 0.0  # 右夹爪开度 0-1


# ═══════════════════════════════════════════════
# Z700 硬件定义
# ═══════════════════════════════════════════════

Z700_JOINTS = {
    # 左臂 (7 DOF)
    "left_joint_1":  "左臂基座旋转",
    "left_joint_2":  "左臂肩部俯仰",
    "left_joint_3":  "左臂肘部俯仰",
    "left_joint_4":  "左臂腕部旋转",
    "left_joint_5":  "左臂腕部俯仰",
    "left_joint_6":  "左臂腕部偏航",
    "left_gripper":  "左夹爪开合",
    # 右臂 (7 DOF)
    "right_joint_1": "右臂基座旋转",
    "right_joint_2": "右臂肩部俯仰",
    "right_joint_3": "右臂肘部俯仰",
    "right_joint_4": "右臂腕部旋转",
    "right_joint_5": "右臂腕部俯仰",
    "right_joint_6": "右臂腕部偏航",
    "right_gripper": "右夹爪开合",
}

Z700_CAMERAS = {
    "head_3d":      {"w": 1280, "h": 720,  "fps": 30, "enc": "rgb8",   "desc": "头部3D深度相机 Gemini 335L"},
    "left_wrist":   {"w": 640,  "h": 480,  "fps": 60, "enc": "rgb8",   "desc": "左腕部RGB相机"},
    "right_wrist":  {"w": 640,  "h": 480,  "fps": 60, "enc": "rgb8",   "desc": "右腕部RGB相机"},
    "fisheye_0":    {"w": 640,  "h": 480,  "fps": 15, "enc": "rgb8",   "desc": "鱼眼相机 #0"},
    "fisheye_1":    {"w": 640,  "h": 480,  "fps": 15, "enc": "rgb8",   "desc": "鱼眼相机 #1"},
    "fisheye_2":    {"w": 640,  "h": 480,  "fps": 15, "enc": "rgb8",   "desc": "鱼眼相机 #2"},
    "fisheye_3":    {"w": 640,  "h": 480,  "fps": 15, "enc": "rgb8",   "desc": "鱼眼相机 #3"},
}

Z700_ROS2_NODES = {
    # 仿真模式下可见的虚拟节点
    "sim": [
        ("/zmax/virtual_robot",     "关节状态发布 + 订阅目标"),
        ("/zmax/camera_head_3d",    "头部3D相机 (rgb+depth)"),
        ("/zmax/camera_left_wrist", "左腕相机"),
        ("/zmax/camera_right_wrist","右腕相机"),
        ("/zmax/force_sensor",      "六维力/力矩传感器"),
        ("/zmax/io_controller",     "IO控制器 (急停/塔灯/光栅)"),
        ("/zmax/gripper_control",   "夹爪控制 (力控+位置)"),
        ("/zmax/safety_monitor",    "安全监控节点"),
    ],
    # 真机模式下的已知节点 (从 D23 实测)
    "real": [
        ("/tashan/robot_driver",        "他山机器人驱动"),
        ("/tashan/real_joint_states",   "真实关节状态"),
        ("/tashan/gripper_pos",         "夹爪位置"),
        ("/tashan/robot_status",        "机器人状态"),
        ("/tashan/tower_light/status",  "塔灯状态"),
        ("/tashan/camera_*/",           "相机阵列"),
        ("/tashan/barcode_scanner",     "扫码枪"),
        ("/tashan/foundationpose",      "FoundationPose视觉"),
        ("/tashan/force_sensor",        "力传感器"),
        ("/tashan/emergency_stop",      "急停"),
    ],
}


# ═══════════════════════════════════════════════
# 仿真引擎核心
# ═══════════════════════════════════════════════

class HardwareSimulator:
    """
    Z700 硬件仿真引擎
    
    模式: 'sim' | 'local' | 'real'
      - sim:   纯虚拟设备，带可调噪声
      - local: 尝试连接本地 ROS2/DDS
      - real:  连接 Orin 真机 (TCP Bridge / gRPC)
    """

    def __init__(self, mode: str = "sim"):
        self.mode = mode
        self.running = False
        self._thread: Optional[threading.Thread] = None
        self._tick_hz = 1000  # 1ms 控制周期
        self._start_time = time.time()
        self._callbacks: dict[str, list[Callable]] = {}

        # 初始化虚拟设备
        self.joints: dict[str, JointState] = {}
        self.cameras: dict[str, CameraFrame] = {}
        self.force = ForceData()
        self.io = IOState()
        self._init_sim_devices()

        # 仿真参数
        self.noise_level = 0.001    # 关节噪声 (rad)
        self.force_noise = 0.05     # 力传感器噪声 (N)
        self.fault_injection = {}   # 故障注入配置

    def _init_sim_devices(self):
        """初始化所有虚拟设备"""
        for jname in Z700_JOINTS:
            self.joints[jname] = JointState(name=jname)
        for cname, cfg in Z700_CAMERAS.items():
            self.cameras[cname] = CameraFrame(
                name=cname,
                width=cfg["w"], height=cfg["h"],
                fps=cfg["fps"], encoding=cfg["enc"]
            )

    # ── 生命周期 ──

    def start(self):
        if self.running:
            return
        self.running = True
        self._thread = threading.Thread(target=self._sim_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self.running = False
        if self._thread:
            self._thread.join(timeout=2)

    def reset(self):
        """重置所有设备到初始状态"""
        self._start_time = time.time()
        self._init_sim_devices()
        self.force = ForceData()
        self.io = IOState()

    # ── 仿真主循环 ──

    def _sim_loop(self):
        """1ms 周期仿真循环"""
        interval = 1.0 / self._tick_hz
        while self.running:
            t = time.time() - self._start_time
            self._update_joints(t)
            self._update_force(t)
            self._update_cameras(t)
            self._update_io(t)
            time.sleep(interval)

    def _update_joints(self, t: float):
        """关节仿真: 正弦波 + 噪声"""
        for i, (jname, joint) in enumerate(self.joints.items()):
            if not joint.enabled:
                continue
            phase = i * 0.5  # 各关节不同相位
            # 基础正弦运动
            joint.position = joint.target + 0.1 * math.sin(t * 2.0 + phase)
            joint.velocity = 0.1 * 2.0 * math.cos(t * 2.0 + phase)
            joint.torque = 0.05 * math.sin(t * 1.5 + phase)
            joint.current = abs(joint.torque) * 10.0
            joint.temperature = 35.0 + random.gauss(0, 0.5)
            # 加噪声
            if self.noise_level > 0:
                joint.position += random.gauss(0, self.noise_level)

    def _update_force(self, t: float):
        """力传感器仿真"""
        self.force.timestamp = t
        self.force.fx = 0.5 * math.sin(t * 1.5) + random.gauss(0, self.force_noise)
        self.force.fy = 0.3 * math.cos(t * 2.0) + random.gauss(0, self.force_noise)
        self.force.fz = random.gauss(-1.0, self.force_noise)  # 插入力
        self.force.tx = random.gauss(0, 0.01)
        self.force.ty = random.gauss(0, 0.01)
        self.force.tz = random.gauss(0, 0.005)

    def _update_cameras(self, t: float):
        """相机仿真: 生成测试图案帧"""
        for cname, cam in self.cameras.items():
            cam.timestamp = t
            # 测试图案: 彩色条纹
            if cam.encoding == "rgb8":
                h, w = cam.height, cam.width
                data = np.zeros((h, w, 3), dtype=np.uint8)
                stripe_width = 40
                for col in range(w):
                    color_val = int(127 + 127 * math.sin((col / stripe_width) + t * 3))
                    data[:, col] = [color_val, (color_val + 85) % 255, (color_val + 170) % 255]
                # 叠加文字提示
                cam.data = data

    def _update_io(self, t: float):
        """IO 仿真"""
        self.io.tower_light = 3 if self.running else 0  # 运行中绿灯
        self.io.light_curtain = True
        # 模拟夹爪随关节运动
        if "left_gripper" in self.joints:
            self.io.gripper_left = max(0, min(1, 
                0.3 + 0.2 * math.sin(t * 1.5)))
        if "right_gripper" in self.joints:
            self.io.gripper_right = max(0, min(1,
                0.5 + 0.3 * math.cos(t * 2.0)))

    # ── 回调注册 ──

    def on_update(self, event: str, callback: Callable):
        """注册更新回调: joint_state / camera_frame / force_data / io_state"""
        if event not in self._callbacks:
            self._callbacks[event] = []
        self._callbacks[event].append(callback)

    def _notify(self, event: str):
        for cb in self._callbacks.get(event, []):
            try:
                cb()
            except Exception:
                pass

    # ── 故障注入 (调试用) ──

    def inject_fault(self, device: str, fault_type: str, params: dict | None = None):
        """注入硬件故障"""
        self.fault_injection[device] = {
            "type": fault_type,
            "params": params or {},
            "active": True,
        }

    def clear_fault(self, device: str):
        self.fault_injection.pop(device, None)

    # ── 获取状态快照 ──

    def get_joint_snapshot(self) -> dict:
        """全部关节状态快照"""
        return {
            jname: {
                "pos": round(j.position, 5),
                "vel": round(j.velocity, 5),
                "torque": round(j.torque, 5),
                "temp": round(j.temperature, 1),
                "current": round(j.current, 2),
                "enabled": j.enabled,
            }
            for jname, j in self.joints.items()
        }

    def get_camera_snapshot(self) -> dict:
        """相机状态快照"""
        return {
            cname: {
                "size": f"{c.width}x{c.height}",
                "fps": c.fps,
                "enc": c.encoding,
                "ts": round(c.timestamp, 3),
            }
            for cname, c in self.cameras.items()
        }

    def get_io_snapshot(self) -> dict:
        """IO状态快照"""
        return {
            "estop": "🔴 触发" if self.io.estop else "🟢 正常",
            "tower_light": ["⚫灭", "🔴红", "🟡黄", "🟢绿"][self.io.tower_light],
            "light_curtain": "🟢 未触发" if self.io.light_curtain else "🔴 触发",
            "gripper_left": f"{self.io.gripper_left:.2f}",
            "gripper_right": f"{self.io.gripper_right:.2f}",
        }

    def get_topology(self) -> dict:
        """系统拓扑"""
        joint_count = len(Z700_JOINTS)
        enabled = sum(1 for j in self.joints.values() if j.enabled)
        return {
            "mode": self.mode,
            "joints": f"{enabled}/{joint_count} active",
            "cameras": f"{len(Z700_CAMERAS)} configured",
            "force_sensor": "✅ 1x 6-axis",
            "io_devices": "estop + tower_light + curtain + barcode",
            "control_hz": self._tick_hz,
            "uptime": f"{time.time() - self._start_time:.1f}s",
        }


# ═══════════════════════════════════════════════
# 单例
# ═══════════════════════════════════════════════

_simulator: Optional[HardwareSimulator] = None


def get_simulator(mode: str = "sim") -> HardwareSimulator:
    global _simulator
    if _simulator is None:
        _simulator = HardwareSimulator(mode=mode)
    return _simulator
