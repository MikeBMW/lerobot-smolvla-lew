"""Z-MAX LeftRight 建模: 左脑MLP动作 + 右脑WorldModel判断 + 状态机
2026-08-10 老倪: 成功模型 (抓起8/8 插入7/8) 按 lerobot 标准封装

架构:
  左脑 LeftBrainMLP:  obs → 4D 动作 (MLP偏置接近)
  右脑 RightBrainWM:  obs+action → next obs + contact判断 (该抓了吗, acc 1.00)
  状态机: 接近→抓取→抬起→转移→插入 (推理时编排)
"""
from __future__ import annotations
import os
from typing import Optional

import torch
import torch.nn as nn
import numpy as np

try:
    from lerobot.policies.pretrained import PreTrainedPolicy
    from .configuration_left_right import LeftRightConfig
    _HAS_LEROBOT = True
except ImportError:
    _HAS_LEROBOT = False
    from dataclasses import dataclass, field
    @dataclass
    class PreTrainedPolicy:
        config: object = None
        def from_pretrained(cls, *a, **k): raise NotImplementedError
    @dataclass
    class LeftRightConfig:
        left_hidden: int = 512
        right_hidden: int = 256
        grasp_contact_threshold: float = 0.5
        grasp_d_hp: float = 0.06
        lift_height: float = 0.08
        transfer_tolerance: float = 0.05
        insert_tolerance: float = 0.05
        n_obs_steps: int = 1
        chunk_size: int = 1
        n_action_steps: int = 1
        input_features: dict = field(default_factory=dict)
        output_features: dict = field(default_factory=dict)


class LeftBrainMLP(nn.Module):
    """左脑: obs → 4D 动作 (连续动作生成)"""
    def __init__(self, obs_dim=39, act_dim=4, hidden=512):
        super().__init__()
        self.obs_dim = obs_dim
        self.act_dim = act_dim
        self.net = nn.Sequential(
            nn.Linear(obs_dim, hidden), nn.ReLU(), nn.Dropout(0.1),
            nn.Linear(hidden, hidden), nn.ReLU(), nn.Dropout(0.1),
            nn.Linear(hidden, hidden), nn.ReLU(),
            nn.Linear(hidden, act_dim))
    def forward(self, x):
        return self.net(x)


class RightBrainWM(nn.Module):
    """右脑: obs + action → next obs + contact判断 (抓取时机)"""
    def __init__(self, obs_dim=39, act_dim=4, hidden=256):
        super().__init__()
        self.enc = nn.Sequential(
            nn.Linear(obs_dim + act_dim, hidden), nn.ReLU(),
            nn.Linear(hidden, hidden), nn.ReLU())
        self.pred_next = nn.Linear(hidden, obs_dim)
        self.contact_head = nn.Linear(hidden, 1)
    def forward(self, obs, act):
        h = self.enc(torch.cat([obs, act], dim=-1))
        next_obs = self.pred_next(h)
        contact = torch.sigmoid(self.contact_head(h))
        return next_obs, contact


