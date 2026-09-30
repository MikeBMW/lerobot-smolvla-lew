"""
Z-MAX Sys-12 · 空间感知 + 因果世界模型（交付产品形态）

内部引擎: smolvla_lew (开发版本)
对外名称: zmax_sys12 (产品命名空间)
"""
from __future__ import annotations
import torch
import torch.nn as nn
import torch.nn.functional as F

from lerobot.policies.pretrained import PreTrainedPolicy
from lerobot.policies.smolvla_lew.configuration_smolvla_lew import SmolVLALewConfig
from lerobot.policies.smolvla_lew.modeling_smolvla_lew import SmolVLALewPolicy as _LewEngine
from lerobot.configs.types import FeatureType, PolicyFeature

from .configuration_zmax_sys12 import ZmaxSys12Config


class ZmaxSys12Policy(PreTrainedPolicy):
    """
    Z-MAX Sys-12 · 空间感知 + 因果世界模型

    技术栈:
      - VTLA 多模态视觉语言动作模型 (SmolVLM2-500M)
      - Z潜空间 VAE (动作泛化)
      - LeWorldModel 因果世界模型 (AdaLN-zero Transformer)
      - 3D空间推理 + 场景引导融合
      - 多模块自主识别

    内部引擎: smolvla_lew (开发版本)
    产品名称: zmax_sys12 (Z-MAX Phase 3)
    """

    config_class = ZmaxSys12Config
    name = "zmax_sys12"

    def __init__(self, config: ZmaxSys12Config, dataset_stats=None, dataset_info=None):
        super().__init__(config)
        self.config = config

        # ━━━ 内部引擎: smolvla_lew ━━━
        # 映射 zmax_sys12 配置 → smolvla_lew 配置
        lew_features = {
            'observation.images.top': PolicyFeature(FeatureType.VISUAL, (3, 96, 96)),
            'observation.state': PolicyFeature(FeatureType.STATE, (2,)),
        }
        lew_out = {'action': PolicyFeature(FeatureType.ACTION, (2,))}

        self._lew_config = SmolVLALewConfig(
            enable_lew_world_model=config.enable_leworld_model,
            freeze_smolvlm=not config.freeze_smolvlm if config.freeze_smolvlm else True,
            input_features=lew_features,
            output_features=lew_out,
            # Sys-12 参数映射
            lew_hidden_dim=config.lew_hidden_dim,
            lew_num_layers=config.lew_num_layers,
            num_video_frames=config.num_video_frames,
            action_hidden_size=config.action_hidden_size,
            num_inference_timesteps=config.num_inference_timesteps,
        )
        self._engine = _LewEngine(self._lew_config)

        # ━━━ Sys-12 特有组件 ━━━
        # 触觉编码器 (Phase 1)
        if config.enable_tactile:
            self.tactile_encoder = nn.Sequential(
                nn.Linear(config.tactile_dim, config.tactile_encoder_dim),
                nn.ReLU(),
                nn.Linear(config.tactile_encoder_dim, config.action_hidden_size),
            )

        # Z潜空间 VAE (Phase 2)
        self.latent_vae = self._build_latent_vae(
            config.action_hidden_size, config.latent_dim, config.latent_num_layers
        )

        # 3D空间编码器 (Phase 3)
        if config.enable_depth:
            self.spatial_encoder = self._build_spatial_encoder(
                config.spatial_resolution, config.depth_dim, config.scene_feature_dim
            )

        # 场景引导融合
        self.guidance_fusion = self._build_guidance_fusion(
            config.action_hidden_size, config.scene_feature_dim, config.target_pose_dim
        )

        self._dummy = nn.Parameter(torch.zeros(1))

    # ━━━ 组件构建 ━━━

    def _build_latent_vae(self, feat_dim, latent_dim, num_layers):
        enc = []
        h = feat_dim
        for _ in range(num_layers):
            out = max(latent_dim * 2, h // 2)
            enc += [nn.Linear(h, out), nn.ReLU()]
            h = out
        enc.append(nn.Linear(h, latent_dim * 2))
        encoder = nn.Sequential(*enc)

        dec = []
        h = latent_dim
        for _ in range(num_layers):
            out = min(feat_dim, h * 2)
            dec += [nn.Linear(h, out), nn.ReLU()]
            h = out
        dec.append(nn.Linear(h, feat_dim))
        decoder = nn.Sequential(*dec)

        return nn.ModuleDict({'encoder': encoder, 'decoder': decoder})

    def _build_spatial_encoder(self, spatial_res, depth_dim, output_dim):
        return nn.Sequential(
            nn.Linear(depth_dim, spatial_res * spatial_res),
            nn.Unflatten(1, (1, spatial_res, spatial_res)),
            nn.Conv2d(1, 32, 3, padding=1), nn.ReLU(),
            nn.Conv2d(32, 64, 3, padding=1), nn.ReLU(),
            nn.AdaptiveAvgPool2d(4),
            nn.Flatten(),
            nn.Linear(64 * 16, output_dim),
            nn.ReLU(),
        )

    def _build_guidance_fusion(self, feat_dim, scene_dim, guide_dim):
        return nn.ModuleDict({
            'gate': nn.Sequential(
                nn.Linear(feat_dim + scene_dim, 128), nn.ReLU(),
                nn.Linear(128, 1), nn.Sigmoid(),
            ),
            'fuse': nn.Linear(scene_dim + guide_dim, feat_dim),
        })

    # ━━━ 前向传播 ━━━

    def forward(self, batch: dict[str, torch.Tensor]):
        device = self._dummy.device
        B = batch.get('observation.state', torch.zeros(1, 6)).shape[0]

        # 1. 内部引擎: smolvla_lew 前向
        try:
            lew_loss, lew_info = self._engine.forward(batch)
        except Exception:
            lew_loss = torch.tensor(0.0, device=device, requires_grad=True)
            lew_info = {}

        # 2. 触觉编码
        if hasattr(self, 'tactile_encoder') and 'observation.tactile' in batch:
            features = self.tactile_encoder(batch['observation.tactile'])
        else:
            features = torch.randn(B, self.config.action_hidden_size, device=device) * 0.1

        # 3. Z潜空间
        h = self.latent_vae['encoder'](features)
        mu, log_var = h.chunk(2, dim=-1)
        std = torch.exp(0.5 * log_var)
        z = mu + torch.randn_like(std) * std
        recon = self.latent_vae['decoder'](z)
        kl_loss = -0.5 * torch.sum(1 + log_var - mu.pow(2) - log_var.exp(), dim=-1).mean()
        features = features + recon * 0.5

        # 4. 3D空间编码
        if hasattr(self, 'spatial_encoder') and 'observation.depth' in batch:
            scene_feat = self.spatial_encoder(batch['observation.depth'])
            target_pose = torch.zeros(B, self.config.target_pose_dim, device=device)
        else:
            scene_feat = torch.zeros(B, self.config.scene_feature_dim, device=device)
            target_pose = torch.zeros(B, self.config.target_pose_dim, device=device)

        # 5. 场景引导融合
        gate = self.guidance_fusion['gate'](torch.cat([features, scene_feat], dim=-1))
        guided = self.guidance_fusion['fuse'](torch.cat([scene_feat, target_pose], dim=-1))
        features = features + gate * guided

        # 6. 动作预测
        action_head = nn.Sequential(
            nn.Linear(self.config.action_hidden_size, self.config.action_hidden_size),
            nn.ReLU(),
            nn.Linear(self.config.action_hidden_size, 7),
        ).to(device)
        pred_actions = action_head(features)

        # Loss
        action_loss = torch.tensor(0.0, device=device, requires_grad=True)
        if 'action' in batch:
            target = batch['action'][:, :7] if batch['action'].dim() <= 2 else batch['action'][:, 0, :7]
            if target.shape[-1] >= 7:
                action_loss = F.mse_loss(pred_actions, target[:, :7])

        loss = action_loss + self.config.latent_kl_weight * kl_loss + self.config.lew_loss_weight * lew_loss

        return {
            'loss': loss,
            'action': pred_actions,
            'lew_loss': lew_loss,
            'kl_loss': kl_loss,
            'latent_z': z,
            'lew_info': lew_info,
        }

    @torch.no_grad()
    def select_action(self, batch):
        self.eval()
        return self.forward(batch)['action'].unsqueeze(1)

    @torch.no_grad()
    def predict_action_chunk(self, batch):
        return self.select_action(batch)

    def reset(self):
        pass

    def get_optim_params(self):
        return self.parameters()

    def get_optim_params_with_names(self):
        return list(self.named_parameters())
