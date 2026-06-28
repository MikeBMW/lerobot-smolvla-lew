# Copyright 2026 The HuggingFace Inc. team. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

from dataclasses import dataclass, field

from lerobot.configs.policies import PreTrainedConfig
from lerobot.configs.types import NormalizationMode
from lerobot.optim.optimizers import AdamWConfig
from lerobot.optim.schedulers import CosineDecayWithWarmupSchedulerConfig


# 1. 注册标识改为 smolvla_lew，类名全部替换
@PreTrainedConfig.register_subclass("smolvla_lew")
@dataclass
class SmolVLALewConfig(PreTrainedConfig):
    n_obs_steps: int = 1
    chunk_size: int = 7
    n_action_steps: int = 7

    normalization_mapping: dict[str, NormalizationMode] = field(
        default_factory=lambda: {
            "VISUAL": NormalizationMode.IDENTITY,
            "STATE": NormalizationMode.MEAN_STD,
            "ACTION": NormalizationMode.MIN_MAX,
        }
    )

    # ========== 移除全部Qwen、V-JEPA参数，替换为SmolVLM + LeWorldModel ==========
    # SmolVLM 轻量视觉语言主干配置（专家版新增参数）
    smolvlm_name: str = "HuggingFaceTB/SmolVLM2-500M-Video-Instruct"
    freeze_smolvlm: bool = True
    siglip_image_size: int = 64
    num_vision_tokens: int = 64
    # ===== 新增专家SmolVLMWithExpertModel配套参数 =====
    num_expert_layers: int = -1
    num_vlm_layers: int = -1
    self_attn_every_n_layers: int = -1
    expert_width_multiplier: float = 0.5

    # LeWorldModel 轻量世界模型开关与超参（替换原V-JEPA全套）
    enable_lew_world_model: bool = False
    lew_loss_weight: float = 0.1
    lew_hidden_dim: int = 192
    lew_num_layers: int = 6
    num_video_frames: int = 2  # LeWM仅需最少2帧 t/t+1

    # 移除Qwen专属token/prompt配置，SmolVLM原生不需要自定义action占位token
    # tokenizer_padding_side、prompt_template、special_action_token、embodied_action_token 全部删除

    # 任务维度（适配pusht自动覆盖）
    action_dim: int = 2
    state_dim: int = 2

    # DiT动作头参数 完全保留不变（复用action_head.py）
    num_action_tokens_per_timestep: int = 4
    num_embodied_action_tokens_per_instruction: int = 8
    num_inference_timesteps: int = 4

    action_hidden_size: int = 512
    action_model_type: str = "DiT-B"
    action_num_layers: int = 2
    action_num_heads: int | None = None
    action_attention_head_dim: int | None = None
    action_dropout: float = 0.2
    action_num_timestep_buckets: int = 1000
    action_noise_beta_alpha: float = 1.5
    action_noise_beta_beta: float = 1.0
    action_noise_s: float = 0.999
    num_target_vision_tokens: int = 16
    action_max_seq_len: int = 1024

    # 原V-JEPA专属参数全部删除：jepa_encoder_name、jepa_tubelet_size、predictor_depth等

    repeated_diffusion_steps: int = 4

    # 图像、夹爪后处理配置（和vla_jepa通用，保留）
    resize_images_to: tuple[int, int] | None = (64, 64)
    binarize_gripper_action: bool = True
    pre_snap_gripper_action: bool = True
    clip_normalized_actions: bool = True
    gripper_dim: int = 6
    gripper_threshold: float = 0.5
    torch_dtype: str = "float16"

    gradient_checkpointing: bool = True

    # 优化器、学习率调度器完全复用
    optimizer_lr: float = 1e-4
    optimizer_betas: tuple[float, float] = (0.9, 0.95)
    optimizer_eps: float = 1e-8
    optimizer_weight_decay: float = 1e-10
    optimizer_grad_clip_norm: float = 10.0
    scheduler_warmup_steps: int = 1_000
    scheduler_decay_steps: int = 30_000
    scheduler_decay_lr: float = 2.5e-6

    steps: int = 2

    def __post_init__(self) -> None:
        super().__post_init__()
        # 逻辑替换：原freeze_qwen + enable_world_model → freeze_smolvlm + enable_lew_world_model
        if self.freeze_smolvlm and self.enable_lew_world_model:
            self.enable_lew_world_model = False
        if self.n_action_steps > self.chunk_size:
            raise ValueError("`n_action_steps` must be <= `chunk_size`.")
        # LeWorldModel 最低帧数校验，替换原jepa tubelet判断
        if self.num_video_frames < 2:
            raise ValueError(
                f"`num_video_frames` ({self.num_video_frames}) must be >= 2 "
                f"to have context frame and target frame for LeWorldModel."
            )

    def validate_features(self) -> None:
        # 校验逻辑完全复用，自动从数据集覆盖action_dim/state_dim（适配pusht）
        if not self.image_features:
            raise ValueError("SmolVLALew requires at least one visual input feature.")
        if self.action_feature is None:
            raise ValueError("SmolVLALew requires an action output feature.")
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