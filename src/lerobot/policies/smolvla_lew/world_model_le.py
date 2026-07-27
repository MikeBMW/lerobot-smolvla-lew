# Copyright 2026 The HuggingFace Inc. team. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
LeWorldModel for SmolVLA-LEW

Adapted from https://github.com/lucas-maes/le-wm
Integration: Uses SmolVLM's SigLIP vision encoder for observation embeddings
Architecture: AdaLN-zero conditioned Transformer for next-frame prediction
"""

import torch
import torch.nn.functional as F
from torch import nn


# ============================================================================
# 新增：LeWorldModel 核心组件（从 le-wm 适配）
# ============================================================================


def modulate(x, shift, scale):
    """AdaLN-zero modulation"""
    return x * (1 + scale) + shift


class FeedForward(nn.Module):
    """FeedForward network used in Transformers"""

    def __init__(self, dim, hidden_dim, dropout=0.0):
        super().__init__()
        self.net = nn.Sequential(
            nn.LayerNorm(dim),
            nn.Linear(dim, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, dim),
            nn.Dropout(dropout),
        )

    def forward(self, x):
        return self.net(x)


class Attention(nn.Module):
    """Scaled dot-product attention with causal masking"""

    def __init__(self, dim, heads=8, dim_head=64, dropout=0.0):
        super().__init__()
        inner_dim = dim_head * heads
        project_out = not (heads == 1 and dim_head == dim)
        self.heads = heads
        self.scale = dim_head**-0.5
        self.dropout = dropout
        self.norm = nn.LayerNorm(dim)
        self.to_qkv = nn.Linear(dim, inner_dim * 3, bias=False)
        self.to_out = (
            nn.Sequential(nn.Linear(inner_dim, dim), nn.Dropout(dropout))
            if project_out
            else nn.Identity()
        )

    def forward(self, x, causal=True):
        """
        x : (B, T, D)
        """
        x = self.norm(x)
        drop = self.dropout if self.training else 0.0
        qkv = self.to_qkv(x).chunk(3, dim=-1)
        q, k, v = (t.reshape(t.shape[0], t.shape[1], self.heads, -1).permute(0, 2, 1, 3) for t in qkv)
        out = F.scaled_dot_product_attention(q, k, v, dropout_p=drop, is_causal=causal)
        out = out.permute(0, 2, 1, 3).reshape(out.shape[0], out.shape[2], -1)
        return self.to_out(out)


class ConditionalBlock(nn.Module):
    """Transformer block with AdaLN-zero conditioning"""

    def __init__(self, dim, heads, dim_head, mlp_dim, dropout=0.0):
        super().__init__()

        self.attn = Attention(dim, heads=heads, dim_head=dim_head, dropout=dropout)
        self.mlp = FeedForward(dim, mlp_dim, dropout=dropout)
        self.norm1 = nn.LayerNorm(dim, elementwise_affine=False, eps=1e-6)
        self.norm2 = nn.LayerNorm(dim, elementwise_affine=False, eps=1e-6)
        self.adaLN_modulation = nn.Sequential(
            nn.SiLU(), nn.Linear(dim, 6 * dim, bias=True)
        )

        nn.init.constant_(self.adaLN_modulation[-1].weight, 0)
        nn.init.constant_(self.adaLN_modulation[-1].bias, 0)

    def forward(self, x, c):
        shift_msa, scale_msa, gate_msa, shift_mlp, scale_mlp, gate_mlp = (
            self.adaLN_modulation(c).chunk(6, dim=-1)
        )
        x = x + gate_msa * self.attn(modulate(self.norm1(x), shift_msa, scale_msa))
        x = x + gate_mlp * self.mlp(modulate(self.norm2(x), shift_mlp, scale_mlp))
        return x


class Transformer(nn.Module):
    """Transformer with AdaLN-zero blocks"""

    def __init__(
        self,
        input_dim,
        hidden_dim,
        output_dim,
        depth,
        heads,
        dim_head,
        mlp_dim,
        dropout=0.0,
    ):
        super().__init__()
        self.norm = nn.LayerNorm(hidden_dim)
        self.layers = nn.ModuleList([])

        self.input_proj = (
            nn.Linear(input_dim, hidden_dim)
            if input_dim != hidden_dim
            else nn.Identity()
        )

        self.cond_proj = (
            nn.Linear(input_dim, hidden_dim)
            if input_dim != hidden_dim
            else nn.Identity()
        )

        self.output_proj = (
            nn.Linear(hidden_dim, output_dim)
            if hidden_dim != output_dim
            else nn.Identity()
        )

        for _ in range(depth):
            self.layers.append(
                ConditionalBlock(hidden_dim, heads, dim_head, mlp_dim, dropout)
            )

    def forward(self, x, c=None):
        if hasattr(self, "input_proj"):
            x = self.input_proj(x)

        if c is not None and hasattr(self, "cond_proj"):
            c = self.cond_proj(c)

        for block in self.layers:
            x = block(x, c)
        x = self.norm(x)

        if hasattr(self, "output_proj"):
            x = self.output_proj(x)
        return x


class Embedder(nn.Module):
    """Action embedding network"""
    
    def __init__(
        self,
        input_dim=10,
        smoothed_dim=10,
        emb_dim=10,
        mlp_scale=4,
    ):
        super().__init__()
        self.patch_embed = nn.Conv1d(input_dim, smoothed_dim, kernel_size=1, stride=1)
        self.embed = nn.Sequential(
            nn.Linear(smoothed_dim, mlp_scale * emb_dim),
            nn.SiLU(),
            nn.Linear(mlp_scale * emb_dim, emb_dim),
        )

    def forward(self, x):
        """
        x: (B, T, D)
        """
        x = x.float()
        x = x.permute(0, 2, 1)
        x = self.patch_embed(x)
        x = x.permute(0, 2, 1)
        x = self.embed(x)
        return x


class ARPredictor(nn.Module):
    """Autoregressive predictor for next-step embedding prediction."""

    def __init__(
        self,
        *,
        num_frames,
        depth,
        heads,
        mlp_dim,
        input_dim,
        hidden_dim,
        output_dim=None,
        dim_head=64,
        dropout=0.0,
        emb_dropout=0.0,
    ):
        super().__init__()
        self.pos_embedding = nn.Parameter(torch.randn(1, num_frames, input_dim))
        self.dropout = nn.Dropout(emb_dropout)
        self.transformer = Transformer(
            input_dim,
            hidden_dim,
            output_dim or input_dim,
            depth,
            heads,
            dim_head,
            mlp_dim,
            dropout,
        )

    def forward(self, x, c):
        """
        x: (B, T, d) - observation embeddings
        c: (B, T, act_dim) - action embeddings (conditioning)
        """
        T = x.size(1)
        x = x + self.pos_embedding[:, :T]
        x = self.dropout(x)
        x = self.transformer(x, c)
        return x


# ============================================================================
# 新增：LeWorldModel 封装类（用于 SmolVLA-LEW）
# ============================================================================


class LeWorldModel(nn.Module):
    """
    LeWorldModel for SmolVLA-LEW
    
    Uses SmolVLM's SigLIP vision encoder to extract per-frame CLS embeddings,
    then predicts next-frame embeddings using action-conditioned ARPredictor.
    
    Input:
        - videos: [B, V, T, C, H, W] video frames
        - actions: [B, T, action_dim] action sequence
        
    Output:
        - lew_loss: scalar L1 loss between predicted and actual next-frame embeddings
    """

    def __init__(
        self,
        vision_encoder,
        action_dim,
        obs_embed_dim,
        hidden_dim=192,
        num_layers=6,
        num_heads=8,
        dim_head=64,
        mlp_dim=768,
        num_frames=2,
        dropout=0.0,
    ):
        super().__init__()
        
        # Vision encoder (from SmolVLM's SigLIP)
        self.vision_encoder = vision_encoder
        
        # Action encoder
        self.action_encoder = Embedder(
            input_dim=action_dim,
            smoothed_dim=action_dim,
            emb_dim=obs_embed_dim,
            mlp_scale=4,
        )
        
        # ARPredictor
        self.predictor = ARPredictor(
            num_frames=num_frames,
            depth=num_layers,
            heads=num_heads,
            mlp_dim=mlp_dim,
            input_dim=obs_embed_dim,
            hidden_dim=hidden_dim,
            output_dim=obs_embed_dim,
            dim_head=dim_head,
            dropout=dropout,
        )
        
        # Projector for vision encoder output
        self.projector = nn.Linear(
            vision_encoder.config.vision_config.hidden_size, 
            obs_embed_dim
        )
        
    def encode_frame(self, pixel_values):
        """
        Encode a single frame through SigLIP vision encoder
        
        Args:
            pixel_values: [B, C, H, W]
            
        Returns:
            embeddings: [B, obs_embed_dim] - CLS token embeddings
        """
        # SigLIP vision encoder forward
        vision_outputs = self.vision_encoder(pixel_values=pixel_values)
        # Get CLS token (first token)
        cls_token = vision_outputs.last_hidden_state[:, 0, :]
        # Project to obs_embed_dim
        embeddings = self.projector(cls_token)
        return embeddings
    
    def forward(self, videos, actions):
        """
        Compute LeWorldModel loss
        
        Args:
            videos: [B, V, T, C, H, W] - batch of videos (V views, T frames)
            actions: [B, T, action_dim] - action sequence
            
        Returns:
            lew_loss: scalar L1 loss
        """
        B, V, T, C, H, W = videos.shape
        
        # ====== 新增：取第一视角进行编码（简化多视角处理） ======
        frames = videos[:, 0, :, :, :, :]  # [B, T, C, H, W]
        frames_flat = frames.reshape(B * T, C, H, W)
        
        # 通过SigLIP视觉编码器提取每帧CLS嵌入
        with torch.no_grad():
            frame_emb = self.encode_frame(frames_flat)  # [B*T, obs_dim]
        
        frame_emb = frame_emb.reshape(B, T, -1)  # [B, T, obs_dim]
        
        # 编码动作序列
        act_emb = self.action_encoder(actions.float())  # [B, T, obs_dim]
        
        # Shift-by-one拆分：input=帧0..T-2, target=帧1..T-1
        input_emb = frame_emb[:, :-1, :]   # [B, T-1, obs_dim]
        target_emb = frame_emb[:, 1:, :]   # [B, T-1, obs_dim]
        input_act = act_emb[:, :-1, :]      # [B, T-1, obs_dim]
        
        # 自回归预测下一帧嵌入
        pred_emb = self.predictor(input_emb, input_act)  # [B, T-1, obs_dim]
        
        # L1损失
        lew_loss = F.l1_loss(pred_emb, target_emb, reduction="mean")
        
        return lew_loss
    
    @torch.no_grad()
    def rollout(self, init_frame, action_sequence):
        """
        自回归推理：给定初始帧和动作序列，预测未来帧嵌入
        
        Args:
            init_frame: [B, V, C, H, W] - 初始观测帧（单帧）
            action_sequence: [B, T, action_dim] - 未来 T 步动作序列
            
        Returns:
            rollout_emb: [B, T+1, obs_embed_dim] - 初始帧 + T 个预测帧的嵌入
        """
        B = init_frame.shape[0]
        T = action_sequence.shape[1]
        
        # 编码初始帧
        # 取第一视角
        init_pixel = init_frame[:, 0, :, :, :]  # [B, C, H, W]
        init_emb = self.encode_frame(init_pixel)  # [B, obs_dim]
        init_emb = init_emb.unsqueeze(1)  # [B, 1, obs_dim]
        
        # 编码整个动作序列
        act_emb = self.action_encoder(action_sequence.float())  # [B, T, obs_dim]
        
        # 自回归预测
        rollout_emb_list = [init_emb]  # 从初始帧开始
        history_emb = init_emb  # [B, 1, obs_dim]
        
        for t in range(T):
            # 当前动作嵌入
            curr_act = act_emb[:, t:t+1, :]  # [B, 1, obs_dim]
            
            # 使用历史帧 + 当前动作进行预测
            # ARPredictor 输出整个序列的预测，我们取最后一个作为下一步预测
            pred_emb_full = self.predictor(history_emb, curr_act)  # [B, len, obs_dim]
            pred_emb = pred_emb_full[:, -1:, :]  # 取最后一个时间步的预测 [B, 1, obs_dim]
            
            rollout_emb_list.append(pred_emb)
            
            # 更新历史（追加预测帧）
            history_emb = torch.cat([history_emb, pred_emb], dim=1)  # [B, len+1, obs_dim]
            
            # 保持固定长度（可选，根据实际需求）
            max_len = self.predictor.pos_embedding.shape[1]
            if history_emb.shape[1] > max_len:
                history_emb = history_emb[:, -max_len:, :]  # 截断到最大长度
        
        # 合并所有嵌入
        rollout_emb = torch.cat(rollout_emb_list, dim=1)  # [B, T+1, obs_dim]
        
        return rollout_emb
