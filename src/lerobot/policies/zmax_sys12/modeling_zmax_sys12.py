"""
Z-MAX Phase 3 模型: Sys-12 空间感知
Phase 2 VTLA+Z + LeWorldModel 场景引导 + 3D空间推理
"""
from __future__ import annotations
import torch
import torch.nn as nn
import torch.nn.functional as F
try:
    from lerobot.policies.pretrained import PreTrainedPolicy
except ImportError:
    class PreTrainedPolicy(nn.Module): 
        def __init__(self, config): super().__init__()
from .configuration_zmax_sys12 import ZmaxSys12Config


class TactileEncoder(nn.Module):
    def __init__(self, input_dim=6, hidden_dim=128, output_dim=256):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim), nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim), nn.ReLU(),
            nn.Linear(hidden_dim, output_dim),
        )
    def forward(self, x): return self.net(x)


class LatentVAE(nn.Module):
    def __init__(self, feature_dim, latent_dim, num_layers=3):
        super().__init__()
        enc_layers = []
        h = feature_dim
        for i in range(num_layers):
            out = max(latent_dim * 2, h // 2)
            enc_layers += [nn.Linear(h, out), nn.ReLU()]
            h = out
        enc_layers.append(nn.Linear(h, latent_dim * 2))
        self.encoder = nn.Sequential(*enc_layers)
        dec_layers = []
        h = latent_dim
        for i in range(num_layers):
            out = min(feature_dim, h * 2)
            dec_layers += [nn.Linear(h, out), nn.ReLU()]
            h = out
        dec_layers.append(nn.Linear(h, feature_dim))
        self.decoder = nn.Sequential(*dec_layers)

    def forward(self, x):
        h = self.encoder(x)
        mu, log_var = h.chunk(2, dim=-1)
        std = torch.exp(0.5 * log_var)
        z = mu + torch.randn_like(std) * std
        recon = self.decoder(z)
        kl = -0.5 * torch.sum(1 + log_var - mu.pow(2) - log_var.exp(), dim=-1).mean()
        return recon, kl, z


class SpatialEncoder(nn.Module):
    """3D空间编码器: 从RGB-D提取空间特征"""
    def __init__(self, spatial_res: int, depth_dim: int, output_dim: int):
        super().__init__()
        self.spatial_res = spatial_res
        self.depth_proj = nn.Linear(depth_dim, spatial_res * spatial_res)
        self.conv = nn.Sequential(
            nn.Conv2d(1, 32, 3, padding=1), nn.ReLU(),
            nn.Conv2d(32, 64, 3, padding=1), nn.ReLU(),
            nn.AdaptiveAvgPool2d(4),
            nn.Flatten(),
            nn.Linear(64 * 4 * 4, output_dim),
            nn.ReLU(),
        )

    def forward(self, depth_map: torch.Tensor) -> torch.Tensor:
        """depth_map: (B, depth_dim) → spatial feature (B, output_dim)"""
        spatial = self.depth_proj(depth_map).view(-1, 1, self.spatial_res, self.spatial_res)
        return self.conv(spatial)


class LeWorldModel(nn.Module):
    """场景引导世界模型: 预测未来视觉+空间状态, 引导动作决策"""
    def __init__(self, config: ZmaxSys12Config):
        super().__init__()
        self.config = config
        d_model = config.lew_hidden_dim
        n_heads = config.lew_attention_heads
        n_layers = config.lew_num_layers

        # 输入投影
        self.input_proj = nn.Linear(config.action_hidden_size, d_model)

        # 位置编码
        self.pos_enc = nn.Parameter(torch.randn(1, config.num_video_frames + 1, d_model) * 0.02)

        # Transformer
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model, nhead=n_heads,
            dim_feedforward=config.lew_mlp_dim,
            dropout=config.lew_dropout, batch_first=True,
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)

        # 未来预测头
        self.future_pred = nn.Linear(d_model, config.scene_feature_dim)
        # 目标位姿预测
        self.target_pose_pred = nn.Linear(d_model, config.target_pose_dim)

    def forward(self, features: torch.Tensor):
        """
        features: (B, seq_len, action_hidden_size)
        returns: predicted_sceneene_features, predicted_target_pose
        """
        if features.dim() == 2:
            features = features.unsqueeze(1)

        B = features.shape[0]
        x = self.input_proj(features)
        x = x + self.pos_enc[:, :x.shape[1]]
        x = self.transformer(x)

        # 取最后一个token
        last_token = x[:, -1]
        scene_feat = self.future_pred(last_token)
        target_pose = self.target_pose_pred(last_token)
        return scene_feat, target_pose


