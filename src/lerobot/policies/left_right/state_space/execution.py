"""execution.py — 执行层 · 物理闭环 (状态空间模型画布)

机器人执行器 (机械臂/夹爪) → 物理世界 → 传感器反馈 z_k → 卡尔曼校正闭环。

闭环 (对应画布连线):
  🤖执行器 → 🌍物理世界 → z_k 传感器反馈 → 🧪状态校正器 → 校正后潜状态 → 📈先验预测器

状态空间闭环:
  u (物理指令) → 执行器 → 世界 → z_k (观测) → 残差 → 校正 → 预测 → (下一拍)
"""
import numpy as np


class RobotExecutor:
    """🤖 机器人执行器 — 接收物理指令执行"""

    def __init__(self, n_joints=7):
        self.n_joints = n_joints  # 7 轴冗余臂 (Sawyer)

    def execute(self, u):
        """执行物理指令 → 返回执行结果 (关节/末端状态变化)"""
        return np.asarray(u, dtype=float)


class PhysicalWorld:
    """🌍 物理世界 — 执行结果 → 传感器反馈 z_k"""

    def __init__(self, noise=0.005, seed=42):
        self.noise = noise          # 传感器噪声 σ (卡尔曼校正的残差来源)
        self._rng = np.random.default_rng(seed)

    def observe(self, state):
        """返回传感器观测 z_k (带高斯噪声, 供卡尔曼校正)"""
        s = np.asarray(state, dtype=float)
        return s + self._rng.normal(0.0, self.noise, size=s.shape)
