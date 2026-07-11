"""
Z-MAX 硬件树定义

映射Z700/Z700F机器人的所有传感器、执行器、控制器
对应Orin ROS2 Topic → LeRobot Robot接口

层级结构:
  robot
  ├── controllers (域控制器)
  │   ├── orin (Jetson AGX/Nano)
  │   └── mcu (TC397)
  ├── arms (机械臂)
  │   ├── left (左臂: 取料)
  │   └── right (右臂: 插拔)
  ├── sensors (传感器)
  │   ├── cameras (3D深度 + 腕部RGB)
  │   ├── force_torque (六维力)
  │   ├── tactile (触觉阵列)
  │   ├── imu (惯性测量)
  │   └── io (数字/模拟IO)
  └── actuators (执行器)
      ├── gripper (夹爪)
      └── conveyor (传送带)
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class ZmaxLevel(Enum):
    L2 = "L2"       # 基线版: 纯规则
    L3 = "L3"       # 增强版: ACT引擎
    L4 = "L4"       # 旗舰版: SmolVLA+世界模型


@dataclass
class HwNode:
    """硬件树节点"""
    id: str
    name: str
    type: str                          # controller/arm/sensor/actuator
    level: ZmaxLevel = ZmaxLevel.L2    # 最低支持等级
    ros_topic: Optional[str] = None    # 对应Orin ROS2 Topic
    ros_type: Optional[str] = None     # ROS消息类型
    frequency: Optional[float] = None  # 发布频率(Hz)
    unit: Optional[str] = None         # 数据单位
    range: Optional[str] = None        # 量程
    children: list[HwNode] = field(default_factory=list)
    specs: dict = field(default_factory=dict)


# ═══════════════════════════════════════════
# Z-MAX 硬件树完整定义
# ═══════════════════════════════════════════

ZMAX_HARDWARE_TREE = HwNode(
    id="zmax",
    name="Z-MAX",
    type="robot",
    level=ZmaxLevel.L2,
    children=[
        # ━━━ 域控制器 ━━━
        HwNode(id="orin", name="Jetson Orin", type="controller", level=ZmaxLevel.L2,
               ros_topic="/diagnostics",
               specs={"orin_nano": {"ram":"8GB","tensor":"40TOPS","cpu":"6-core"},
                      "orin_agx": {"ram":"32GB","tensor":"275TOPS","cpu":"12-core"}},
               children=[
                   HwNode(id="mcu", name="TC397 MCU", type="controller", level=ZmaxLevel.L2,
                          ros_topic="/mcu/status", frequency=10,
                          specs={"cores":"6 TriCore @300MHz","dma":"4000 DMIPS","safety":"ASIL-D"}),
               ]),
        
        # ━━━ 左臂 (取料) ━━━
        HwNode(id="left_arm", name="左臂(取料)", type="arm", level=ZmaxLevel.L2,
               ros_topic="/left_arm/joint_states", ros_type="sensor_msgs/JointState", frequency=100,
               children=[
                   HwNode(id="l_j1", name="基座", type="joint", level=ZmaxLevel.L2, unit="rad", range="±180°"),
                   HwNode(id="l_j2", name="肩部", type="joint", level=ZmaxLevel.L2, unit="rad", range="±130°"),
                   HwNode(id="l_j3", name="肘部", type="joint", level=ZmaxLevel.L2, unit="rad", range="±150°"),
                   HwNode(id="l_j4", name="腕1(翻转)", type="joint", level=ZmaxLevel.L2, unit="rad", range="±180°"),
                   HwNode(id="l_j5", name="腕2(俯仰)", type="joint", level=ZmaxLevel.L2, unit="rad", range="±120°"),
                   HwNode(id="l_j6", name="腕3(旋转)", type="joint", level=ZmaxLevel.L2, unit="rad", range="±360°"),
                   HwNode(id="l_gripper", name="吸盘夹爪", type="actuator", level=ZmaxLevel.L2,
                          ros_topic="/left_gripper/state", frequency=50, unit="0-255", range="开合度"),
               ]),
        
        # ━━━ 右臂 (插拔) ━━━
        HwNode(id="right_arm", name="右臂(插拔)", type="arm", level=ZmaxLevel.L2,
               ros_topic="/right_arm/joint_states", ros_type="sensor_msgs/JointState", frequency=100,
               children=[
                   HwNode(id="r_j1", name="基座", type="joint", level=ZmaxLevel.L2, unit="rad"),
                   HwNode(id="r_j2", name="肩部", type="joint", level=ZmaxLevel.L2, unit="rad"),
                   HwNode(id="r_j3", name="肘部", type="joint", level=ZmaxLevel.L2, unit="rad"),
                   HwNode(id="r_j4", name="腕1", type="joint", level=ZmaxLevel.L2, unit="rad"),
                   HwNode(id="r_j5", name="腕2", type="joint", level=ZmaxLevel.L2, unit="rad"),
                   HwNode(id="r_j6", name="腕3", type="joint", level=ZmaxLevel.L2, unit="rad"),
                   HwNode(id="r_gripper", name="精密夹爪", type="actuator", level=ZmaxLevel.L2,
                          ros_topic="/right_gripper/state", frequency=50, unit="0-255"),
               ]),
        
        # ━━━ 传感器组 ━━━
        HwNode(id="sensors", name="传感器组", type="sensor", level=ZmaxLevel.L2, children=[
            # 相机
            HwNode(id="realsense", name="Realsense D435i", type="sensor", level=ZmaxLevel.L2,
                   ros_topic="/camera/color/image_raw", frequency=30,
                   specs={"resolution":"640x480","fov":"87°×58°","depth":"0.3-10m"}),
            HwNode(id="wrist_cam_l", name="腕部RGB(左)", type="sensor", level=ZmaxLevel.L3,
                   ros_topic="/left_wrist/camera", frequency=30),
            HwNode(id="wrist_cam_r", name="腕部RGB(右)", type="sensor", level=ZmaxLevel.L3,
                   ros_topic="/right_wrist/camera", frequency=30),
            # 力/力矩
            HwNode(id="ft_sensor", name="六维力/力矩", type="sensor", level=ZmaxLevel.L3,
                   ros_topic="/force_torque", frequency=1000, unit="N/Nm",
                   specs={"fx_fy":"±500N","fz":"±700N","t_xy":"±18Nm","tz":"±18Nm","精度":"0.1%F.S."}),
            # 触觉
            HwNode(id="tactile", name="触觉传感器", type="sensor", level=ZmaxLevel.L3,
                   ros_topic="/tactile/array", frequency=200, unit="N",
                   specs={"精度":"0.1N","量程":"0.01-20N","尺寸":"10.6×14.4mm"}),
            # IMU
            HwNode(id="imu", name="IMU", type="sensor", level=ZmaxLevel.L3,
                   ros_topic="/imu/data", frequency=200,
                   specs={"gyro":"±500°/s","accel":"±16g","bias":"1.2°/h"}),
            # IO
            HwNode(id="io", name="数字IO", type="sensor", level=ZmaxLevel.L2,
                   ros_topic="/io/status", frequency=10,
                   specs={"di":"8路","do":"8路","ai":"4路(0-10V)"}),
        ]),
        
        # ━━━ L4专属 ━━━
        HwNode(id="l4_sensors", name="L4扩展传感器", type="sensor", level=ZmaxLevel.L4, children=[
            HwNode(id="depth_cam", name="3D深度相机", type="sensor", level=ZmaxLevel.L4,
                   ros_topic="/camera/depth/image_raw", frequency=15),
            HwNode(id="thermal", name="热成像", type="sensor", level=ZmaxLevel.L4,
                   ros_topic="/thermal/image", frequency=5),
            HwNode(id="lidar", name="激光雷达", type="sensor", level=ZmaxLevel.L4,
                   ros_topic="/scan", frequency=10, specs={"range":"0.1-25m","fov":"270°"}),
        ]),
        
        # ━━━ 执行器 ━━━
        HwNode(id="conveyor", name="传送带", type="actuator", level=ZmaxLevel.L2,
               ros_topic="/conveyor/control", frequency=10),
        HwNode(id="tower_light", name="三色塔灯", type="actuator", level=ZmaxLevel.L2,
               ros_topic="/tower_light/state", frequency=1),
        HwNode(id="safety_curtain", name="光幕", type="actuator", level=ZmaxLevel.L2,
               ros_topic="/safety/curtain", frequency=50),
    ]
)

# ━━━ 扁平化工具 ━━━

def flatten_tree(node: HwNode, parent_id: str = "") -> list[dict]:
    """将硬件树展平为列表"""
    result = []
    full_id = f"{parent_id}/{node.id}" if parent_id else node.id
    item = {
        "id": node.id, "full_id": full_id, "name": node.name,
        "type": node.type, "level": node.level.value,
        "ros_topic": node.ros_topic, "ros_type": node.ros_type,
        "frequency": node.frequency, "unit": node.unit,
        "range": node.range, "specs": node.specs,
        "children": len(node.children)
    }
    result.append(item)
    for child in node.children:
        result.extend(flatten_tree(child, full_id))
    return result

def get_by_level(level: ZmaxLevel) -> list[dict]:
    """获取指定等级的所有硬件节点"""
    return [n for n in flatten_tree(ZMAX_HARDWARE_TREE) 
            if ZmaxLevel(n["level"]) in [ZmaxLevel.L2, level] or ZmaxLevel(n["level"]) == level]

def to_json(node: HwNode = None) -> str:
    """硬件树→JSON"""
    import json
    if node is None:
        node = ZMAX_HARDWARE_TREE
    return json.dumps(flatten_tree(node), ensure_ascii=False, indent=2)
