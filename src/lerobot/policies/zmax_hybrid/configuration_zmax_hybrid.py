# Copyright 2026 The HuggingFace Inc. team. All rights reserved.
"""Z-MAX Hybrid · 逐层交叉反馈融合架构配置

架构: SmolVLA × LeWM 分布式混合模型
      VLA 3层 + 每层Cross-Attention注入世界模型潜空间Z
      训练时三层门控激活, 推理时世界模型剥离
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lerobot.configs.policies import PreTrainedConfig
from lerobot.configs.types import NormalizationMode
from lerobot.optim.optimizers import AdamWConfig
from lerobot.optim.schedulers import CosineDecayWithWarmupSchedulerConfig


@PreTrainedConfig.register_subclass("zmax_hybrid")
@dataclass
class ZmaxHybridConfig(PreTrainedConfig):
    """Z-MAX Hybrid 策略配置

    架构模式:
      - 训练: VLA 3层 + WM GRU + 逐层Cross-Attention + H-JEPA能量损失
      - 推理: 纯VLA+DiT, WM剥离, gate归零, 零额外开销
    """

    # ━━━ 基础配置 ━━━
    n_obs_steps: int = 1
    chunk_size: int = 7
    n_action_steps: int = 7

    normalization_mapping: dict[str, NormalizationMode] = field(
        default_factory=lambda: {
            "VISUAL": NormalizationMode.IDENTITY,
            "STATE": NormalizationMode.MEAN_STD,
            "ACTION": NormalizationMode.MEAN_STD,
        }
    )

    # ━━━ VLA 骨干 ━━━
    smolvlm_name: str = "HuggingFaceTB/SmolVLM2-500M-Video-Instruct"
    freeze_smolvlm: bool = True
    siglip_image_size: int = 64
    num_vision_tokens: int = 64
    vlm_hidden_size: int = 960

    # 预训练VLA路径 (加速收敛)
    pretrained_vla_path: str | None = None

    # ━━━ 混合层配置 ━━━
    num_hybrid_layers: int = 3                 # VLA混合层数
    hybrid_hidden_size: int = 512               # 混合层隐藏维度
    hybrid_num_heads: int = 8                   # 注意力头数
    hybrid_head_dim: int = 64                   # 每头维度
    hybrid_ffn_multiplier: float = 4.0          # FFN扩展倍数
    hybrid_dropout: float = 0.1

    # 门控系数 (gate₁=1.0, gate₂=0.1, gate₃=0.01)
    hybrid_gates: tuple[float, ...] = (1.0, 0.1, 0.01)

    # ━━━ 世界模型 (LeWM) ━━━
    enable_world_model: bool = True             # 训练时启用
    enable_wm_inference: bool = False           # 推理时是否保留世界模型 (自回归, 更慢但可能更准)
    wm_hidden_dim: int = 256                    # GRU隐藏维度
    wm_num_layers: int = 2                      # GRU层数
    wm_latent_dims: tuple[int, ...] = (256, 256, 128)  # z₁空间/z₂物体/z₃语义维度
    wm_energy_loss_weight: float = 0.1          # H-JEPA能量损失权重
    num_video_frames: int = 2                   # 视频帧数 (t和t+1)

    # ━━━ 动作头 (DiT) ━━━
    action_model_type: str = "DiT-B"
    action_hidden_size: int = 512
    action_num_layers: int = 2
    action_num_heads: int | None = None
    action_attention_head_dim: int | None = None
    action_dropout: float = 0.2
    action_num_timestep_buckets: int = 1000
    action_noise_beta_alpha: float = 1.5
    action_noise_beta_beta: float = 1.0
    action_noise_s: float = 0.999
    num_inference_timesteps: int = 4
    repeated_diffusion_steps: int = 4
    num_action_tokens_per_timestep: int = 4
    num_embodied_action_tokens_per_instruction: int = 8

    # ━━━ 预处理 ━━━
    resize_images_to: tuple[int, int] | None = (64, 64)
    binarize_gripper_action: bool = True
    pre_snap_gripper_action: bool = True
    clip_normalized_actions: bool = True
    gripper_dim: int = 6
    gripper_threshold: float = 0.5
    torch_dtype: str = "float16"

    # ━━━ 优化器 ━━━
    gradient_checkpointing: bool = True
    optimizer_lr: float = 1e-4
    optimizer_betas: tuple[float, float] = (0.9, 0.95)
    optimizer_eps: float = 1e-8
    optimizer_weight_decay: float = 1e-10
    optimizer_grad_clip_norm: float = 10.0
    scheduler_warmup_steps: int = 1_000
    scheduler_decay_steps: int = 30_000
    scheduler_decay_lr: float = 2.5e-6

    action_dim: int = 2
    state_dim: int = 2

    def __post_init__(self) -> None:
        super().__post_init__()
        assert len(self.hybrid_gates) == self.num_hybrid_layers, (
            f"hybrid_gates length ({len(self.hybrid_gates)}) must match "
            f"num_hybrid_layers ({self.num_hybrid_layers})"
        )
        assert len(self.wm_latent_dims) == self.num_hybrid_layers, (
            f"wm_latent_dims length ({len(self.wm_latent_dims)}) must match "
            f"num_hybrid_layers ({self.num_hybrid_layers})"
        )
        if self.n_action_steps > self.chunk_size:
            raise ValueError("n_action_steps must be <= chunk_size")

    def validate_features(self) -> None:
        if not self.image_features:
            raise ValueError("ZmaxHybrid requires at least one visual input feature.")
        if self.action_feature is None:
            raise ValueError("ZmaxHybrid requires an action output feature.")
        self.action_dim = self.action_feature.shape[0]
        if self.robot_state_feature is not None:
            self.state_dim = self.robot_state_feature.shape[0]

    def get_optimizer_preset(self) -> AdamWConfig:
        return AdamWConfig(
            lr=self.optimizer_lr,
            betas=self.optimizer_betas,
            eps=self.optimizer_eps,
            weight_decay=self.optimizer_weight_decay,
            grad_clip_norm=self.optimizer_grad_clip_norm,
        )

    def get_scheduler_preset(self) -> CosineDecayWithWarmupSchedulerConfig:
        return CosineDecayWithWarmupSchedulerConfig(
            peak_lr=self.optimizer_lr,
            decay_lr=self.scheduler_decay_lr,
            num_warmup_steps=self.scheduler_warmup_steps,
            num_decay_steps=self.scheduler_decay_steps,
        )

    @property
    def observation_delta_indices(self) -> list[int]:
        return list(range(self.num_video_frames))

    @property
    def action_delta_indices(self) -> list[int]:
        return list(range(self.chunk_size))

    @property
    def reward_delta_indices(self) -> None:
        return None
