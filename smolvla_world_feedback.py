#!/usr/bin/env python3
"""SmolVLA + LeWM 潜空间逐层交叉反馈融合 (VLA-JEPA 风格)
架构: SmolVLA主干预测action ← 每层Cross-Attn注入LeWM潜状态
"""
import torch, torch.nn as nn, math

class LayerWiseWorldFeedback(nn.Module):
    """逐层世界模型反馈注入器
    在SmolVLA的每一层处理中，通过Cross-Attention注入LeWM预测的潜状态。
    形成分布式多反馈回路: 每层都能看到世界模型对未来状态的预测。
    """
    def __init__(self, vla_dim=512, wm_dim=256, num_layers=4, heads=8):
        super().__init__()
        # 世界模型 → VLA维度对齐
        self.wm_proj = nn.Linear(wm_dim, vla_dim)
        # 每层独立的Cross-Attention
        self.cross_attns = nn.ModuleList([
            nn.MultiheadAttention(vla_dim, heads, batch_first=True)
            for _ in range(num_layers)
        ])
        # 每层的门控融合 (学习多少世界模型信息要注入)
        self.gates = nn.ParameterList([
            nn.Parameter(torch.zeros(1,1,vla_dim))
            for _ in range(num_layers)
        ])
        # 层归一化
        self.layer_norms = nn.ModuleList([
            nn.LayerNorm(vla_dim) for _ in range(num_layers)
        ])

    def forward(self, vla_features, wm_latents):
        """
        vla_features: List[Tensor(b,seq,vla_dim)] — SmolVLA每层输出
        wm_latents:   Tensor(b,t,wm_dim) — LeWM预测的潜状态序列
        """
        wm_proj = self.wm_proj(wm_latents)  # (b,t,vla_dim)
        enhanced = []
        for i, vla_feat in enumerate(vla_features):
            # Cross-Attn: VLA features attend to world model predictions
            attended, _ = self.cross_attns[i](vla_feat, wm_proj, wm_proj)
            # 门控融合: sigmoid gate controls how much WM info to inject
            gate = torch.sigmoid(self.gates[i])
            fused = vla_feat + gate * attended
            enhanced.append(self.layer_norms[i](fused))
        return enhanced

class SmolVLA_WorldFeedback(nn.Module):
    """SmolVLA + 逐层世界模型反馈 = VLA-JEPA-like 架构
    训练时: LeWM预测未来潜状态注入每层
    推理时: 可选剥离LeWM (降低延迟)
    """
    def __init__(self, vla_dim=256, wm_dim=256, action_dim=6, chunk=50):
        super().__init__()
        # VLA主干 (简化版 SmolVLA)
        self.vla_encoder = nn.Sequential(
            nn.Conv2d(3,64,8,4), nn.ReLU(),
            nn.Conv2d(64,128,4,2), nn.ReLU(),
            nn.Conv2d(128,256,4,2), nn.AdaptiveAvgPool2d(1))
        self.state_proj = nn.Linear(7, vla_dim)
        # 世界模型
        self.world_model = nn.GRU(vla_dim, wm_dim, 2, batch_first=True)
        self.wm_predictor = nn.Linear(wm_dim, vla_dim)
        # 逐层反馈
        self.num_layers = 3
        self.vla_layers = nn.ModuleList([
            nn.TransformerEncoderLayer(d_model=vla_dim, nhead=8, batch_first=True)
            for _ in range(self.num_layers)
        ])
        self.feedback = LayerWiseWorldFeedback(vla_dim, wm_dim, self.num_layers)
        # DiT 动作头
        self.action_head = nn.Sequential(
            nn.Linear(vla_dim, vla_dim*4), nn.ReLU(),
            nn.Linear(vla_dim*4, action_dim*chunk))

    def forward(self, rgb, state, use_wm=True):
        """
        rgb:   (b,3,H,W) — 当前帧
        state: (b,7)     — 当前关节状态
        """
        b = rgb.shape[0]
        # VLA编码
        vfeat = self.vla_encoder(rgb).view(b, -1)
        sfeat = self.state_proj(state)
        vla_in = (vfeat + sfeat).unsqueeze(1)  # (b,1,vla_dim)

        # 逐层VLA处理 + 世界模型预测
        layer_outputs = []
        wm_hidden = None
        for i, layer in enumerate(self.vla_layers):
            vla_out = layer(vla_in)  # (b,1,vla_dim)
            layer_outputs.append(vla_out)
            # LeWM预测下一步潜状态
            if use_wm:
                wm_out, wm_hidden = self.world_model(vla_out, wm_hidden)

        # 逐层交叉反馈: 每层的WM输出注入到每层的VLA特征
        if use_wm:
            wm_feats = torch.cat([self.wm_predictor(wm_out).unsqueeze(1) for _ in range(self.num_layers)], dim=1)
            layer_outputs = self.feedback(layer_outputs, wm_feats)

        # 融合所有层输出
        fused = torch.stack(layer_outputs, dim=1).mean(dim=1)
        action = self.action_head(fused).view(b, 50, 6)
        return action

    def inference(self, rgb, state):
        """推理模式: 剥离世界模型, 仅VLA主干+动作头"""
        return self.forward(rgb, state, use_wm=False)

if __name__ == '__main__':
    model = SmolVLA_WorldFeedback().cuda()
    rgb = torch.randn(2,3,128,128).cuda()
    state = torch.randn(2,7).cuda()
    # 训练模式
    action_train = model(rgb, state, use_wm=True)
    # 推理模式 (无世界模型)
    action_infer = model.inference(rgb, state)
    params = sum(p.numel() for p in model.parameters())
    print(f'✅ SmolVLA+WorldFeedback: {params/1e6:.1f}M params')
    print(f'   训练模式 action: {action_train.shape}')
    print(f'   推理模式 action: {action_infer.shape}')
