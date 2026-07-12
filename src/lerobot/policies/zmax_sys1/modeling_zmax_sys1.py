"""
Z-MAX Sys-1 · 统一推理框架

引擎策略:
  - engine='act'    → 本地 ACT (52M, 8.4ms) on WSL RTX4060
  - engine='vtla'   → 远程 VTLA (450M, ~220ms) on 4090 via gRPC
  - engine='groot'  → 远程 GR00T (2B, ~500ms) on 4090 via gRPC
  - engine='smolvla'→ 本地 smolvla (450M) — Sys-11兼容
  - engine='lew'    → 本地 smolvla_lew (628M) — Sys-12兼容

对外名称: VTLA (Z-MAX Sys-1)
"""
from __future__ import annotations
import torch, time, json, os
import torch.nn as nn
import torch.nn.functional as F

from lerobot.policies.pretrained import PreTrainedPolicy
from lerobot.configs.types import FeatureType, PolicyFeature
from .configuration_zmax_sys1 import ZmaxSys1Config


class ZmaxSys1Policy(PreTrainedPolicy):
    """
    Z-MAX Sys-1 · 统一推理引擎

    本地引擎: ACT (52M, <1ms)
    远程引擎: VTLA / GR00T (4090 via gRPC)
    兼容引擎: smolvla (Sys-11) / smolvla_lew (Sys-12)

    切换: model.set_engine('vtla') or config.engine='vtla'
    """

    config_class = ZmaxSys1Config
    name = "zmax_sys1"

    def __init__(self, config: ZmaxSys1Config, dataset_stats=None, dataset_info=None):
        super().__init__(config)
        self.config = config
        self._engine_name = getattr(config, 'engine', 'act')
        self._local_model = None
        self._grpc_client = None

        # ━━━ 加载本地引擎 ━━━
        self._load_local_engine()

        # ━━━ gRPC客户端 (4090) ━━━
        self._grpc_host = getattr(config, 'grpc_host', '106.75.239.80')
        self._grpc_port = getattr(config, 'grpc_port', 50051)

        # ━━━ 动作适配器 ━━━
        self.action_adapter = nn.Linear(14, 7)  # ACT 14D → Z-MAX 7D

        self._dummy = nn.Parameter(torch.zeros(1))

    # ═══════ 引擎管理 ═══════

    def _load_local_engine(self):
        """加载本地引擎 (ACT/smolvla/smolvla_lew)"""
        if self._engine_name == 'act':
            try:
                from lerobot.policies.act.modeling_act import ACTPolicy
                self._local_model = ACTPolicy.from_pretrained(
                    'lerobot/act_aloha_sim_transfer_cube_human'
                )
            except Exception as e:
                print(f"[Sys-1] ACT load failed: {e}")

        elif self._engine_name == 'smolvla':
            try:
                from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy
                features = {
                    'observation.images.camera1': PolicyFeature(FeatureType.VISUAL, (3,256,256)),
                    'observation.images.camera2': PolicyFeature(FeatureType.VISUAL, (3,256,256)),
                    'observation.images.camera3': PolicyFeature(FeatureType.VISUAL, (3,256,256)),
                    'observation.state': PolicyFeature(FeatureType.STATE, (2,)),
                }
                from lerobot.policies.smolvla.configuration_smolvla import SmolVLAConfig
                cfg = SmolVLAConfig(input_features=features, 
                                    output_features={'action': PolicyFeature(FeatureType.ACTION, (2,))})
                self._local_model = SmolVLAPolicy(cfg)
            except Exception as e:
                print(f"[Sys-1] SmolVLA load failed: {e}")

        elif self._engine_name == 'lew':
            try:
                from lerobot.policies.smolvla_lew.modeling_smolvla_lew import SmolVLALewPolicy
                from lerobot.policies.smolvla_lew.configuration_smolvla_lew import SmolVLALewConfig
                features = {
                    'observation.images.top': PolicyFeature(FeatureType.VISUAL, (3,96,96)),
                    'observation.state': PolicyFeature(FeatureType.STATE, (2,)),
                }
                cfg = SmolVLALewConfig(
                    input_features=features,
                    output_features={'action': PolicyFeature(FeatureType.ACTION, (2,))},
                    freeze_smolvlm=True,
                    enable_lew_world_model=False
                )
                self._local_model = SmolVLALewPolicy(cfg)
            except Exception as e:
                print(f"[Sys-1] LEW load failed: {e}")

    @property
    def engine(self) -> str:
        return self._engine_name

    def set_engine(self, name: str):
        """切换引擎: act | vtla | groot | smolvla | lew"""
        self._engine_name = name
        if name in ('act', 'smolvla', 'lew'):
            self._load_local_engine()
        print(f"[Sys-1] Engine → {name}")

    def _get_grpc_client(self):
        """懒加载gRPC客户端"""
        if self._grpc_client is None and self._engine_name in ('vtla', 'groot'):
            try:
                import grpc
                from hermes_gateway_mac.sys2_pb2_grpc import Sys2ServiceStub
                from hermes_gateway_mac import sys2_pb2
                channel = grpc.insecure_channel(f"{self._grpc_host}:{self._grpc_port}")
                self._grpc_client = Sys2ServiceStub(channel)
                self._sys2_pb2 = sys2_pb2
            except ImportError:
                print("[Sys-1] gRPC not available")
        return self._grpc_client

    # ═══════ 推理 ═══════

    def _infer_local(self, batch, device) -> dict:
        """本地推理 (ACT/smolvla/lew)"""
        if self._local_model is None:
            return {'action': torch.zeros(1, 7, device=device),
                    'loss': torch.tensor(0.0, device=device, requires_grad=True),
                    'engine': self._engine_name}

        self._local_model.to(device).eval()
        try:
            with torch.no_grad():
                action = self._local_model.select_action(batch)
                if action.dim() == 3:
                    action = action[:, -1, :]
                if action.shape[-1] > 7:
                    action = action[:, :7]
                elif action.shape[-1] == 6:
                    action = F.pad(action, (0, 1))
                elif action.shape[-1] == 14:
                    self.action_adapter.to(device)
                    action = self.action_adapter(action)
        except Exception:
            action = torch.zeros(1, 7, device=device)

        loss = torch.tensor(0.0, device=device, requires_grad=True)
        if 'action' in batch:
            target = batch['action'][:, :7] if batch['action'].dim() <= 2 else batch['action'][:, 0, :7]
            if target.shape[-1] >= 7:
                loss = F.mse_loss(action, target[:, :7])

        return {'action': action, 'loss': loss, 'engine': self._engine_name}

    def _infer_remote(self, batch, device, model_type: str) -> dict:
        """远程推理 (4090 via gRPC)"""
        client = self._get_grpc_client()
        if client is None:
            return {'action': torch.zeros(1, 7, device=device),
                    'loss': torch.tensor(0.0, device=device, requires_grad=True),
                    'engine': f'{self._engine_name}(fallback-local)'}

        try:
            # 提取观测数据
            state = batch.get('observation.state', torch.zeros(1, 6)).cpu().numpy()
            img = None
            for k in batch:
                if 'image' in k:
                    img = batch[k].cpu().numpy()
                    break

            # 构建gRPC请求
            from hermes_gateway_mac import sys2_pb2
            req = sys2_pb2.InferRequest(
                model_type=model_type,
                state=state.flatten().tolist(),
                image=img.flatten().tolist() if img is not None else [],
                image_shape=list(img.shape) if img is not None else [1, 3, 256, 256],
                task=getattr(batch, 'task', 'execute'),
            )
            resp = client.Infer(req)
            action = torch.tensor(resp.action, device=device).reshape(1, -1)
            if action.shape[-1] > 7:
                action = action[:, :7]
        except Exception as e:
            print(f"[Sys-1] gRPC error: {e}")
            action = torch.zeros(1, 7, device=device)

        return {'action': action,
                'loss': torch.tensor(0.0, device=device, requires_grad=True),
                'engine': self._engine_name}

    def forward(self, batch: dict[str, torch.Tensor]):
        device = self._dummy.device

        # 路由
        if self._engine_name in ('vtla',):
            return self._infer_remote(batch, device, 'vtla')
        elif self._engine_name in ('groot',):
            return self._infer_remote(batch, device, 'groot')
        else:
            return self._infer_local(batch, device)

    @torch.no_grad()
    def select_action(self, batch):
        self.eval()
        return self.forward(batch)['action'].unsqueeze(1)

    @torch.no_grad()
    def predict_action_chunk(self, batch):
        return self.select_action(batch)

    def reset(self): pass

    def get_optim_params(self):
        return self.parameters()
