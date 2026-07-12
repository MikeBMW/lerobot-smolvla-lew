"""Z-MAX Sys2 配置: 云端大模型 (VTLA + GR00T N1.7)

Sys2 运行在 4090 上，为 Sys1(4060) 提供大模型推理服务。
Sys1 ACT 模板可通过 gRPC/HTTP 调用 Sys2 的 VTLA 和 GR00T 模型。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum

try:
    from lerobot.configs.policies import PreTrainedConfig
    from lerobot.configs.types import NormalizationMode
    _HAS_LEROBOT = True
except ImportError:
    _HAS_LEROBOT = False
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


class Sys2ModelType(str, Enum):
    """Sys2 支持的模型类型"""
    VTLA = "vtla"       # Vision-Touch-Language-Action (触觉VLA)
    GROOT = "groot"     # NVIDIA GR00T N1.7 (通用人形机器人)
    ACT = "act"         # ACT fallback
    AUTO = "auto"       # 自动选择


class SubSystemMode(str, Enum):
    SYS1 = "sys1"; SYS11 = "sys11"; SYS12 = "sys12"


@PreTrainedConfig.register_subclass("zmax_sys2")
@dataclass
class ZmaxSys2Config(PreTrainedConfig):
    """Z-MAX Sys2 云端大模型配置

    Sys2 是大模型推理层，运行在 4090 上：
    - VTLA: 融合触觉的视觉-语言-动作模型 (~450M)
    - GR00T: NVIDIA GR00T N1.7 通用机器人基础模型 (~7B)
    - ACT: 轻量级动作分块 Transformer (~52M, fallback)
    """

    # ═══ 模型路径 ═══
    vtla_model_path: str = ""
    """VTLA 模型检查点路径 (如 lerobot/smolvla_base 或本地路径)"""

    groot_model_path: str = ""
    """GR00T N1.7 模型检查点路径 (HuggingFace 或本地路径)"""

    groot_embodiment_tag: str = "new_embodiment"
    """GR00T 具身标签 (OXE_DROID, UNITREE_G1, SIMPLER_ENV_WIDOWX 等)"""

    act_model_path: str = "lerobot/act_aloha_sim_transfer_cube_human"
    """ACT fallback 模型路径"""

    # ═══ 推理配置 ═══
    default_model: str = "auto"
    """默认模型: vtla, groot, act, auto"""

    max_batch_size: int = 4
    """最大批处理大小"""

    use_bfloat16: bool = True
    """使用 bfloat16 推理 (GR00T 要求 bf16)"""

    timeout_seconds: float = 30.0
    """单次推理超时 (秒)"""

    # ═══ gRPC 服务配置 ═══
    grpc_host: str = "0.0.0.0"
    grpc_port: int = 50052
    """Sys2 gRPC 服务端口 (不同于 Sys1 的 50051)"""

    http_host: str = "0.0.0.0"
    http_port: int = 8080
    """Sys2 REST API 端口 (可选, 便于调试)"""

    enable_grpc: bool = True
    enable_http: bool = True

    # ═══ 触觉模态配置 ═══
    enable_tactile: bool = True
    tactile_dim: int = 16
    """触觉传感器维度 (16点阵)"""

    force_torque_dim: int = 6
    """力/力矩维度"""

    # ═══ VTLA 模型架构参数 ═══
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

    # ═══ GA-Z空间 ═══
    latent_dim: int = 256
    latent_num_layers: int = 3
    latent_kl_weight: float = 0.01
    num_module_types: int = 4
    module_type_embedding_dim: int = 64

    # ═══ LeWorldModel (从Sys12继承) ═══
    enable_leworld_model: bool = True
    lew_loss_weight: float = 0.1
    lew_hidden_dim: int = 192
    lew_num_layers: int = 6
    lew_attention_heads: int = 8
    lew_dim_head: int = 24
    lew_mlp_dim: int = 768
    lew_dropout: float = 0.1
    num_video_frames: int = 4
    spatial_resolution: int = 16
    depth_dim: int = 32
    scene_feature_dim: int = 512
    target_pose_dim: int = 6
    guidance_strength: float = 0.5

    # ═══ 任务规划器 ═══
    planner_hidden_dim: int = 512
    planner_num_layers: int = 4
    planner_num_heads: int = 8
    max_task_steps: int = 16
    task_embedding_dim: int = 256

    # ═══ 多产线调度 ═══
    default_subsystem: str = "sys12"
    enable_auto_routing: bool = True
    routing_threshold: float = 0.7
    max_concurrent_lines: int = 8
    line_status_dim: int = 128
    enable_5g_comm: bool = True
    comm_latency_budget_ms: float = 50.0

    # ═══ 自评估 ═══
    enable_self_eval: bool = True
    eval_interval_steps: int = 100
    success_threshold: float = 0.95

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

    def __post_init__(self):
        if _HAS_LEROBOT:
            super().__post_init__()
        self.use_leworld_model = True
