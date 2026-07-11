#!/usr/bin/env python3
"""
Z-MAX Sys-0 基础安全模块

System 0 = 动作(标准接口) · 真实环境运行
在驱动机器人之前，必须加载此模块。

安全层级 (对齐 Q/ZFCY 001.1-2026):
  L1 硬件安全: 双路急停 + 安全光栅 (硬件IO)
  L2 传感器安全: 力/扭矩阈值 + 关节限位 + 速度限制
  L3 行为安全: 光幕联动降速 + 碰撞预判
  L4 主动安全: 力控预判 + 自诊断 (L4阶段)

部署: Orin nvidia-desktop
ROS2: Domain 23
"""
import time
import math
import json
import threading
import os
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Callable
from enum import Enum

# ═══════════════════════════════════════════════
# 安全状态定义
# ═══════════════════════════════════════════════

class SafetyLevel(Enum):
    """安全等级"""
    SAFE = "safe"           # 正常
    WARNING = "warning"     # 接近阈值
    CAUTION = "caution"     # 降速运行
    STOPPED = "stopped"     # 已停止
    ESTOP = "estop"         # 紧急停止
    FAULT = "fault"         # 故障


class TowerLight(Enum):
    """三色塔灯"""
    OFF = 0
    GREEN = 1    # 正常运行
    YELLOW = 2   # 警告/降速
    RED = 3      # 停止/故障


@dataclass
class SafetyConfig:
    """安全配置参数 (基于L2基线版硬件规格)"""

    # ── 力/扭矩阈值 ──
    force_limit_z_max: float = 5.0       # Z轴力上限 (N) — 光模块插入
    force_limit_z_min: float = -2.0      # Z轴力下限 (N) — 防止撞底
    force_limit_xy: float = 3.0          # X/Y轴力上限 (N)
    torque_limit: float = 0.5            # 扭矩上限 (Nm)

    # ── 关节限位 (XMS5-R800, 单位: rad) ──
    joint_limits: List[tuple] = field(default_factory=lambda: [
        (-2.0, 2.0),     # joint_1
        (-2.0, 2.0),     # joint_2
        (-3.0, 0.5),     # joint_3
        (-3.0, 3.0),     # joint_4
        (-2.0, 2.0),     # joint_5
        (-3.0, 3.0),     # joint_6
    ])
    joint_velocity_limit: float = 2.0    # rad/s
    joint_acceleration_limit: float = 5.0 # rad/s²

    # ── 夹爪安全 ──
    gripper_force_max: float = 50.0      # N — 最大夹持力
    gripper_force_min: float = 2.0       # N — 最小夹持力 (低于此值=脱开)
    gripper_open_min: float = 0.05       # 最小开度

    # ── 工作空间 ──
    workspace_x: tuple = (-0.8, 0.8)     # m
    workspace_y: tuple = (-0.8, 0.8)
    workspace_z: tuple = (0.0, 1.2)      # m (不允许低于桌面)
    workspace_radius: float = 0.8        # m — 球面工作半径

    # ── 响应时间 ──
    force_response_us: int = 100          # 力超阈值响应时间 (μs)
    estop_response_ms: int = 1            # 急停响应 (ms)
    slowdown_distance_m: float = 0.3      # 光幕预警距离 (m)

    # ── 重试 ──
    max_retry_count: int = 3             # 最大自动重试
    retry_backoff_s: float = 0.5         # 重试退避时间 (s)


# ═══════════════════════════════════════════════
# Sys-0 安全控制器
# ═══════════════════════════════════════════════

