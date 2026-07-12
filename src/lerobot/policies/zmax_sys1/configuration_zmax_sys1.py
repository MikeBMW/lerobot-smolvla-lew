"""Z-MAX Phase 1 配置: System 1 VTLA基础功能"""
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


@PreTrainedConfig.register_subclass("zmax_sys1")
@dataclass
class ZmaxSys1Config(PreTrainedConfig):    
    # ━━━ 抽象方法实现 ━━━
    def validate_features(self): pass
    def get_optimizer_preset(self): return {}
    def get_scheduler_preset(self): return {}
    
    @property
    def observation_delta_indices(self): return []
    @property
    def action_delta_indices(self): return []
    @property
    def reward_delta_indices(self): return []
    """Phase 1: VTLA 基础插拔策略"""
    # 引擎选择
    engine: str = "act"   # act | vtla | groot | smolvla | lew
    grpc_host: str = "106.75.239.80"
    grpc_port: int = 50051
    # VLM
    smolvlm_name: str = "HuggingFaceTB/SmolVLM2-500M-Video-Instruct"
    freeze_smolvlm: bool = True
    siglip_image_size: int = 64
    num_vision_tokens: int = 64
    num_expert_layers: int = -1
    expert_width_multiplier: float = 0.5
    # DiT-B Action Head
    action_model_type: str = "DiT-B"
    action_hidden_size: int = 512
    action_num_layers: int = 2
    action_dropout: float = 0.2
    num_inference_timesteps: int = 4
    repeated_diffusion_steps: int = 4
    # Phase 1 触觉
    enable_tactile: bool = True
    tactile_dim: int = 6
    tactile_encoder_dim: int = 128
    # 插拔专用
    max_insertion_force: float = 5.0
    alignment_tolerance: float = 0.02

    def __post_init__(self):
        if _HAS_LEROBOT:
            super().__post_init__()
        self.use_leworld_model = False
