"""
Z-MAX Phase 1 模型: System 1 VTLA 基础插拔
继承 smolvla_lew，增加触觉编码器
"""
from __future__ import annotations
import torch
import torch.nn as nn
try:
    from lerobot.policies.pretrained import PreTrainedPolicy
except ImportError:
    class PreTrainedPolicy(nn.Module): 
        def __init__(self, config): super().__init__()
from .configuration_zmax_sys1 import ZmaxSys1Config


class TactileEncoder(nn.Module):
    """6维力/力矩触觉编码器"""
    def __init__(self, input_dim: int = 6, hidden_dim: int = 128, output_dim: int = 256):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, output_dim),
        )

    def forward(self, tactile: torch.Tensor) -> torch.Tensor:
        return self.net(tactile)


class ZmaxSys1Policy(PreTrainedPolicy):
    """
    Phase 1 策略: VTLA 端到端插拔
    视觉(V) + 触觉(T) + 语言(L) → 动作(A)
    """

    config_class = ZmaxSys1Config
    name = "zmax_sys1"

    def __init__(self, config: ZmaxSys1Config, dataset_stats=None, dataset_info=None):
        super().__init__(config)
        self.config = config

        # 触觉编码器
        if config.enable_tactile:
            self.tactile_encoder = TactileEncoder(
                input_dim=config.tactile_dim,
                hidden_dim=config.tactile_encoder_dim,
                output_dim=config.action_hidden_size,
            )

        # 简化的动作预测头 (DiT-B placeholder)
        self.action_head = nn.Sequential(
            nn.Linear(config.action_hidden_size, config.action_hidden_size),
            nn.ReLU(),
            nn.Linear(config.action_hidden_size, 7),  # 6DoF + gripper
        )

        self._dummy = nn.Parameter(torch.zeros(1))  # 确保有可训练参数

    def forward(self, batch: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
        """前向传播: 返回action loss"""
        batch_size = batch.get("observation.state", torch.zeros(1, 6)).shape[0]

        # 简化的动作预测
        if hasattr(self, "tactile_encoder") and "observation.tactile" in batch:
            features = self.tactile_encoder(batch["observation.tactile"])
        else:
            features = torch.zeros(batch_size, self.config.action_hidden_size, device=self._dummy.device)

        pred_actions = self.action_head(features)

        loss = torch.tensor(0.0, device=self._dummy.device, requires_grad=True)
        if "action" in batch:
            target = batch["action"][:, 0, :7] if batch["action"].dim() > 2 else batch["action"][:, :7]
            if target.shape[-1] >= 7:
                loss = nn.functional.mse_loss(pred_actions, target[:, :7])

        return {"loss": loss, "action": pred_actions}

    @torch.no_grad()
    def select_action(self, batch: dict[str, torch.Tensor]) -> torch.Tensor:
        self.eval()
        out = self.forward(batch)
        return out["action"].unsqueeze(1)

    def reset(self):
        pass

    def get_optim_params(self):
        return self.parameters()

    def get_optim_params_with_names(self):
        return list(self.named_parameters())
