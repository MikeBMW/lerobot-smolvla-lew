"""jepa_encoder.py — JEPA 编码器: (s) → z"""
import torch.nn as nn

class JEPAEncoder(nn.Module):
    def __init__(self, in_dim, z_dim):
        super().__init__()
        self.enc = nn.Sequential(
            nn.Linear(in_dim, z_dim*2), nn.GELU(),
            nn.Linear(z_dim*2, z_dim), nn.LayerNorm(z_dim))
    def forward(self, x, prior=None):
        if prior is not None: x = x + prior
        return self.enc(x)
