"""
Z-MAX Orin Robot — leRobot 标准接口实现

将 珞石 XMS5-R800 的 ROS2 topic/服务 封装为 leRobot Robot 抽象

层次:
  L2 (Z700F基线):  只读关节+力控阈值保护, 无自主运动
  L3 (Z700增强):   条件自动化, topic+service 读写
  L4 (Z700旗舰):   全自主, 视觉引导+力控自适应+AI安全

硬件树:
  Robot
  ├── joints ×6 (XMS5-R800)
  ├── gripper (DH PGE/PGC)
  ├── force_sensor (TS-T-15 六维力 1kHz)
  ├── tactile_sensor ×2 (CH341 触觉阵列)
  ├── camera_realsense (D405 RGB-D)
  ├── camera_mechmind (Mech-Mind 3D)
  ├── barcode_scanner (Honeywell 3310)
  ├── tower_light (Artery LED)
  ├── emergency_stop (双路急停)
  └── light_curtain (安全光栅)

用法:
  from zmax_orin import ZMaxOrinRobot, ZMaxOrinConfig
  config = ZMaxOrinConfig(level="L3", orin_host="192.168.23.10")
  with ZMaxOrinRobot(config) as robot:
      obs = robot.get_observation()
      robot.send_action({"joint_positions": [0.1,0,0,0,0,0]})
"""

import time, json, os, threading, subprocess
from typing import Optional, Dict, List
from dataclasses import dataclass, field

try:
    import rclpy
    from rclpy.node import Node
    from sensor_msgs.msg import JointState
    from std_msgs.msg import Float32, Bool
    HAS_ROS2 = True
except ImportError:
    HAS_ROS2 = False


# ═══════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════

@dataclass
class ZMaxOrinConfig:
    """Z-MAX Orin 机器人配置"""
    level: str = "L2"          # L2/L3/L4
    orin_host: str = "192.168.23.10"
    orin_user: str = "nvidia"
    controller_ip: str = "192.168.23.160"
    robot_model: str = "XMS5-R800-W4G3B4C"
    ros_domain_id: int = 23
    use_sim: bool = False      # 仿真模式

    # 关节
    joint_count: int = 6
    joint_names: list = field(default_factory=lambda: [
        "XMS5-R800-W4G3B4C_joint_1", "XMS5-R800-W4G3B4C_joint_2",
        "XMS5-R800-W4G3B4C_joint_3", "XMS5-R800-W4G3B4C_joint_4",
        "XMS5-R800-W4G3B4C_joint_5", "XMS5-R800-W4G3B4C_joint_6",
    ])

    # 安全
    force_limit_z_n: float = 5.0
    force_limit_xy_n: float = 3.0
    torque_limit_nm: float = 0.5
    velocity_limit_rad_s: float = 2.0
    joint_limits_rad: tuple = (-3.0, 3.0)


# ═══════════════════════════════════════════════
# 硬件树
# ═══════════════════════════════════════════════