class LeftRightPolicy(PreTrainedPolicy):
    """双脑策略: 左脑动作 + 右脑判断 (lerobot 标准 PreTrainedPolicy)"""
    config_class = LeftRightConfig  # lerobot 标准要求
    name = "left_right"            # lerobot 标准要求

    def __init__(self, config: Optional[LeftRightConfig] = None):
        config = config or LeftRightConfig()
        self.config = config
        super().__init__(config)  # 2026-08-10: 必须先 super (模块赋值要求)
        # 维度: 从 config.input_features 读, 默认 39D obs / 4D act
        obs_dim = 39
        act_dim = 4
        if config.input_features:
            obs_dim = config.input_features.get("observation.state", [39])[0] if isinstance(
                config.input_features.get("observation.state", [39]), (list, tuple)) else 39
            act_dim = config.output_features.get("action", [4])[0] if isinstance(
                config.output_features.get("action", [4]), (list, tuple)) else 4
        self.left = LeftBrainMLP(obs_dim, act_dim, config.left_hidden)
        self.right = RightBrainWM(obs_dim, act_dim, config.right_hidden)

    def forward(self, batch, **kwargs):
        """训练: 左脑动作回归 + 右脑 next/contact 预测
        batch: {"observation.state": [B, T, obs_dim], "action": [B, T, act_dim]}
        返回: {"action": [B, T, act_dim]} (标准 lerobot 输出)
        """
        obs = batch["observation.state"].float()
        if obs.ndim == 3:
            obs = obs[:, -1]  # 取最后 obs step
        act = batch["action"].float()
        if act.ndim == 3:
            act_flat = act[:, -1]
        else:
            act_flat = act
        # 左脑动作预测
        pred_act = self.left(obs)
        # 右脑判断 (辅助 loss 用, 推理不需要)
        if self.training and "next_state" in batch:
            next_s = batch["next_state"].float()
            if next_s.ndim == 3:
                next_s = next_s[:, -1]
            pred_next, pred_cont = self.right(obs, act_flat)
            # 右脑 loss 附加 (contact 标签由调用方提供)
            self._right_loss = nn.functional.mse_loss(pred_next, next_s)
        # 标准输出: action (无 chunk, 1 步)
        out = pred_act.unsqueeze(1) if pred_act.ndim == 2 else pred_act
        return {"action": out}

    def select_action(self, batch, **kwargs):
        """推理: 返回动作 (供 env 执行)"""
        self.eval()
        obs = batch["observation.state"].float()
        if obs.ndim == 3:
            obs = obs[:, -1]
        with torch.no_grad():
            pred_act = self.left(obs)
        return pred_act

    def get_right_contact(self, obs, act):
        """右脑 contact 判断 (状态机用)"""
        self.eval()
        with torch.no_grad():
            _, contact = self.right(obs, act)
        return contact

    def compute_loss(self, batch, **kwargs):
        """lerobot 标准 loss 接口"""
        out = self.forward(batch, **kwargs)
        act = batch["action"].float()
        if act.ndim == 3:
            act = act[:, -1]
        loss = nn.functional.mse_loss(out["action"].squeeze(1), act)
        right_loss = getattr(self, "_right_loss", None)
        if right_loss is not None:
            loss = loss + 0.5 * right_loss
        return {"loss": loss}

    def reset(self):
        """重置状态 (lerobot 标准, 无内部状态)"""
        pass

    def get_optim_params(self):
        """优化器参数 (lerobot 标准)"""
        return {"params": list(self.left.parameters()) + list(self.right.parameters())}

    def predict_action_chunk(self, observation, **kwargs):
        """预测动作块 (lerobot 标准: [B, n_action_steps, act_dim])"""
        obs = observation["observation.state"].float()
        if obs.ndim == 3:
            obs = obs[:, -1]
        with torch.no_grad():
            pred = self.left(obs)
        return pred.unsqueeze(1)  # [B, 1, act_dim]

    def save_pretrained(self, save_directory, **kwargs):
        """保存 (lerobot 标准)"""
        os.makedirs(save_directory, exist_ok=True)
        # config.json
        import json
        cfg = {
            "type": "left_right",
            "left_hidden": self.config.left_hidden,
            "right_hidden": self.config.right_hidden,
            "grasp_contact_threshold": self.config.grasp_contact_threshold,
            "grasp_d_hp": self.config.grasp_d_hp,
            "lift_height": self.config.lift_height,
            "transfer_tolerance": self.config.transfer_tolerance,
            "insert_tolerance": self.config.insert_tolerance,
            "n_obs_steps": self.config.n_obs_steps,
            "chunk_size": self.config.chunk_size,
            "n_action_steps": self.config.n_action_steps,
            "input_features": self.config.input_features,
            "output_features": self.config.output_features,
        }
        with open(os.path.join(save_directory, "config.json"), "w") as f:
            json.dump(cfg, f, indent=2)
        # 权重
        torch.save({
            "left": self.left.state_dict(),
            "right": self.right.state_dict(),
            "obs_dim": self.left.obs_dim,
            "act_dim": self.left.act_dim,
        }, os.path.join(save_directory, "model.pt"))

    @classmethod
    def from_pretrained(cls, pretrained_path, **kwargs):
        """加载 (lerobot 标准)"""
        import json
        cfg_path = os.path.join(pretrained_path, "config.json")
        if os.path.exists(cfg_path):
            with open(cfg_path) as f:
                cfg_data = json.load(f)
        else:
            cfg_data = {}
        config = LeftRightConfig(
            left_hidden=cfg_data.get("left_hidden", 512),
            right_hidden=cfg_data.get("right_hidden", 256),
            grasp_contact_threshold=cfg_data.get("grasp_contact_threshold", 0.5),
            grasp_d_hp=cfg_data.get("grasp_d_hp", 0.06),
            lift_height=cfg_data.get("lift_height", 0.08),
            transfer_tolerance=cfg_data.get("transfer_tolerance", 0.05),
            insert_tolerance=cfg_data.get("insert_tolerance", 0.05),
            input_features=cfg_data.get("input_features", {}),
            output_features=cfg_data.get("output_features", {}),
        )
        policy = cls(config)
        model_path = os.path.join(pretrained_path, "model.pt")
        if os.path.exists(model_path):
            data = torch.load(model_path, map_location="cpu", weights_only=False)
            policy.left.load_state_dict(data["left"])
            policy.right.load_state_dict(data["right"])
        return policy