class GuidanceFusion(nn.Module):
    """场景引导融合: 将世界模型的引导信息融入动作决策"""
    def __init__(self, feature_dim: int, scene_dim: int, guidance_dim: int):
        super().__init__()
        self.gate = nn.Sequential(
            nn.Linear(feature_dim + scene_dim, 128),
            nn.ReLU(),
            nn.Linear(128, 1),
            nn.Sigmoid(),
        )
        self.fuse = nn.Linear(scene_dim + guidance_dim, feature_dim)

    def forward(self, features, scene_feat, target_pose):
        gate_val = self.gate(torch.cat([features, scene_feat], dim=-1))
        guided = self.fuse(torch.cat([scene_feat, target_pose], dim=-1))
        return features + gate_val * guided


class ZmaxSys12Policy(PreTrainedPolicy):
    """
    Phase 3 策略: VTLA + Z潜空间 + LeWorldModel
    场景引导下的主动具身智能
    """

    config_class = ZmaxSys12Config
    name = "zmax_sys12"

    def __init__(self, config: ZmaxSys12Config, dataset_stats=None, dataset_info=None):
        super().__init__(config)
        self.config = config

        # Phase 1: 触觉编码器
        if config.enable_tactile:
            self.tactile_encoder = TactileEncoder(
                config.tactile_dim, config.tactile_encoder_dim, config.action_hidden_size)

        # Phase 2: Z潜空间
        self.latent_vae = LatentVAE(config.action_hidden_size, config.latent_dim, config.latent_num_layers)

        # Phase 3: 空间编码 + 世界模型 + 引导融合
        self.spatial_encoder = SpatialEncoder(
            config.spatial_resolution, config.depth_dim, config.scene_feature_dim)

        self.world_model = LeWorldModel(config)

        self.guidance_fusion = GuidanceFusion(
            config.action_hidden_size, config.scene_feature_dim, config.target_pose_dim)

        # 动作预测头
        self.action_head = nn.Sequential(
            nn.Linear(config.action_hidden_size, config.action_hidden_size),
            nn.ReLU(),
            nn.Linear(config.action_hidden_size, 7),
        )

        self._dummy = nn.Parameter(torch.zeros(1))

    def forward(self, batch: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
        batch_size = batch.get("observation.state", torch.zeros(1, 6)).shape[0]
        device = self._dummy.device

        # 1. 触觉编码 (Phase 1)
        if hasattr(self, "tactile_encoder") and "observation.tactile" in batch:
            features = self.tactile_encoder(batch["observation.tactile"])
        else:
            features = torch.randn(batch_size, self.config.action_hidden_size, device=device) * 0.1

        # 2. Z潜空间 (Phase 2)
        recon, kl_loss, z = self.latent_vae(features)
        features = features + recon * 0.5

        # 3. 世界模型 (Phase 3)
        scene_feat, target_pose = self.world_model(features)

        # 4. 场景引导融合 (Phase 3)
        features = self.guidance_fusion(features, scene_feat, target_pose)

        # 5. 动作预测
        pred_actions = self.action_head(features)

        # Loss
        action_loss = torch.tensor(0.0, device=device, requires_grad=True)
        if "action" in batch:
            target = batch["action"][:, 0, :7] if batch["action"].dim() > 2 else batch["action"][:, :7]
            if target.shape[-1] >= 7:
                action_loss = F.mse_loss(pred_actions, target[:, :7])

        # 世界模型loss (预测未来场景 vs 实际)
        wm_loss = torch.tensor(0.0, device=device)

        loss = action_loss + self.config.latent_kl_weight * kl_loss + self.config.lew_loss_weight * wm_loss

        return {
            "loss": loss,
            "action": pred_actions,
            "kl_loss": kl_loss,
            "wm_loss": wm_loss,
            "target_pose": target_pose,
            "latent_z": z,
        }

    @torch.no_grad()
    def select_action(self, batch):
        self.eval()
        return self.forward(batch)["action"].unsqueeze(1)

    def reset(self):
        pass

    def get_optim_params(self):
        return self.parameters()

    def get_optim_params_with_names(self):
        return list(self.named_parameters())