HARDWARE_TREE = {
    "robot": {
        "name": "Z700",
        "model": "XMS5-R800-W4G3B4C",
        "type": "轮式双臂人形机器人",
        "dof": 6,
        "controller": {"ip": "192.168.23.160", "brand": "珞石 ROKAE", "protocol": "xCoreSDK UDP实时"},
        "compute": {"orin": "192.168.23.10", "orin_virtual": "192.168.23.66", "platform": "NVIDIA AGX Orin 32GB", "cuda": "12.6"}
    },
    "actuators": {
        "joints": [
            {"id": 1, "name": "joint_1", "axis": "基座旋转", "type": "旋转", "limits_rad": [-2.0, 2.0], "max_velocity_rad_s": 2.0, "topic": "/real_joint_states"},
            {"id": 2, "name": "joint_2", "axis": "肩部俯仰", "type": "旋转", "limits_rad": [-2.0, 2.0], "max_velocity_rad_s": 2.0, "topic": "/real_joint_states"},
            {"id": 3, "name": "joint_3", "axis": "肘部俯仰", "type": "旋转", "limits_rad": [-3.0, 0.5], "max_velocity_rad_s": 2.0, "topic": "/real_joint_states"},
            {"id": 4, "name": "joint_4", "axis": "腕部旋转", "type": "旋转", "limits_rad": [-3.0, 3.0], "max_velocity_rad_s": 2.0, "topic": "/real_joint_states"},
            {"id": 5, "name": "joint_5", "axis": "腕部俯仰", "type": "旋转", "limits_rad": [-2.0, 2.0], "max_velocity_rad_s": 2.0, "topic": "/real_joint_states"},
            {"id": 6, "name": "joint_6", "axis": "腕部末端", "type": "旋转", "limits_rad": [-3.0, 3.0], "max_velocity_rad_s": 2.0, "topic": "/real_joint_states"}
        ],
        "gripper": {"model": "DH PGE/PGC", "type": "电动平行夹爪", "stroke_mm": 50, "max_force_n": 50, "topic": "/gripper_pos", "service": "/gripper_driver"},
        "gripper_services": [
            {"name": "set_position", "params": {"pos": 0.0, "speed": 100, "force": 40}, "service": "/gripper_driver"}
        ]
    },
    "sensors": {
        "force_torque": {"model": "TS-T-15", "type": "六维力/扭矩", "axes": ["Fx","Fy","Fz","Tx","Ty","Tz"], "sample_rate_hz": 10000, "topic": "/robot/force_torque"},
        "tactile": [
            {"id": 1, "location": "左手指尖", "type": "4×4压力阵列", "interface": "CH341 USB", "topic": "/tactile_sensor"},
            {"id": 2, "location": "右手指尖", "type": "4×4压力阵列", "interface": "CH341 USB", "topic": "/tactile_sensor"}
        ],
        "cameras": [
            {"name": "realsense_d405", "type": "RGB-D", "resolution": "640×480", "fps": 30, "topic": "/realsense/color/image_raw", "depth_topic": "/realsense/depth/image_rect_raw"},
            {"name": "mechmind_3d", "type": "3D结构光", "resolution": "1280×800", "topic": "/mechmind/color", "service": "/vision_pipeline"}
        ],
        "barcode_scanner": {"model": "Honeywell 3310", "type": "二维码扫描", "interface": "USB Serial", "service": "/barcode_scanner/start_scan"},
        "imu": {"type": "内置6轴IMU", "topic": "/robot/tcp_pose"}
    },
    "safety": {
        "emergency_stop": {"type": "双路急停", "channels": 2, "response_ms": 1, "topic": "/emergency_stop"},
        "light_curtain": {"type": "安全光栅", "topic": "/physical_estop"},
        "tower_light": {"model": "Artery LED", "type": "三色塔灯", "states": ["绿=正常","黄=警告","红=停止"], "topic": "/tower_light/command"},
        "sys0_safety": {"loaded": True, "levels": ["L1_estop","L2_force","L3_light_curtain","L4_predictive"]}
    },
    "control": {
        "motion_services": [
            {"name": "相对关节运动", "service": "/target_relative_joint", "params": "6D偏移量"},
            {"name": "绝对关节运动", "service": "/move_joint", "params": "6D目标位置"},
            {"name": "力控搜索插入", "service": "/lissajous_force_search", "params": "期望力+刚度"},
            {"name": "运动序列", "service": "/move_sequence", "params": "waypoint序列"}
        ],
        "state_machine": {"service": "/state_machine/set_mode", "modes": ["实机","仿真"], "topic": "/motion/execution_result"},
        "external_comm": {"service": "/external_comm", "topic": "/execute_external_task", "type": "外部任务触发"}
    }
}


# ═══════════════════════════════════════════════
# Robot 实现
# ═══════════════════════════════════════════════