class Sys0SafetyController:
    """
    System 0 基础安全控制器

    在驱动机器人之前初始化:
        safety = Sys0SafetyController()
        safety.initialize()

    每次运动前检查:
        if safety.ok_to_move():
            robot.move(target)

    检测到危险:
        safety.emergency_stop("Force limit exceeded")
    """

    def __init__(self, config: SafetyConfig = None):
        self.config = config or SafetyConfig()

        # 状态
        self.level = SafetyLevel.SAFE
        self.tower = TowerLight.OFF
        self._lock = threading.Lock()

        # 传感器缓存
        self.joint_positions = [0.0] * 6
        self.joint_velocities = [0.0] * 6
        self.force_torque = {"fx": 0.0, "fy": 0.0, "fz": 0.0,
                             "tx": 0.0, "ty": 0.0, "tz": 0.0}
        self.gripper_state = {"pos": 0.0, "force": 0.0, "holding": False}
        self.estop_active = False
        self.light_curtain_triggered = False

        # 统计
        self.stats = {
            "safety_checks": 0,
            "warnings": 0,
            "estops": 0,
            "retries": 0,
            "last_check_time": 0.0,
            "uptime": 0.0,
        }

        # 回调
        self._on_estop: List[Callable] = []
        self._on_warning: List[Callable] = []
        self._on_recover: List[Callable] = []

        # 日志
        self.log_path = "/tmp/zmax_safety.log"

    # ═══════════════════════════════════════════
    # 初始化
    # ═══════════════════════════════════════════

    def initialize(self):
        """初始化安全系统 — 开机自检"""
        self._log("=== Sys-0 安全系统启动 ===")
        self._log(f"  力阈值: Fz={self.config.force_limit_z_max}N, "
                  f"Fxy={self.config.force_limit_xy}N")
        self._log(f"  关节限位: {len(self.config.joint_limits)}轴")
        self._log(f"  工作空间: {self.config.workspace_radius}m半径")
        self._log(f"  重试: {self.config.max_retry_count}次, "
                  f"退避={self.config.retry_backoff_s}s")

        self._set_tower(TowerLight.GREEN)
        self.stats["uptime"] = time.time()
        return True

    # ═══════════════════════════════════════════
    # 核心检查
    # ═══════════════════════════════════════════

    def ok_to_move(self, target_joints: List[float] = None,
                   target_gripper: float = None) -> bool:
        """
        运动前安全检查 — 所有检查通过才允许运动

        Returns:
            True = 安全, 可以运动
            False = 不安全, 运动被阻止
        """
        self.stats["safety_checks"] += 1
        self.stats["last_check_time"] = time.time()

        checks = []

        # L1: 硬件安全
        checks.append(("L1 急停", self._check_estop()))
        checks.append(("L1 光幕", self._check_light_curtain()))

        # L2: 传感器安全
        checks.append(("L2 力传感器", self._check_force_limits()))
        checks.append(("L2 关节限位", self._check_joint_limits(target_joints)))
        checks.append(("L2 速度限制", self._check_velocity_limits()))
        checks.append(("L2 工作空间", self._check_workspace(target_joints)))

        # L2: 夹爪安全
        if target_gripper is not None:
            checks.append(("L2 夹爪", self._check_gripper_safety(target_gripper)))

        # 汇总
        failed = [name for name, ok in checks if not ok]
        if failed:
            self._set_level(SafetyLevel.STOPPED)
            self._log(f"❌ 安全检查失败: {failed}")
            return False

        # L3: 光幕联动降速 (不影响运动, 但设置警告)
        if self.light_curtain_triggered:
            self._set_level(SafetyLevel.CAUTION)
            self._log("⚠️  光幕预警 — 降速运行")

        return True

    # ═══════════════════════════════════════════
    # L1 硬件安全检查
    # ═══════════════════════════════════════════

    def _check_estop(self) -> bool:
        """检查急停状态"""
        if self.estop_active:
            self._set_level(SafetyLevel.ESTOP)
            self._set_tower(TowerLight.RED)
            return False
        return True

    def _check_light_curtain(self) -> bool:
        """检查安全光幕"""
        if self.light_curtain_triggered:
            self._set_level(SafetyLevel.WARNING)
            self._set_tower(TowerLight.YELLOW)
            return False
        return True

    # ═══════════════════════════════════════════
    # L2 传感器安全检查
    # ═══════════════════════════════════════════

    def _check_force_limits(self) -> bool:
        """检查六维力传感器阈值 (TS-T-15, >10kHz)"""
        cfg = self.config
        ft = self.force_torque

        # Z轴力
        if ft["fz"] > cfg.force_limit_z_max:
            self._log(f"⛔ Z轴力超限: {ft['fz']:.1f} > {cfg.force_limit_z_max}N")
            return False
        if ft["fz"] < cfg.force_limit_z_min:
            self._log(f"⛔ Z轴力负超限 (撞底): {ft['fz']:.1f}N")
            return False

        # X/Y轴力
        f_xy = math.sqrt(ft["fx"]**2 + ft["fy"]**2)
        if f_xy > cfg.force_limit_xy:
            self._log(f"⛔ XY轴力超限: {f_xy:.1f} > {cfg.force_limit_xy}N")
            return False

        # 扭矩
        t_mag = math.sqrt(ft["tx"]**2 + ft["ty"]**2 + ft["tz"]**2)
        if t_mag > cfg.torque_limit:
            self._log(f"⛔ 扭矩超限: {t_mag:.2f} > {cfg.torque_limit}Nm")
            return False

        # 接近阈值 → 警告
        if ft["fz"] > cfg.force_limit_z_max * 0.8:
            self._set_level(SafetyLevel.WARNING)
            self._log(f"⚠️  Z轴力接近上限: {ft['fz']:.1f}N (80%)")

        return True

    def _check_joint_limits(self, target_joints: List[float] = None) -> bool:
        """检查关节位置限位"""
        positions = target_joints if target_joints else self.joint_positions
        if len(positions) < 6:
            return True  # 无数据时不阻塞

        for i, pos in enumerate(positions[:6]):
            lo, hi = self.config.joint_limits[i]
            if pos < lo or pos > hi:
                self._log(f"⛔ 关节{i+1}超限: {pos:.3f} ∉ [{lo:.1f}, {hi:.1f}]")
                return False

        return True

    def _check_velocity_limits(self) -> bool:
        """检查关节速度限制"""
        for i, vel in enumerate(self.joint_velocities[:6]):
            if abs(vel) > self.config.joint_velocity_limit:
                self._log(f"⛔ 关节{i+1}速度超限: {vel:.2f} rad/s")
                return False
        return True

    def _check_workspace(self, target_joints: List[float] = None) -> bool:
        """检查工作空间 (简化: 检查每个关节是否在运动范围内)"""
        # 完整工作空间检查需要正运动学 (FK)
        # 这里做基本关节限位检查, FK检查在L4阶段加入
        return self._check_joint_limits(target_joints)

    def _check_gripper_safety(self, target_pos: float) -> bool:
        """检查夹爪安全"""
        if target_pos < 0 or target_pos > 1:
            self._log(f"⛔ 夹爪指令无效: {target_pos:.2f}")
            return False
        if self.gripper_state["force"] > self.config.gripper_force_max:
            self._log(f"⛔ 夹持力超限: {self.gripper_state['force']:.1f}N")
            return False
        return True

    # ═══════════════════════════════════════════
    # 紧急操作
    # ═══════════════════════════════════════════

    def emergency_stop(self, reason: str = ""):
        """紧急停止"""
        with self._lock:
            self.estop_active = True
            self._set_level(SafetyLevel.ESTOP)
            self._set_tower(TowerLight.RED)
            self.stats["estops"] += 1
            self._log(f"🛑 紧急停止! {reason}")

            for cb in self._on_estop:
                try:
                    cb(reason)
                except Exception as e:
                    self._log(f"  estop回调失败: {e}")

    def reset_estop(self) -> bool:
        """重置急停 (需人工确认)"""
        if self.level == SafetyLevel.ESTOP:
            self._log("🔄 急停重置")
            self.estop_active = False
            self._set_level(SafetyLevel.SAFE)
            self._set_tower(TowerLight.GREEN)

            for cb in self._on_recover:
                try:
                    cb()
                except Exception:
                    pass
            return True
        return False

    def safe_retry(self, target_joints: List[float]) -> bool:
        """
        安全重试 — 检测到力异常后自动回退并重试
        最多重试 max_retry_count 次
        """
        for attempt in range(self.config.max_retry_count):
            self.stats["retries"] += 1
            self._log(f"🔄 自动重试 {attempt+1}/{self.config.max_retry_count}")

            # 回退
            time.sleep(self.config.retry_backoff_s)

            # 重新检查
            if self.ok_to_move(target_joints):
                self._log(f"✅ 重试{attempt+1}安全检查通过")
                return True

        self._log(f"❌ {self.config.max_retry_count}次重试均失败, 转入故障状态")
        self._set_level(SafetyLevel.FAULT)
        return False

    # ═══════════════════════════════════════════
    # 传感器更新
    # ═══════════════════════════════════════════

    def update_joints(self, positions: List[float],
                      velocities: List[float] = None):
        """更新关节状态 (来自 /robot/joint_states)"""
        self.joint_positions = positions
        if velocities:
            self.joint_velocities = velocities

    def update_force_torque(self, fx=0.0, fy=0.0, fz=0.0,
                            tx=0.0, ty=0.0, tz=0.0):
        """更新力传感器 (来自 /robot/force_torque)"""
        self.force_torque = {"fx": fx, "fy": fy, "fz": fz,
                             "tx": tx, "ty": ty, "tz": tz}

    def update_gripper(self, pos: float, force: float = 0.0,
                       holding: bool = False):
        """更新夹爪状态 (来自 /gripper_pos)"""
        self.gripper_state = {"pos": pos, "force": force, "holding": holding}

    def update_estop(self, active: bool):
        """更新急停信号 (来自 /emergency_stop)"""
        if active and not self.estop_active:
            self.emergency_stop("硬件急停触发")
        self.estop_active = active

    def update_light_curtain(self, triggered: bool):
        """更新光幕信号"""
        self.light_curtain_triggered = triggered
        if triggered:
            self._set_level(SafetyLevel.CAUTION)
            self._set_tower(TowerLight.YELLOW)

    # ═══════════════════════════════════════════
    # 状态管理
    # ═══════════════════════════════════════════

    def _set_level(self, level: SafetyLevel):
        self.level = level

    def _set_tower(self, light: TowerLight):
        self.tower = light
        # TODO: 发布到 /tower_light/command

    def _log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        try:
            with open(self.log_path, "a") as f:
                f.write(line + "\n")
        except Exception:
            pass

    # ═══════════════════════════════════════════
    # 回调注册
    # ═══════════════════════════════════════════

    def on_estop(self, callback: Callable):
        """注册急停回调"""
        self._on_estop.append(callback)

    def on_warning(self, callback: Callable):
        """注册警告回调"""
        self._on_warning.append(callback)

    def on_recover(self, callback: Callable):
        """注册恢复回调"""
        self._on_recover.append(callback)

    # ═══════════════════════════════════════════
    # 状态报告
    # ═══════════════════════════════════════════

    def get_status(self) -> dict:
        """获取安全状态报告"""
        return {
            "level": self.level.value,
            "tower_light": self.tower.name,
            "estop_active": self.estop_active,
            "light_curtain": self.light_curtain_triggered,
            "joint_positions": self.joint_positions,
            "force_torque": self.force_torque,
            "gripper": self.gripper_state,
            "stats": self.stats,
            "config": {
                "force_z_max": self.config.force_limit_z_max,
                "force_xy": self.config.force_limit_xy,
                "velocity_limit": self.config.joint_velocity_limit,
                "retry_count": self.config.max_retry_count,
            }
        }

    def print_status(self):
        """打印安全状态"""
        s = self.get_status()
        print(f"""
┌──────────────────────────────────────────┐
│  Sys-0 安全状态                           │
├──────────────────────────────────────────┤
│  等级:    {s['level']:12s}  塔灯: {s['tower_light']}
│  急停:    {'🔴 激活' if s['estop_active'] else '🟢 正常'}
│  光幕:    {'⚠️  触发' if s['light_curtain'] else '🟢 正常'}
│  力Z:     {s['force_torque']['fz']:.1f}N  (限:{s['config']['force_z_max']}N)
│  检查:    {s['stats']['safety_checks']}次
│  急停:    {s['stats']['estops']}次
│  重试:    {s['stats']['retries']}次
└──────────────────────────────────────────┘
""")


