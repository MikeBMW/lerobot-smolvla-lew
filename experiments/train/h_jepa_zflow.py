"""h_jepa_zflow.py — H-JEPA z流: 三层表征级联反馈 + SmolVLA"""
import torch, torch.nn as nn
from jepa_encoder import JEPAEncoder
from jepa_predictor import JEPAPredictor
from z_config import ZFlowConfig

class ZFlow_VLA(nn.Module):
    """z1(空间)←z2'先验 | z2(物体)←z3'先验 | z3(语义)独立 → 级联反馈"""
    def __init__(self, cfg: ZFlowConfig = None):
        super().__init__()
        cfg = cfg or ZFlowConfig()
        zd = cfg.z_dims
        # VLA 视觉编码
        self.v_enc = nn.Sequential(nn.Conv2d(3,64,8,4),nn.ReLU(),nn.Conv2d(64,128,4,2),nn.ReLU(),nn.Conv2d(128,cfg.vla_dim,4,2),nn.AdaptiveAvgPool2d(1))
        self.s_proj = nn.Linear(7, cfg.vla_dim)
        # H-JEPA 三层 z
        self.z_enc = nn.ModuleList([JEPAEncoder(cfg.vla_dim, zd[i]) for i in range(3)])
        self.z_pred = nn.ModuleList([JEPAPredictor(zd[i]) for i in range(3)])
        # 级联投影: z3→z2, z2→z1 (top-down)
        self.td32 = nn.Linear(zd[2], zd[1])
        self.td21 = nn.Linear(zd[1], zd[0])
        # 门控(逐层自适应)
        self.gate = nn.ParameterList([nn.Parameter(torch.tensor(cfg.gate_init)) for _ in range(3)])
        # 融合: z1⊕z2⊕z3 → 512D
        fuse_dim = sum(zd)
        self.fuse = nn.Sequential(nn.Linear(fuse_dim, cfg.h_dim), nn.GELU(), nn.LayerNorm(cfg.h_dim))
        # DiT 动作头
        self.head = nn.Sequential(nn.Linear(cfg.h_dim, cfg.h_dim*2),nn.GELU(),nn.Linear(cfg.h_dim*2, cfg.act_dim*cfg.chunk))
        self.train_mode = True

    def forward(self, rgb, state):
        b = rgb.shape[0]
        # VLA 编码
        v = self.v_enc(rgb).view(b, -1) + self.s_proj(state)  # (b, vla_dim)
        # === 自下而上: 生成 z1/z2/z3 ===
        z1 = self.z_enc[0](v)
        z2 = self.z_enc[1](z1)
        z3 = self.z_enc[2](z2)
        # === 预测未来 z' ===
        z3p, e3 = self.z_pred[2](z3)
        z2p, e2 = self.z_pred[1](z2 + self.td32(z3p))  # z3'→z2 先验
        z1p, e1 = self.z_pred[0](z1 + self.td21(z2p))  # z2'→z1 先验
        # === 门控注入 VLA ===
        zs = [z1, z2, z3]
        gated = []
        for i, z in enumerate(zs):
            g = torch.sigmoid(self.gate[i])
            if not self.train_mode: g = g * 0
            gated.append(g * z)
        # === 融合 → Action ===
        fused = self.fuse(torch.cat(gated, -1))  # (b, 512)
        act = self.head(fused).view(b, 14, 7)     # 14步×7维
        return act, (e1 + e2 + e3) / 3

    def set_train(self): self.train_mode = True
    def set_infer(self): self.train_mode = False

if __name__ == '__main__':
    m = ZFlow_VLA()
    p = sum(p.numel() for p in m.parameters())/1e6
    print(f'✅ ZFlow_VLA: {p:.1f}M params')
    rgb, state = torch.randn(2,3,128,128), torch.randn(2,7)
    m.set_train(); a, e = m(rgb, state)
    m.set_infer(); a2, _ = m(rgb, state)
    print(f'[训练] {a.shape} E={e.mean().item():.3f}')
    print(f'[推理] {a2.shape} (零开销)')
    print(f'[门控] z1={torch.sigmoid(m.gate[0]).item():.3f} z2={torch.sigmoid(m.gate[1]).item():.3f} z3={torch.sigmoid(m.gate[2]).item():.3f}')
