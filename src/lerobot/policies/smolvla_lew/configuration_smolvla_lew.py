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
    """
    SmolVLA-LEW 策略配置
    
    两种架构模式（由 GUI 配置中心控制）:
    - Sys-11 纯动作系统 (smolvla): 仅使用 DiT-B action head
    - Sys-11+Sys-12 混合架构 (smolvla_lew): VLA + LeWorldModel 世界模型
    
    用户可修改参数均已标记 [可配置]
    """
    
    # ========== 基础配置 (Sys-11 + Sys-12 共用) ==========
    n_obs_steps: int = 1                                    # [可配置] 观测帧数
    chunk_size: int = 7                                     # [可配置] 动作预测序列长度
    n_action_steps: int = 7                                 # [可配置] 实际执行动作步数

    normalization_mapping: dict[str, NormalizationMode] = field(
        default_factory=lambda: {
            "VISUAL": NormalizationMode.IDENTITY,
            "STATE": NormalizationMode.MEAN_STD,
            "ACTION": NormalizationMode.MIN_MAX,
        }
    )

    # ========== Sys-11 共性参数: SmolVLM 骨干网络 ==========
    # 所有模式共用 (Sys-11 纯动作 / Sys-11+Sys-12 混合)
    smolvlm_name: str = "HuggingFaceTB/SmolVLM2-500M-Video-Instruct"  # [可配置] HuggingFace 模型ID
    freeze_smolvlm: bool = True                             # [可配置] 是否冻结 VLM 主干（Sys-11 纯动作必须 True；Sys-11+Sys-12 混合必须 False）
    siglip_image_size: int = 64                             # [可配置] SigLIP 输入图像尺寸
    num_vision_tokens: int = 64                             # [可配置] 视觉 token 数量
    
    # ===== SmolVLMWithExpertModel 专家配置 =====
    num_expert_layers: int = -1                             # [可配置] 专家层数 (-1 = 自动)
    num_vlm_layers: int = -1                                # [可配置] VLM 层数 (-1 = 自动)
    self_attn_every_n_layers: int = -1                      # [可配置] 自注意力频率 (-1 = 自动)
    expert_width_multiplier: float = 0.5                    # [可配置] 专家宽度倍率 (0.3-0.8)

    # ========== Sys-11 参数: DiT-B Flow-Matching Action Head ==========
    # 所有模式共用
    action_model_type: str = "DiT-B"                        # [可配置] 动作模型类型: "DiT-B" / "DiT-L" / "DiT-test"
    action_hidden_size: int = 512                           # [可配置] DiT 隐藏层维度
    action_num_layers: int = 2                              # [可配置] DiT 层数
    action_num_heads: int | None = None                     # [可配置] 注意力头数 (None = 自动)
    action_attention_head_dim: int | None = None            # [可配置] 每头维度 (None = 自动)
    action_dropout: float = 0.2                             # [可配置] Action head dropout (0.0-0.5)
    action_num_timestep_buckets: int = 1000                 # [可配置] 时间步分段数
    action_noise_beta_alpha: float = 1.5                    # [可配置] Beta分布 α 参数
    action_noise_beta_beta: float = 1.0                     # [可配置] Beta分布 β 参数
    action_noise_s: float = 0.999                           # [可配置] 噪声衰减参数
    num_target_vision_tokens: int = 16                      # [可配置] 目标视觉 token 数
    action_max_seq_len: int = 1024                          # [可配置] 最大序列长度
    num_inference_timesteps: int = 4                        # [可配置] Inference 时的去噪步数
    repeated_diffusion_steps: int = 4                       # [可配置] 训练时 diffusion 重复数
    num_action_tokens_per_timestep: int = 4                 # [可配置] 每个时间步的 action token 数
    num_embodied_action_tokens_per_instruction: int = 8     # [可配置] 每条指令的 embodied token 数

    # ========== Sys-12 参数: LeWorldModel 世界模型 ==========
    # [可配置] 当架构模式 = Sys-11+Sys-12 混合时生效；Sys-11 纯动作模式下强制为 False
    enable_lew_world_model: bool = False
    lew_loss_weight: float = 0.1                            # [可配置] 世界模型 loss 权重 (0.01-1.0)
    lew_hidden_dim: int = 192                               # [可配置] ARPredictor 隐藏层维度 (64-512)
    lew_num_layers: int = 6                                 # [可配置] ARPredictor Transformer 层数 (1-12)
    lew_attention_heads: int = 8                            # [可配置] 注意力头数 (4/8/16)
    lew_dim_head: int = 24                                  # [可配置] 每注意力头维度
    lew_mlp_dim: int = 768                                  # [可配置] FFN 隐藏层维度
    lew_dropout: float = 0.1                                # [可配置] dropout 率 (0.0-0.3)
    num_video_frames: int = 2                               # [可配置] 视频帧数 (必须 ≥ 2，Sys-12 模式下需要 t/t+1)

    # ========== 预处理与后处理参数 (Sys-11 + Sys-12 共用) ==========
    resize_images_to: tuple[int, int] | None = (64, 64)     # [可配置] 图像 resize 尺寸 (None = 不 resize)
    binarize_gripper_action: bool = True                    # [可配置] 夹爪动作是否二值化
    pre_snap_gripper_action: bool = True                    # [可配置] 夹爪预截断
    clip_normalized_actions: bool = True                    # [可配置] 是否裁剪归一化后的动作
    gripper_dim: int = 6                                    # [可配置] 夹爪维度
    gripper_threshold: float = 0.5                          # [可配置] 夹爪二值化阈值
    torch_dtype: str = "float16"                            # [可配置] 训练 dtype: "float16" / "float32" / "bfloat16"

    # ========== 优化器与调度器 (Sys-11 + Sys-12 共用) ==========
    gradient_checkpointing: bool = True                     # [可配置] 梯度 checkpointing (省显存)
    optimizer_lr: float = 1e-4                              # [可配置] 学习率
    optimizer_betas: tuple[float, float] = (0.9, 0.95)      # [可配置] AdamW β1, β2
    optimizer_eps: float = 1e-8                             # [可配置] AdamW ε
    optimizer_weight_decay: float = 1e-10                   # [可配置] weight decay
    optimizer_grad_clip_norm: float = 10.0                  # [可配置] 梯度裁剪范数
    scheduler_warmup_steps: int = 1_000                     # [可配置] warmup 步数
    scheduler_decay_steps: int = 30_000                     # [可配置] 衰减步数
    scheduler_decay_lr: float = 2.5e-6                      # [可配置] 最终学习率

    # ========== 任务维度 ==========
    action_dim: int = 2                                     # [由数据集自动覆盖]
    state_dim: int = 2                                      # [由数据集自动覆盖]

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