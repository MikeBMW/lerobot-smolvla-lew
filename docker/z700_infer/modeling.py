#!/usr/bin/env python3
"""Z700 双脑网络定义 (部署用, 从 modeling_left_right.py 提取)
左脑: obs → 4D 动作; 右脑: (obs, act) → next_obs + contact 判断
"""
import torch
import torch.nn as nn


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
    """右脑: (obs, act) → next_obs 预测 + contact 判断 (抓取时机)"""
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