# ═══════════════════════════════════════════════
# ROS2 集成 (可选)
# ═══════════════════════════════════════════════

def create_sys0_ros2_node(safety: Sys0SafetyController):
    """
    创建 Sys-0 ROS2 安全监听节点
    订阅: /emergency_stop, /robot/force_torque, /robot/joint_states, /gripper_pos
    """
    try:
        import rclpy
        from rclpy.node import Node
        from sensor_msgs.msg import JointState
        from std_msgs.msg import Bool, Float32

        class Sys0SafetyNode(Node):
            def __init__(self):
                super().__init__("sys0_safety")
                self.safety = safety

                # 订阅
                self.create_subscription(
                    Bool, "/emergency_stop",
                    lambda msg: self.safety.update_estop(msg.data), 10)
                self.create_subscription(
                    JointState, "/robot/joint_states",
                    self._on_joint_state, 10)
                # TODO: 订阅力传感器和夹爪 (取决于实际话题名)

                self.get_logger().info("Sys-0 安全节点启动")

            def _on_joint_state(self, msg):
                self.safety.update_joints(
                    list(msg.position),
                    list(msg.velocity) if msg.velocity else None)

        return Sys0SafetyNode()
    except ImportError:
        print("[Sys-0] ROS2不可用, 运行在独立模式")
        return None


