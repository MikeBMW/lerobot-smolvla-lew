"""Z-MAX Phase 3 配置: Sys-12 空间感知 + LeWorldModel"""
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


@PreTrainedConfig.register_subclass("zmax_sys12")
@dataclass
class ZmaxSys12Config(PreTrainedConfig):
    """Phase 3: VTLA + Z潜空间 + LeWorldModel"""
    n_obs_steps: int = 2
    smolvlm_name: str = "HuggingFaceTB/SmolVLM2-500M-Video-Instruct"
    freeze_smolvlm: bool = False
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
    # Z潜空间
    latent_dim: int = 256
    latent_num_layers: int = 3
    latent_kl_weight: float = 0.01
    num_module_types: int = 4
    module_type_embedding_dim: int = 64
    # Phase 3: LeWorldModel
    enable_leworld_model: bool = True
    lew_loss_weight: float = 0.1
    lew_hidden_dim: int = 192
    lew_num_layers: int = 6
    lew_attention_heads: int = 8
    lew_dim_head: int = 24
    lew_mlp_dim: int = 768
    lew_dropout: float = 0.1
    num_video_frames: int = 4
    # 3D空间
    spatial_resolution: int = 16
    enable_depth: bool = True
    depth_dim: int = 32
    scene_feature_dim: int = 512
    target_pose_dim: int = 6
    guidance_strength: float = 0.5

    def __post_init__(self):
        if _HAS_LEROBOT: super().__post_init__()
        self.use_leworld_model = True
