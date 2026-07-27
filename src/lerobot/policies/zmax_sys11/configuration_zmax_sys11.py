"""Z-MAX Phase 2 配置: Sys-11 Z潜空间泛化"""
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
        IDENTITY = "identity"; MEAN_STD = "mean_std"; MIN_MAX = "min_max"
    @dataclass
    class PreTrainedConfig:
        n_obs_steps: int = 1; chunk_size: int = 7; n_action_steps: int = 7
        normalization_mapping: dict = field(default_factory=dict)
        @classmethod
        def register_subclass(cls, name):
            def deco(c): return c
            return deco
        def __post_init__(self): pass


@PreTrainedConfig.register_subclass("zmax_sys11")
@dataclass
class ZmaxSys11Config(PreTrainedConfig):    
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
    """Phase 2: Z潜空间泛化 + 端侧部署"""
    smolvlm_name: str = "HuggingFaceTB/SmolVLM2-500M-Video-Instruct"
    freeze_smolvlm: bool = True
    siglip_image_size: int = 64
    num_vision_tokens: int = 64
    expert_width_multiplier: float = 0.5
    action_model_type: str = "DiT-B"
    action_hidden_size: int = 512
    action_num_layers: int = 2
    action_dropout: float = 0.2
    num_inference_timesteps: int = 4
    repeated_diffusion_steps: int = 4
    enable_tactile: bool = True
    tactile_dim: int = 6
    tactile_encoder_dim: int = 128
    # Phase 2 新增: Z潜空间
    latent_dim: int = 256
    latent_num_layers: int = 3
    latent_num_heads: int = 8
    latent_kl_weight: float = 0.01
    latent_quantization: bool = False
    # 端侧优化
    enable_fp16: bool = True
    enable_int8: bool = False
    target_inference_ms: float = 10.0
    enable_torch_compile: bool = True
    # 泛化
    num_module_types: int = 4
    module_type_embedding_dim: int = 64

    def __post_init__(self):
        if _HAS_LEROBOT: super().__post_init__()
        self.use_leworld_model = False
