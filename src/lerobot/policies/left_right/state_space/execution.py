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

    # 🧮 2026-08-18 老倪: 硬件属性 (Z700 光模块工厂机械臂 — 画布节点展示用)
    #   质量/惯量/自由度 = 真机规格 (VLA 触觉 58D 工程对应 Z700F); 仿真参数 = 引擎常量
    HARDWARE_SPEC = {
        "自由度": "7 (6×旋转关节 J1–J6 + 夹爪开合)",
        "关节配置": "J1–J6 旋转关节 (±170°~±360°) + 末端电动两指夹爪",
        "整机质量": "24.5 kg (Z700 臂), 末端执行器 1.2 kg",
        "额定负载": "3 kg (抓取光模块 0.15 kg ≪ 额定)",
        "末端惯量": "0.08 kg·m² (负载 0.15kg @ 0.3m 臂展)",
        "重复定位精度": "±0.02 mm (光模块插拔需求 ≤0.1mm)",
        "工作半径": "0.8 m",
        "夹爪行程": "0–35 mm, 最大夹持力 12 N",
        "力觉": "6D 力/力矩传感器 (z 向推力 0.03–12 N 分辨率 0.01N)",
        "触觉": "4D 触觉 (夹爪开度/接触 0-1 开关量)",
        "视觉": "RGB-D (Orin 侧 39D 观测: 位置/夹爪/速度/peg/孔位/姿态)",
        "接触刚度": "6.0 N/m (仿真参数)",
        "接触半径": "0.02 m (peg 半径, 仿真参数)",
        "插入深度阈值": "0.004 m (仿真参数, 插入完成判定)",
        "传感器噪声 σ": "0.005 (仿真参数, 卡尔曼校正残差来源)",
    }

    def __init__(self, noise=0.005, seed=42):
        self.noise = noise          # 传感器噪声 σ (卡尔曼校正的残差来源)
        self._rng = np.random.default_rng(seed)

    @property
    def hardware(self):
        """硬件属性 dict (质量/惯量/自由度等) — 画布节点展示"""
        return dict(self.HARDWARE_SPEC)

    def observe(self, state):
        """返回传感器观测 z_k (带高斯噪声, 供卡尔曼校正)"""
        s = np.asarray(state, dtype=float)
        return s + self._rng.normal(0.0, self.noise, size=s.shape)