# ═══════════════════════════════════════════════
# 测试
# ═══════════════════════════════════════════════

if __name__ == "__main__":
    safety = Sys0SafetyController()
    safety.initialize()

    # 模拟正常状态
    safety.update_joints([0.1, -0.05, -2.5, 1.4, 0.4, -0.7])
    safety.update_force_torque(fz=2.0)
    safety.update_gripper(pos=0.5)

    print("=== 测试1: 正常运动 ===")
    print(f"ok_to_move: {safety.ok_to_move([0.1, 0, -2.5, 1.4, 0.4, -0.7])}")

    print("\n=== 测试2: 力超阈值 ===")
    safety.update_force_torque(fz=8.0)
    print(f"ok_to_move: {safety.ok_to_move()}")

    print("\n=== 测试3: 关节超限 ===")
    safety.update_force_torque(fz=2.0)
    print(f"ok_to_move: {safety.ok_to_move([5.0, 0, 0, 0, 0, 0])}")

    print("\n=== 测试4: 急停 ===")
    safety.update_estop(True)
    print(f"ok_to_move: {safety.ok_to_move()}")
    safety.reset_estop()
    print(f"重置后: {safety.ok_to_move()}")

    print("\n=== 测试5: 重试 ===")
    safety.update_force_torque(fz=8.0)
    result = safety.safe_retry([0.1, 0, -2.5, 1.4, 0.4, -0.7])
    print(f"safe_retry: {result} (level={safety.level.value})")

    safety.print_status()
    print(f"\n日志: {safety.log_path}")
