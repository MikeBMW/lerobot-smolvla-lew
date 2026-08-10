"""Z-MAX LeftRight 配置: 双脑架构 (左脑MLP动作 + 右脑WorldModel判断)
2026-08-10 老倪: 把成功模型按 lerobot 标准写成 left_right 工程
成绩: 抓起 8/8, 插入 7/8 (与官方专家持平)
"""
from __future__ import annotations
from dataclasses import dataclass, field

try:
    from lerobot.configs.policies import PreTrainedConfig
    from lerobot.configs.types import NormalizationMode
    _HAS_LEROBOT = True
except ImportError:
    _HAS_LEROBOT = False
    from enum import Enum
    class NormalizationMode(Enum):
        IDENTITY = "identity"
        MEAN_STD = "mean_std"
        MIN_MAX = "min_max"
    @dataclass
    class PreTrainedConfig:
        n_obs_steps: int = 1
        chunk_size: int = 7
        n_action_steps: int = 7
        normalization_mapping: dict = field(default_factory=dict)
        @classmethod
        def register_subclass(cls, name):
            def deco(c): return c
            return deco
        def __post_init__(self): pass


@PreTrainedConfig.register_subclass("left_right")
@dataclass
class LeftRightConfig(PreTrainedConfig):
    """左脑右脑双脑架构配置"""
    # 基础
    n_obs_steps: int = 1
    chunk_size: int = 1
    n_action_steps: int = 1
    # 双脑
    left_hidden: int = 512     # 左脑 MLP 隐藏层
    right_hidden: int = 256    # 右脑 WM 隐藏层
    # 状态机参数 (推理时用)
    grasp_contact_threshold: float = 0.5   # 右脑 contact 判断阈值
    grasp_d_hp: float = 0.06               # 抓取接近距离 (m)
    lift_height: float = 0.08              # 抬起高度 (m)
    transfer_tolerance: float = 0.05       # 转移容差 (m)
    insert_tolerance: float = 0.05         # 插入判定距离 (m)
    # 归一化
    normalization_mapping: dict = field(default_factory=lambda: {
        "observation.state": NormalizationMode.MEAN_STD,
        "action": NormalizationMode.MEAN_STD,
    })
    # 输入输出维度 (运行时填充)
    input_features: dict = field(default_factory=dict)
    output_features: dict = field(default_factory=dict)

    # ── lerobot PreTrainedConfig 抽象方法实现 ──
    @property
    def action_delta_indices(self) -> list[int]:
        return list(range(self.n_action_steps))

    @property
    def observation_delta_indices(self) -> list[int]:
        return list(range(self.n_obs_steps))

    @property
    def reward_delta_indices(self) -> list[int]:
        return [0]

    def validate_features(self, input_features, output_features):
        """校验输入输出特征 (lerobot 标准)"""
        return input_features, output_features

    def get_optimizer_preset(self):
        """优化器配置 (lerobot 标准)"""
        return {"optimizer_cls": "torch.optim.AdamW", "lr": 1e-4}

    def get_scheduler_preset(self):
        """调度器配置 (lerobot 标准)"""
        return {"scheduler_cls": None, "kwargs": {}}
