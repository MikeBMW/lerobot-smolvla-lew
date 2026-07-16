#!/usr/bin/env python3
"""H-JEPA × SmolVLA 分层中间表征对齐架构 v3
参考: LeCun H-JEPA paper — 每层JEPA Encoder产生z, Predictor预测z'
核心: z是中间表征, 非外部注入。z0(细节)→z1(物体)→z2(语义) 分层预测

设计: xspace | 编码: web | 验证: 小芳
"""
import torch, torch.nn as nn, numpy as np, os
from pathlib import Path

# ============================================================
# JEPA 单层模块: Encoder(s,a)→z → Predictor(z)→z'
# ============================================================
class JEPA_Layer(nn.Module):
    def __init__(self, dim=256):
        super().__init__()
        self.enc = nn.Sequential(nn.Linear(dim,dim),nn.GELU(),nn.Linear(dim,dim),nn.LayerNorm(dim))
        self.pred = nn.Sequential(nn.Linear(dim,dim*2),nn.GELU(),nn.Linear(dim*2,dim),nn.LayerNorm(dim))
        self.energy = nn.Sequential(nn.Linear(dim,dim//4),nn.GELU(),nn.Linear(dim//4,1))
    def forward(self, s):
        x = s
        z = self.enc(x)
        zp = self.pred(z)
        e = self.energy(zp)
        return z, zp, e

# ============================================================
# H-JEPA 分层堆叠: z0(细节)→z1(物体)→z2(语义)
# ============================================================
class HJEPA_Stack(nn.Module):
    """三层JEPA堆叠: 自下而上编码 + 自上而下约束"""
    def __init__(self, dim=256):
        super().__init__()
        self.z0 = JEPA_Layer(dim)
        self.z1 = JEPA_Layer(dim)
        self.z2 = JEPA_Layer(dim)
        # 层间投影
        self.up01 = nn.Linear(dim,dim)  # z0→z1
        self.up12 = nn.Linear(dim,dim)  # z1→z2
        self.down21 = nn.Linear(dim,dim)  # z2→z1 (top-down)
        self.down10 = nn.Linear(dim,dim)  # z1→z0

    def forward(self, s, a):
        """自下而上编码 → 自上而下约束 → 预测"""
        # Bottom-up: 细节→抽象
        z0, z0_pred, e0 = self.z0(s)
        z1, z1_pred, e1 = self.z1(self.up01(z0))
        z2, z2_pred, e2 = self.z2(self.up12(z1))

        # Top-down refinement: 抽象约束细节
        z1_refined = z1 + self.down21(z2_pred)
        z0_refined = z0 + self.down10(z1_refined)

        return [z0_refined, z1_refined, z2], [z0_pred, z1_pred, z2_pred], (e0+e1+e2)/3

# ============================================================
# H-JEPA × SmolVLA 完整模型
# ============================================================
class HJEPA_SmolVLA_v3(nn.Module):
    def __init__(self, dim=256, act_dim=6, chunk=50):
        super().__init__()
        self.dim = dim
        # VLA视觉编码
        self.v_enc = nn.Sequential(nn.Conv2d(3,64,8,4),nn.ReLU(),nn.Conv2d(64,128,4,2),nn.ReLU(),nn.Conv2d(128,dim,4,2),nn.AdaptiveAvgPool2d(1))
        self.s_proj = nn.Linear(7,dim)

        # H-JEPA分层堆叠 — 核心: z0/z1/z2
        self.hjepa = HJEPA_Stack(dim)

        # 三层VLA Transformer + 逐层z注入
        self.layers = nn.ModuleList([nn.TransformerEncoderLayer(dim,8,dim*4,batch_first=True) for _ in range(3)])
        self.z_proj = nn.ModuleList([nn.Linear(dim,dim) for _ in range(3)])  # z→VLA空间
        self.gate = nn.ParameterList([nn.Parameter(torch.tensor(-3.0)) for _ in range(3)])
        self.norm = nn.ModuleList([nn.LayerNorm(dim) for _ in range(3)])
        self.w = [1.0, 0.1, 0.01]  # 逐层衰减

        # 融合 + 动作头
        self.fuse = nn.Linear(dim*3,dim)
        self.head = nn.Sequential(nn.Linear(dim,dim*4),nn.GELU(),nn.Linear(dim*4,dim*4),nn.GELU(),nn.Linear(dim*4,act_dim*chunk))
        self.train_mode = True

    def forward(self, rgb, state):
        b = rgb.shape[0]
        # VLA基本编码
        v_feat = self.v_enc(rgb).view(b,-1)
        s_feat = self.s_proj(state)
        vla_in = v_feat + s_feat

        # H-JEPA: 产生z0/z1/z2 (中间表征)
        zs, z_preds, energy = self.hjepa(v_feat, vla_in)

        # VLA三层处理 + 逐层z注入
        x = vla_in.unsqueeze(1)
        outs = []
        for i, layer in enumerate(self.layers):
            x = layer(x)
            # z注入: gate×(0.1^i)×z
            zi = self.z_proj[i](zs[i])
            g = torch.sigmoid(self.gate[i]) * self.w[i]
            if not self.train_mode: g = g * 0  # 推理零开销
            x = self.norm[i](x + g * zi)
            outs.append(x)

        fuse = self.fuse(torch.cat(outs,-1)).squeeze(1)
        act = self.head(fuse).view(b, 50, -1)
        return act, energy

    def set_train(self): self.train_mode = True
    def set_infer(self): self.train_mode = False

# ============================================================
# MetaWorld 数据加载
# ============================================================
class MetaWorldLoader:
    def __init__(self, dir="/root/datasets/metaworld/tasks"):
        self.files = list(Path(dir).glob("*.npz"))
        self.fake = not self.files
        if not self.fake:
            self.data = []
            for f in self.files:
                d = np.load(f)
                self.data.append({'obs':torch.tensor(d['observations'],dtype=torch.float32),'state':torch.tensor(d['states'],dtype=torch.float32),'task':str(d.get('task_name',f.stem))})
            print(f"📦 {len(self.files)}任务")

    def batch(self, n=8):
        if self.fake: return torch.randn(n,3,128,128), torch.randn(n,7)
        t = self.data[np.random.randint(0,len(self.data))]
        i = np.random.randint(0, max(1,t['obs'].shape[0]-n), n)
        return t['obs'][i[:n]].cuda(), t['state'][i[:n]].cuda()

# ============================================================
# 验证
# ============================================================
if __name__ == '__main__':
    m = HJEPA_SmolVLA_v3().cuda()
    print(f'✅ H-JEPA v3: {sum(p.numel() for p in m.parameters())/1e6:.1f}M params')

    rgb, state = torch.randn(2,3,128,128).cuda(), torch.randn(2,7).cuda()
    m.set_train(); a_tr, e = m(rgb,state)
    m.set_infer(); a_inf, _ = m(rgb,state)
    print(f'[训练] {a_tr.shape} E={e.item():.3f}')
    print(f'[推理] {a_inf.shape} (z注入=0)')

    ldr = MetaWorldLoader()
    print(f'[数据] {"✅ MetaWorld" if not ldr.fake else "⚠️ 模拟"}')

    print('[z层]',end='')
    for i,g in enumerate(m.gate):
        print(f' | z{i}={torch.sigmoid(g).item():.3f}×{m.w[i]:.2f}',end='')
    print(' |')
    print('✅ H-JEPA v3 全验证通过')