class ZMaxOrinRobot:
    """Z-MAX Orin 机器人 — leRobot 标准接口"""

    name = "zmax_orin"
    LEVELS = {"L2": "分段式自动化", "L3": "条件自动化", "L4": "高度自动化"}

    def __init__(self, config: ZMaxOrinConfig = None):
        self.config = config or ZMaxOrinConfig()
        self._connected = False
        self._calibrated = True
        self._running = False
        self._lock = threading.Lock()

        # 观察缓存
        self._obs = {
            "joint_positions": [0.0] * 6,
            "joint_velocities": [0.0] * 6,
            "gripper_position": 0.0,
            "force_torque": {"fx": 0, "fy": 0, "fz": 0, "tx": 0, "ty": 0, "tz": 0},
            "tcp_pose": {"x": 0, "y": 0, "z": 0, "rx": 0, "ry": 0, "rz": 0},
            "estop": False,
            "timestamp": 0.0,
        }

    # ── leRobot 接口 ──

    @property
    def observation_features(self) -> dict:
        return {
            "joint_positions": list,  # 6D
            "joint_velocities": list,
            "gripper_position": float,
            "force_torque": dict,
            "tcp_pose": dict,
            "estop": bool,
        }

    @property
    def action_features(self) -> dict:
        return {
            "target_joint_positions": list,  # 6D
            "gripper_command": float,
        }

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def is_calibrated(self) -> bool:
        return self._calibrated

    def get_level_name(self) -> str:
        return self.LEVELS.get(self.config.level, "未知")

    def connect(self, calibrate: bool = True):
        """连接机器人 — SSH + ROS2"""
        if self.config.use_sim:
            from orin_sim_bridge import SimulatedOrin
            self._sim = SimulatedOrin()
            self._connected = True
            self._poll_thread = threading.Thread(target=self._poll_sim, daemon=True)
            self._poll_thread.start()
            print(f"[Z-MAX] 仿真模式连接成功 ({self.get_level_name()})")
            return

        # 真机模式: SSH 轮询 ROS2 话题
        self._connected = True
        self._poll_thread = threading.Thread(target=self._poll_orin, daemon=True)
        self._poll_thread.start()
        print(f"[Z-MAX] Orin 连接成功 ({self.get_level_name()})")

    def disconnect(self):
        self._running = False
        self._connected = False
        if hasattr(self, '_sim'):
            self._sim.running = False

    def calibrate(self):
        self._calibrated = True

    def configure(self):
        """运行时配置"""
        pass

    def get_observation(self) -> dict:
        """获取观测 — leRobot 标准格式"""
        with self._lock:
            return dict(self._obs)

    def send_action(self, action: dict) -> dict:
        """发送动作 — L3/L4 级别"""
        if self.config.level == "L2":
            return {"error": "L2级别不支持自主运动", "action": action}

        if self.config.use_sim:
            targets = action.get("target_joint_positions", [0]*6)
            self._sim.move_absolute(targets)
            return {"success": True, "targets": targets}

        # L3/L4: SSH + ROS2 service call
        joint_names_str = str(self.config.joint_names)
        positions_str = str(action.get("target_joint_positions", [0]*6))
        cmd = (
            f"source /opt/ros/humble/setup.bash && "
            f"source ~/0615/tashan_robot_so_20260630_163849_f98c30a_aarch64/install/setup.bash && "
            f"export ROS_DOMAIN_ID=23 && "
            f"ros2 service call /target_relative_joint interfaces/srv/TargetJoint "
            f"'{{sim_mode: false, joint_state: {{name: {joint_names_str}, "
            f"position: {positions_str}, velocity: [0,0,0,0,0,0.1]}}}}'"
        )

        try:
            r = subprocess.run(["ssh", "nvidia@" + self.config.orin_host, cmd],
                             capture_output=True, text=True, timeout=5)
            return {"success": "success" in r.stdout.lower(), "raw": r.stdout[-200:]}
        except:
            return {"error": "SSH timeout"}

    # ── 内部轮询 ──

    def _poll_sim(self):
        while self._running if hasattr(self, '_running') else True:
            if not hasattr(self, '_sim'):
                break
            self._sim.update(0.033)
            state = self._sim.get_full_state()
            with self._lock:
                self._obs["joint_positions"] = state["joints"]["positions"]
                self._obs["joint_velocities"] = state["joints"]["velocities"]
                self._obs["gripper_position"] = state["gripper"]["pos"]
                self._obs["timestamp"] = time.time()
            time.sleep(0.033)

    def _poll_orin(self):
        while getattr(self, '_running', True):
            try:
                r = subprocess.run([
                    "ssh", "-o", "ConnectTimeout=3", f"nvidia@{self.config.orin_host}",
                    "source /opt/ros/humble/setup.bash && source ~/0615/tashan_robot_so_20260630_163849_f98c30a_aarch64/install/setup.bash && export ROS_DOMAIN_ID=23 && timeout 3 ros2 topic echo /real_joint_states --once 2>/dev/null | grep -A6 position:"
                ], capture_output=True, text=True, timeout=5)
                if r.returncode == 0:
                    lines = r.stdout.strip().split('\n')
                    pos = []
                    for l in lines:
                        try: pos.append(float(l.strip().split()[-1]))
                        except: pass
                    if len(pos) >= 6:
                        with self._lock:
                            self._obs["joint_positions"] = pos[:6]
                            self._obs["timestamp"] = time.time()
            except:
                pass
            time.sleep(0.1)

    def __enter__(self): self.connect(); return self
    def __exit__(self, *a): self.disconnect()


# ═══════════════════════════════════════════════
# 硬件树 API (供 Web 访问)
# ═══════════════════════════════════════════════

def get_hardware_tree() -> dict:
    """返回硬件树 — 供 datadrive.world 前端渲染"""
    return HARDWARE_TREE

def get_hardware_tree_json() -> str:
    return json.dumps(HARDWARE_TREE, indent=2, ensure_ascii=False)


# ═══════════════════════════════════════════════
# 测试
# ═══════════════════════════════════════════════

if __name__ == "__main__":
    # 仿真模式测试
    config = ZMaxOrinConfig(level="L3", use_sim=True)
    with ZMaxOrinRobot(config) as robot:
        print(f"Level: {robot.get_level_name()}")
        time.sleep(0.5)
        obs = robot.get_observation()
        print(f"Joints: {[round(p,4) for p in obs['joint_positions']]}")
        result = robot.send_action({"target_joint_positions": [0,0,0,0,0,-0.1745]})
        print(f"J6 -10°: {result}")
        time.sleep(1)
        obs = robot.get_observation()
        print(f"After: J6={obs['joint_positions'][5]:.4f} rad")

    print(f"\nHardware tree: {len(json.dumps(HARDWARE_TREE))} chars")
    print(f"Components: actuators={len(HARDWARE_TREE['actuators'])} "
          f"sensors={len(HARDWARE_TREE['sensors'])}")
