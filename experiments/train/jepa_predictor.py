"""jepa_predictor.py — JEPA 预测器: z → z' + 能量评估"""
import torch.nn as nn

class JEPAPredictor(nn.Module):
    def __init__(self, z_dim):
        super().__init__()
        self.pred = nn.Sequential(
            nn.Linear(z_dim, z_dim*2), nn.GELU(),
            nn.Linear(z_dim*2, z_dim), nn.LayerNorm(z_dim))
        self.energy = nn.Sequential(
            nn.Linear(z_dim, z_dim//4), nn.GELU(),
            nn.Linear(z_dim//4, 1))
    def forward(self, z):
        zp = self.pred(z)
        e = self.energy(zp)
        return zp, e
