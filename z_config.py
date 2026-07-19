"""z_config.py — H-JEPA z流架构配置"""
from dataclasses import dataclass, field
from typing import List

@dataclass
class ZFlowConfig:
    # 三层 z 维度
    z_dims: List[int] = field(default_factory=lambda: [256, 256, 128])  # z1(空间) z2(物体) z3(语义)
    # VLA 维度
    vla_dim: int = 256
    h_dim: int = 512  # 隐藏层
    # 动作
    act_dim: int = 7   # 6关节+1夹爪
    chunk: int = 14     # 预测14步
    # 训练
    lr: float = 1e-4
    batch_size: int = 8
    epochs: int = 300
    energy_margin: float = 1.0
    # 门控
    gate_init: float = -3.0
    # 数据
    data_dir: str = "/root/datasets"
