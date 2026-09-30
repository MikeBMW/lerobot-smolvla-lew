"""Mamba SSM 增强模块 (自实现, 无外部依赖) — 状态空间模型核心: 选择性扫描
S6 简化: 离散 SSM h' = A h + B u; y = C h
选择性: B/C/Δ 由输入 x 经线性投影产生 (输入依赖 = Mamba 关键)
用于 LEW 世界模型混合 (消融: transformer only vs hybrid)
"""
import torch
from torch import nn
import torch.nn.functional as F


class SelectiveSSM(nn.Module):
    """选择性状态空间层 (单层) — Mamba 风格简化版

    对序列最后一维独立处理: 每个通道一个标量 SSM (diagonal A)。
    h_{t+1} = exp(A_bar) h_t + B_bar u_t     (A_bar = ΔA 离散化)
    y_t     = C h_t + D u_t
    """

    def __init__(self, d_model: int, d_state: int = 16, d_delta: int = 64):
        super().__init__()
        self.d_model = d_model
        self.d_state = d_state
        # 输入投影 (x → B, C, Δ 参数 + 门控分支)
        self.in_proj = nn.Linear(d_model, d_model * 2, bias=False)   # x → z(门控) + x_conv
        self.x_proj = nn.Linear(d_model, d_delta + d_state * 2, bias=False)  # → Δ, B, C 参数
        self.dt_proj = nn.Linear(d_delta, d_model, bias=True)        # Δ → 每通道时间尺度
        # A/logA 初始 (对角线, 负值保证稳定)
        A = torch.arange(1, d_state + 1, dtype=torch.float32).repeat(d_model, 1)
        self.register_buffer("A_log", torch.log(A))                  # (d_model, d_state)
        self.D = nn.Parameter(torch.ones(d_model))
        self.out_proj = nn.Linear(d_model, d_model, bias=False)
        self.act = nn.SiLU()
        nn.init.zeros_(self.dt_proj.bias)   # dt_proj 偏置让 Δ 初始≈0.5

    def forward(self, x):
        """x: (B, T, D) → (B, T, D) 因果时序处理"""
        B, T, D = x.shape
        # 门控 + 主分支
        zx = self.in_proj(x)                      # (B,T,2D)
        z, xb = zx.chunk(2, dim=-1)
        xb = self.act(xb)
        # 选择性参数
        xd = self.x_proj(xb)                      # (B,T,d_delta+2*d_state)
        delta, B_, C_ = xd.split([self.x_proj.out_features - self.d_state * 2,
                                  self.d_state, self.d_state], dim=-1)
        delta = F.softplus(self.dt_proj(delta))   # (B,T,D) 时间尺度 >0
        A = -torch.exp(self.A_log)                # (D,d_state) 稳定负对角
        # 离散化: A_bar = exp(ΔA) (对角线逐元素)
        dA = torch.exp(delta.unsqueeze(-1) * A.unsqueeze(0))   # (B,T,D,d_state)
        # 扫描 (顺序, 因果)
        h = torch.zeros(B, D, self.d_state, device=x.device)
        ys = []
        for t in range(T):
            dB = delta[:, t].unsqueeze(-1) * B_[:, t].unsqueeze(1)   # (B,D,d_state)
            h = dA[:, t] * h + dB * xb[:, t].unsqueeze(-1)
            y_t = (C_[:, t].unsqueeze(1) * h).sum(-1) + self.D * xb[:, t]
            ys.append(y_t)
        y = torch.stack(ys, dim=1)                # (B,T,D)
        y = self.act(y) * z                       # 门控输出
        return self.out_proj(y)


class MambaBlock(nn.Module):
    """Mamba 层 + 残差 + LayerNorm (替换/插入 Transformer 层用)"""

    def __init__(self, dim, d_state=16):
        super().__init__()
        self.norm = nn.LayerNorm(dim)
        self.ssm = SelectiveSSM(dim, d_state=d_state)

    def forward(self, x, c=None):
        return x + self.ssm(self.norm(x))


class HybridTransformerBlock(nn.Module):
    """混合块: 自注意力 (AdaLN 条件) + Mamba SSM 增强 (消融实验用)
    Transformer 块内插 SSM: attn 后接 ssm (不额外条件), 时序建模强化
    """

    def __init__(self, dim, heads, dim_head, mlp_dim, dropout=0.0, d_state=16):
        super().__init__()
        from lerobot.policies.smolvla_lew.world_model_le import Attention, FeedForward, modulate
        self._modulate = modulate
        self.attn = Attention(dim, heads=heads, dim_head=dim_head, dropout=dropout)
        self.ssm = SelectiveSSM(dim, d_state=d_state)
        self.mlp = FeedForward(dim, mlp_dim, dropout=dropout)
        self.norm1 = nn.LayerNorm(dim, elementwise_affine=False, eps=1e-6)
        self.norm2 = nn.LayerNorm(dim, elementwise_affine=False, eps=1e-6)
        self.norm3 = nn.LayerNorm(dim, elementwise_affine=False, eps=1e-6)
        self.adaLN_modulation = nn.Sequential(nn.SiLU(), nn.Linear(dim, 6 * dim, bias=True))
        nn.init.constant_(self.adaLN_modulation[-1].weight, 0)
        nn.init.constant_(self.adaLN_modulation[-1].bias, 0)

    def forward(self, x, c):
        _m = self._modulate
        shift_msa, scale_msa, gate_msa, shift_mlp, scale_mlp, gate_mlp = (
            self.adaLN_modulation(c).chunk(6, dim=-1)
        )
        x = x + gate_msa * self.attn(_m(self.norm1(x), shift_msa, scale_msa))
        # 🧠 Mamba SSM 增强: 无额外条件, 纯时序状态建模 (B,T,D) 因果
        x = x + self.ssm(self.norm2(x))
        x = x + gate_mlp * self.mlp(_m(self.norm3(x), shift_mlp, scale_mlp))
        return x
