"""
Z-MAX Phase 2 模型: Sys-11 泛化调优
在 Phase 1 VTLA 基础上增加 Z潜空间 VAE + 动作泛化
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
from .configuration_zmax_sys11 import ZmaxSys11Config


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
    """Z潜空间: 动作特征压缩与泛化"""
    def __init__(self, feature_dim: int, latent_dim: int, num_layers: int = 3):
        super().__init__()
        # 编码器
        enc_layers = []
        h = feature_dim
        for i in range(num_layers):
            out = max(latent_dim * 2, h // 2)
            enc_layers += [nn.Linear(h, out), nn.ReLU()]
            h = out
        enc_layers.append(nn.Linear(h, latent_dim * 2))  # mu + log_var
        self.encoder = nn.Sequential(*enc_layers)

        # 解码器
        dec_layers = []
        h = latent_dim
        for i in range(num_layers):
            out = min(feature_dim, h * 2)
            dec_layers += [nn.Linear(h, out), nn.ReLU()]
            h = out
        dec_layers.append(nn.Linear(h, feature_dim))
        self.decoder = nn.Sequential(*dec_layers)

    def encode(self, x):
        h = self.encoder(x)
        mu, log_var = h.chunk(2, dim=-1)
        return mu, log_var

    def reparameterize(self, mu, log_var):
        std = torch.exp(0.5 * log_var)
        eps = torch.randn_like(std)
        return mu + eps * std

    def decode(self, z):
        return self.decoder(z)

    def forward(self, x):
        mu, log_var = self.encode(x)
        z = self.reparameterize(mu, log_var)
        recon = self.decode(z)
        kl = -0.5 * torch.sum(1 + log_var - mu.pow(2) - log_var.exp(), dim=-1).mean()
        return recon, kl, z


class ModuleTypeEmbedding(nn.Module):
    """多型号模块类型嵌入 (一脑多能)"""
    def __init__(self, num_types: int, embed_dim: int):
        super().__init__()
        self.embedding = nn.Embedding(num_types, embed_dim)

    def forward(self, module_type_id: torch.Tensor) -> torch.Tensor:
        return self.embedding(module_type_id)


class ZmaxSys11Policy(PreTrainedPolicy):
    """
    Phase 2 策略: VTLA + Z潜空间泛化
    在 Phase 1 基础上实现动作压缩泛化 + 多型号迁移
    """

    config_class = ZmaxSys11Config
    name = "zmax_sys11"

    def __init__(self, config: ZmaxSys11Config, dataset_stats=None, dataset_info=None):
        super().__init__(config)
        self.config = config

        # 触觉编码器 (from Phase 1)
        if config.enable_tactile:
            self.tactile_encoder = TactileEncoder(
                config.tactile_dim, config.tactile_encoder_dim, config.action_hidden_size)

        # Z潜空间 VAE (Phase 2 新增)
        self.latent_vae = LatentVAE(
            feature_dim=config.action_hidden_size,
            latent_dim=config.latent_dim,
            num_layers=config.latent_num_layers,
        )

        # 多型号嵌入 (Phase 2 新增)
        self.module_embedding = ModuleTypeEmbedding(
            config.num_module_types, config.module_type_embedding_dim)

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

        # 触觉编码
        if hasattr(self, "tactile_encoder") and "observation.tactile" in batch:
            features = self.tactile_encoder(batch["observation.tactile"])
        else:
            features = torch.zeros(batch_size, self.config.action_hidden_size, device=device)

        # Z潜空间压缩泛化
        recon, kl_loss, z = self.latent_vae(features)
        features = features + recon  # 残差连接

        # 动作预测
        pred_actions = self.action_head(features)

        # Loss = L2 + KL * weight
        action_loss = torch.tensor(0.0, device=device, requires_grad=True)
        if "action" in batch:
            target = batch["action"][:, 0, :7] if batch["action"].dim() > 2 else batch["action"][:, :7]
            if target.shape[-1] >= 7:
                action_loss = F.mse_loss(pred_actions, target[:, :7])

        loss = action_loss + self.config.latent_kl_weight * kl_loss
        return {"loss": loss, "action": pred_actions, "kl_loss": kl_loss, "latent_z": z}

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
