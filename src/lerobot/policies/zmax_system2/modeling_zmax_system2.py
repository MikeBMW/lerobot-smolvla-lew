"""
Z-MAX Phase 4 模型: System 2 全系统大脑
编排 Phase1-3 子系统 + 任务拆解 + 多产线调度
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
from .configuration_zmax_system2 import ZmaxSystem2Config


class TaskPlanner(nn.Module):
    """任务规划器: 将高层任务拆解为子步骤序列"""
    def __init__(self, config: ZmaxSystem2Config):
        super().__init__()
        d_model = config.planner_hidden_dim

        self.task_embed = nn.Parameter(torch.randn(config.max_task_steps, config.task_embedding_dim) * 0.02)
        self.input_proj = nn.Linear(config.action_hidden_size, d_model)

        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model, nhead=config.planner_num_heads,
            dim_feedforward=d_model * 4, dropout=0.1, batch_first=True,
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=config.planner_num_layers)

        # 子步骤输出
        self.step_head = nn.Linear(d_model, config.task_embedding_dim)
        # 子系统路由
        self.router = nn.Sequential(
            nn.Linear(d_model, 64), nn.ReLU(),
            nn.Linear(64, 3),  # sys1, sys11, sys12
            nn.Softmax(dim=-1),
        )

    def forward(self, features: torch.Tensor):
        """
        features: (B, action_hidden_size) 全局特征
        returns: task_steps (B, max_steps, task_embed), subsystem_weights (B, 3)
        """
        B = features.shape[0]
        x = self.input_proj(features).unsqueeze(1)  # (B, 1, d_model)

        # 扩展为多步任务
        task_queries = self.task_embed.unsqueeze(0).expand(B, -1, -1)  # (B, steps, task_embed)
        task_queries_proj = task_queries  # 已经是正确维度
        x = torch.cat([x, task_queries_proj[:, :, :x.shape[-1]]], dim=1) if task_queries_proj.shape[-1] == x.shape[-1] else x

        x = self.transformer(x)

        # 子步骤计划
        step_embeds = self.step_head(x[:, 1:])  # (B, steps, task_embed)
        # 子系统路由
        route_weights = self.router(x[:, 0])  # (B, 3)

        return step_embeds, route_weights


class MultiLineCoordinator(nn.Module):
    """多产线协调器"""
    def __init__(self, max_lines: int, status_dim: int, feature_dim: int):
        super().__init__()
        self.line_status_proj = nn.Linear(status_dim, feature_dim)
        self.attention = nn.MultiheadAttention(feature_dim, num_heads=4, batch_first=True)
        self.output = nn.Linear(feature_dim, feature_dim)

    def forward(self, global_feat: torch.Tensor, line_statuses: torch.Tensor = None):
        """global_feat: (B, D), line_statuses: (B, num_lines, status_dim)"""
        if line_statuses is None:
            return global_feat
        B = global_feat.shape[0]
        line_feats = self.line_status_proj(line_statuses)  # (B, L, D)
        q = global_feat.unsqueeze(1)
        out, _ = self.attention(q, line_feats, line_feats)
        return global_feat + self.output(out.squeeze(1))


class ZmaxSystem2Policy(PreTrainedPolicy):
    """
    Phase 4 策略: System 2 全系统大脑
    编排 Phase 1-3 子系统，实现 L4 全域自主
    """

    config_class = ZmaxSystem2Config
    name = "zmax_system2"

    def __init__(self, config: ZmaxSystem2Config, dataset_stats=None, dataset_info=None):
        super().__init__(config)
        self.config = config

        # 简化特征提取 (实际会加载 Phase 1-3 模型)
        self.feature_extractor = nn.Sequential(
            nn.Linear(6, config.action_hidden_size), nn.ReLU(),
            nn.Linear(config.action_hidden_size, config.action_hidden_size), nn.ReLU(),
        )

        # Phase 4: 任务规划器
        self.task_planner = TaskPlanner(config)

        # Phase 4: 多产线协调
        self.coordinator = MultiLineCoordinator(
            config.max_concurrent_lines, config.line_status_dim, config.action_hidden_size)

        # 动作预测头
        self.action_head = nn.Sequential(
            nn.Linear(config.action_hidden_size, config.action_hidden_size),
            nn.ReLU(),
            nn.Linear(config.action_hidden_size, 7),
        )

        self._dummy = nn.Parameter(torch.zeros(1))

    def forward(self, batch: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
        device = self._dummy.device
        state = batch.get("observation.state", torch.zeros(1, 6, device=device))
        if state.device != device:
            state = state.to(device)
        B = state.shape[0]

        # 1. 特征提取
        features = self.feature_extractor(state)

        # 2. 多产线协调
        features = self.coordinator(features, line_statuses=None)

        # 3. 任务规划 + 子系统路由
        task_steps, route_weights = self.task_planner(features)

        # 4. 根据路由权重融合子系统的输出 (简化: 直接用全局特征)
        pred_actions = self.action_head(features)

        # Loss
        loss = torch.tensor(0.0, device=device, requires_grad=True)
        if "action" in batch:
            target = batch["action"][:, 0, :7] if batch["action"].dim() > 2 else batch["action"][:, :7]
            if target.shape[-1] >= 7:
                loss = F.mse_loss(pred_actions, target[:, :7])

        return {
            "loss": loss,
            "action": pred_actions,
            "task_steps": task_steps,
            "route_weights": route_weights,
            "routing_decision": {
                "sys1": route_weights[:, 0].mean().item(),
                "sys11": route_weights[:, 1].mean().item(),
                "sys12": route_weights[:, 2].mean().item(),
            },
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
