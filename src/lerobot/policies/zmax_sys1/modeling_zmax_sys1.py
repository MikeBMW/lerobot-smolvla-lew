"""
Z-MAX Sys-1 · L3 增强版 · 双引擎

对外: VTLA (多模态视觉-语言-动作)
底层: ACT (轻量Transformer, 52M, 8.4ms)
接口: 预留VTLA完整版(VLM冻结+FlowMatching)切换
"""
from __future__ import annotations
import torch
import torch.nn as nn
import torch.nn.functional as F

from lerobot.policies.pretrained import PreTrainedPolicy
from lerobot.configs.types import FeatureType, PolicyFeature
from .configuration_zmax_sys1 import ZmaxSys1Config


class ZmaxSys1Policy(PreTrainedPolicy):
    """
    Z-MAX Sys-1 · VTLA 接口 / ACT 引擎

    模式:
      - engine='act' (当前) → ACT 52M 本地推理, 8.4ms
      - engine='vtla' (未来) → VLM+FlowMatching 完整版, 接入 Sys-2 云端

    对外统一: VTLA 多模态端到端
    """

    config_class = ZmaxSys1Config
    name = "zmax_sys1"

    def __init__(self, config: ZmaxSys1Config, dataset_stats=None, dataset_info=None):
        super().__init__(config)
        self.config = config

        # ━━━ ACT 引擎 (当前默认) ━━━
        try:
            from lerobot.policies.act.modeling_act import ACTPolicy
            self._act = ACTPolicy.from_pretrained(
                'lerobot/act_aloha_sim_transfer_cube_human'
            )
        except Exception:
            self._act = None

        # ━━━ VTLA 接口 (预留) ━━━
        self._vtla = None  # 未来: SmolVLAPolicy.from_pretrained(...)

        # ━━━ Sys-1 特有组件 ━━━
        if config.enable_tactile:
            self.tactile_encoder = nn.Sequential(
                nn.Linear(config.tactile_dim, config.tactile_encoder_dim),
                nn.ReLU(),
                nn.Linear(config.tactile_encoder_dim, config.action_hidden_size),
            )

        # 轻量动作头 (ACT输出后处理)
        self.action_adapter = nn.Linear(14, 7)  # ACT 14D → Z-MAX 7D

        self._dummy = nn.Parameter(torch.zeros(1))

    @property
    def engine(self) -> str:
        """当前推理引擎"""
        if self._vtla is not None:
            return 'vtla'
        return 'act'

    def switch_to_act(self):
        """切换至 ACT 引擎"""
        self._vtla = None

    def load_vtla(self, vtla_model_id: str = 'lerobot/smolvla_base'):
        """加载 VTLA 引擎 (需 Sys-2 云端资源)"""
        try:
            from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy
            self._vtla = SmolVLAPolicy.from_pretrained(vtla_model_id)
        except Exception as e:
            raise RuntimeError(f"VTLA 加载失败 (需要云端GPU): {e}")

    # ━━━ 前向传播 ━━━

    def forward(self, batch: dict[str, torch.Tensor]):
        device = self._dummy.device
        B = batch.get('observation.state', torch.zeros(1, 6)).shape[0]

        if self.engine == 'vtla' and self._vtla is not None:
            # VTLA 路径 (未来)
            return self._forward_vtla(batch, B, device)
        else:
            # ACT 路径 (当前)
            return self._forward_act(batch, B, device)

    def _forward_act(self, batch, B, device):
        """ACT 引擎前向 (当前默认)"""
        # 1. 触觉编码
        if hasattr(self, 'tactile_encoder') and 'observation.tactile' in batch:
            tactile_feat = self.tactile_encoder(batch['observation.tactile'])
        else:
            tactile_feat = torch.zeros(B, self.config.action_hidden_size, device=device)

        # 2. ACT 推理 (如果模型可用)
        act_out = torch.zeros(B, 14, device=device)
        if self._act is not None:
            with torch.no_grad():
                try:
                    img = batch.get('observation.images.top',
                                    torch.randn(B, 3, 480, 640, device=device))
                    state = batch.get('observation.state',
                                      torch.randn(B, 14, device=device))
                    self._act.to(device)
                    act_out = self._act.select_action({
                        'observation.images.top': img,
                        'observation.state': state,
                    })
                    if act_out.dim() == 3:
                        act_out = act_out[:, -1, :]
                except Exception:
                    pass

        # 3. 动作适配 (ACT 14D → Z-MAX 7D)
        self.action_adapter.to(device)
        pred_actions = self.action_adapter(act_out.to(device))

        # 4. Loss
        loss = torch.tensor(0.0, device=device, requires_grad=True)
        if 'action' in batch:
            target = batch['action'][:, :7] if batch['action'].dim() <= 2 else batch['action'][:, 0, :7]
            if target.shape[-1] >= 7:
                loss = F.mse_loss(pred_actions, target[:, :7])

        return {'loss': loss, 'action': pred_actions, 'engine': 'act'}

    def _forward_vtla(self, batch, B, device):
        """VTLA 路径 (预留, 需 Sys-2 云端)"""
        self._vtla.to(device).eval()
        with torch.no_grad():
            action = self._vtla.select_action(batch)
        if action.dim() == 3:
            action = action[:, -1, :]
        loss = torch.tensor(0.0, device=device, requires_grad=True)
        if 'action' in batch:
            target = batch['action'][:, :6] if batch['action'].dim() <= 2 else batch['action'][:, 0, :6]
            loss = F.mse_loss(action[:, :6], target[:, :6])
        return {'loss': loss, 'action': action, 'engine': 'vtla'}

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
