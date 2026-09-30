# Copyright 2026 The HuggingFace Inc. team. All rights reserved.
"""
Z-MAX Hybrid · 逐层交叉反馈融合

架构: SmolVLA Encoder → VLA Layer1→2→3 (每层Cross-Attn读WM潜空间Z)
      └── LeWM (GRU×2) → z₁(空间256D) z₂(物体256D) z₃(语义128D)
      → Feature Fusion → DiT → Action

训练: 三层门控激活 (gate₁=1.0 gate₂=0.1 gate₃=0.01)
推理: gate归零, WM剥离, 零额外开销
"""

from __future__ import annotations

import logging
from collections import deque

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch import Tensor

from lerobot.policies.pretrained import PreTrainedPolicy
from lerobot.policies.utils import populate_queues
from lerobot.utils.constants import ACTION, OBS_STATE
from lerobot.utils.import_utils import require_package

from .configuration_zmax_hybrid import ZmaxHybridConfig

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# LeWorldModel — GRU + 三层潜空间预测 + H-JEPA能量损失
# ═══════════════════════════════════════════════════════════════


class LeWorldModelGRU(nn.Module):
    """GRU世界模型: 编码历史状态 → 预测未来三层潜空间Z

    z₁: 256维 — 空间潜变 (物体在哪里)
    z₂: 256维 — 物体潜变 (是什么物体)
    z₃: 128维 — 语义潜变 (任务目标是什么)

    参考: LeWorldModel (Maes et al., 2026)
      - 论文: arXiv 2603.19312
      - 代码: https://github.com/lucas-maes/le-wm
      - 原理: JEPA (Joint Embedding Predictive Architecture)
      - 本实现: 将Transformer预测器改为GRU, 三层潜空间替代单层,
        保留H-JEPA能量损失, 适配LeRobot VLA管线
    """

    def __init__(self, config: ZmaxHybridConfig, obs_dim: int, ctx_dim: int):
        super().__init__()
        self.config = config

        # 观测编码: state + action → hidden
        self.obs_proj = nn.Linear(obs_dim, config.wm_hidden_dim)

        # 上下文编码: VLA特征 → hidden
        self.ctx_proj = nn.Linear(ctx_dim, config.wm_hidden_dim)

        # GRU编码器 (2层)
        self.gru = nn.GRU(
            input_size=config.wm_hidden_dim,
            hidden_size=config.wm_hidden_dim,
            num_layers=config.wm_num_layers,
            batch_first=True,
        )

        # 三层预测头
        self.z_heads = nn.ModuleList([
            nn.Sequential(
                nn.Linear(config.wm_hidden_dim, config.wm_hidden_dim),
                nn.ReLU(),
                nn.Linear(config.wm_hidden_dim, zdim),
            )
            for zdim in config.wm_latent_dims
        ])

    def forward(
        self,
        obs_seq: Tensor,         # [B, T, obs_dim]  连续帧的观测
        ctx_features: Tensor,    # [B, ctx_dim]      VLA特征作为上下文
    ) -> tuple[list[Tensor], Tensor]:
        """前向传播。

        Returns:
            z_list: 三层潜空间预测 [z₁, z₂, z₃]
            energy_loss: H-JEPA能量损失 (预测误差)
        """
        B = obs_seq.shape[0]

        # 编码观测序列
        obs_emb = self.obs_proj(obs_seq)  # [B, T, hidden]

        # 上下文注入GRU初始状态
        ctx_emb = self.ctx_proj(ctx_features)  # [B, hidden]
        h0 = ctx_emb.unsqueeze(0).repeat(self.config.wm_num_layers, 1, 1)

        # GRU前向
        gru_out, _ = self.gru(obs_emb, h0)  # [B, T, hidden]
        last_state = gru_out[:, -1, :]       # [B, hidden]

        # 三层预测
        z_list = [head(last_state) for head in self.z_heads]

        # H-JEPA 能量损失: 预测的潜空间 vs 目标潜空间的L2距离
        # 目标: 用当前GRU状态预测下一帧的观测编码
        if obs_seq.shape[1] >= 2:
            target_obs = self.obs_proj(obs_seq[:, 1:, :])  # [B, T-1, hidden]
            pred_obs = gru_out[:, :-1, :]                    # [B, T-1, hidden]
            energy_loss = F.mse_loss(pred_obs, target_obs)
        else:
            energy_loss = torch.tensor(0.0, device=obs_seq.device)

        return z_list, energy_loss


# ═══════════════════════════════════════════════════════════════
# VLA Hybrid Layer — Transformer encoder + Cross-Attention + Gate
# ═══════════════════════════════════════════════════════════════


class VLAHybridLayer(nn.Module):
    """单层VLA混合层: Self-Attn → Cross-Attn(WM Z) → FFN → Gate融合"""

    def __init__(
        self,
        hidden_dim: int,
        num_heads: int,
        head_dim: int,
        ffn_multiplier: float,
        dropout: float,
        z_dim: int,
    ):
        super().__init__()

        # Self-Attention
        self.self_attn = nn.MultiheadAttention(
            hidden_dim, num_heads, dropout=dropout, batch_first=True
        )
        self.attn_ln = nn.LayerNorm(hidden_dim)

        # Cross-Attention (读WM潜空间Z)
        self.cross_attn = nn.MultiheadAttention(
            hidden_dim, num_heads, dropout=dropout, batch_first=True
        )
        self.cross_ln = nn.LayerNorm(hidden_dim)

        # Z投影 (WM潜空间→Cross-Attn的K/V，拆成多token)
        self.num_z_tokens = 4  # 将z拆成4个token，每个携带不同子空间信息
        z_chunk_dim = z_dim // self.num_z_tokens
        self.z_token_projs = nn.ModuleList([
            nn.Linear(z_chunk_dim, hidden_dim)
            for _ in range(self.num_z_tokens)
        ])

        # FFN
        ffn_dim = int(hidden_dim * ffn_multiplier)
        self.ffn = nn.Sequential(
            nn.LayerNorm(hidden_dim),
            nn.Linear(hidden_dim, ffn_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(ffn_dim, hidden_dim),
            nn.Dropout(dropout),
        )

    def forward(
        self,
        x: Tensor,              # [B, L, hidden]  VLA特征
        z: Tensor | None,       # [B, z_dim]      WM潜空间 (推理时为None)
        gate: float,            # 门控系数
    ) -> Tensor:
        """前向传播。

        Args:
            x: VLA特征
            z: 世界模型潜空间 (None时跳过Cross-Attn)
            gate: 门控系数 (训练: 1.0→0.1→0.01, 推理: 0.0)
        """
        # Self-Attention
        residual = x
        x = self.attn_ln(x)
        x, _ = self.self_attn(x, x, x)
        x = x + residual

        # Cross-Attention (从WM注入 — 多token Z)
        if z is not None and gate > 0:
            residual = x
            x_norm = self.cross_ln(x)
            # 将z拆成多个token，每个关注不同的潜空间子区域
            z_chunks = z.chunk(self.num_z_tokens, dim=-1)  # [B, zdim/4] × 4
            z_tokens = torch.stack([
                proj(chunk) for proj, chunk in zip(self.z_token_projs, z_chunks)
            ], dim=1)  # [B, num_z_tokens, hidden]
            x_cross, _ = self.cross_attn(x_norm, z_tokens, z_tokens)
            # x_norm [B, 2, 512] → 关注 z_tokens [B, 4, 512]
            x = residual + gate * x_cross

        # FFN
        x = x + self.ffn(x)

        return x


# ═══════════════════════════════════════════════════════════════
# ZmaxHybridModel — 完整混合模型
# ═══════════════════════════════════════════════════════════════


class ZmaxHybridModel(nn.Module):
    """Z-MAX Hybrid 完整模型

    数据流:
      RGB+State → SmolVLM Encoder → Hybrid Layers(×3) → Fusion → DiT → Action
                                         ↕ Cross-Attn
                                    LeWM (GRU) → z₁,z₂,z₃
    """

    def __init__(self, config: ZmaxHybridConfig, pretrained_vla: str | None = None) -> None:
        super().__init__()
        require_package("transformers", extra="zmax_hybrid")
        self.config = config

        # ━━━ SmolVLM 视觉编码器 + 可选预训练权重 ━━━
        from transformers import AutoModel, AutoProcessor
        
        logger.info(f"Loading SmolVLM vision backbone...")
        self.vlm = AutoModel.from_pretrained(
            config.smolvlm_name,
            dtype=torch.float16,
            low_cpu_mem_usage=True,
            trust_remote_code=True,
        )
        self.processor = AutoProcessor.from_pretrained(config.smolvlm_name)
        
        # 从预训练SmolVLA加载VLM权重
        if pretrained_vla is not None:
            logger.info(f"Loading pretrained VLA weights from {pretrained_vla}...")
            from lerobot.policies.smolvla import SmolVLAPolicy
            pretrained = SmolVLAPolicy.from_pretrained(pretrained_vla)
            vla_vlm = pretrained.model.vlm_with_expert.vlm
            # 复制VLM权重到Hybrid
            vla_state = vla_vlm.state_dict()
            self.vlm.load_state_dict(vla_state, strict=False)
            del pretrained, vla_vlm
            torch.cuda.empty_cache()
            logger.info("Pretrained VLM weights loaded")
        
        # 使用vision_model获取hidden_size，如果不可用则回退
        try:
            self.vlm_hidden_size = self.vlm.config.vision_config.hidden_size
        except Exception:
            self.vlm_hidden_size = 768  # SigLIP default for SmolVLM2

        # ━━━ 特征投影 ━━━
        self.vlm_to_hybrid = nn.Linear(self.vlm_hidden_size, config.hybrid_hidden_size)
        self.state_proj = nn.Linear(config.state_dim, config.hybrid_hidden_size)

        # ━━━ 三层VLA混合层 ━━━
        self.hybrid_layers = nn.ModuleList([
            VLAHybridLayer(
                hidden_dim=config.hybrid_hidden_size,
                num_heads=config.hybrid_num_heads,
                head_dim=config.hybrid_head_dim,
                ffn_multiplier=config.hybrid_ffn_multiplier,
                dropout=config.hybrid_dropout,
                z_dim=config.wm_latent_dims[i],
            )
            for i in range(config.num_hybrid_layers)
        ])

        # ━━━ 世界模型 ━━━
        if config.enable_world_model:
            obs_input_dim = config.state_dim + config.action_dim
            self.world_model = LeWorldModelGRU(
                config,
                obs_dim=obs_input_dim,
                ctx_dim=config.hybrid_hidden_size,
            )
        else:
            self.world_model = None

        # ━━━ 动作头 (DiT-B) ━━━
        from lerobot.policies.smolvla_lew.action_head import SmolVLALewActionHead

        self.action_head = SmolVLALewActionHead(
            config, cross_attention_dim=config.hybrid_hidden_size
        )

        # ━━━ 冻结VLM ━━━
        if config.freeze_smolvlm:
            for p in self.vlm.parameters():
                p.requires_grad = False

    def _encode_vlm(self, images: list, instructions: list[str]) -> Tensor:
        """SigLIP视觉编码: 图片tensor → 视觉特征
        
        images: list of [C, H, W] tensors or PIL images
        """
        device = next(self.vlm.parameters()).device
        
        # Convert to tensor batch  
        img_tensors = []
        for img in images:
            if isinstance(img, torch.Tensor):
                if img.ndim == 3:
                    img = img.unsqueeze(0)      # [1, C, H, W]
                # 归一化: 假设输入在[0,1]或[-1,1]范围，统一到[0,1]
                img = img.float()
                if img.min() < 0:
                    img = (img + 1) / 2         # [-1,1] → [0,1]
                img_tensors.append(img.to(device))
            else:
                imgs = img if isinstance(img, list) else [img]
                proc = self.processor(images=imgs, return_tensors="pt")
                pv = proc["pixel_values"]
                if pv.ndim == 5:
                    pv = pv[:, 0]
                img_tensors.append(pv.to(device).float())
        
        # Concatenate all images and scale to [0, 255]
        pixel_values = torch.cat(img_tensors, dim=0)
        if pixel_values.max() <= 1.0:
            pixel_values = pixel_values * 255.0
        
        # 匹配VLM dtype (half精度)
        vlm_dtype = next(self.vlm.vision_model.parameters()).dtype
        pixel_values = pixel_values.to(dtype=vlm_dtype, device=device)
        
        with torch.no_grad():
            vis_out = self.vlm.vision_model(pixel_values)
            features = vis_out.last_hidden_state  # [B, num_patches, 768]
        
        # 统一到float32（VLM可能是half）
        features = features.float()
        
        return features

    def forward(
        self,
        images: list,
        instructions: list[str],
        state: Tensor,
        actions: Tensor | None = None,
        videos: Tensor | None = None,
        action_is_pad: Tensor | None = None,
        training: bool = True,
    ) -> dict[str, Tensor]:
        """完整前向传播。

        Args:
            images: 每样本的图片列表
            instructions: 语言指令
            state: [B, state_dim]
            actions: [B, T_chunk, action_dim] 训练时需要
            videos: [B, V, T, C, H, W] 视频帧 (世界模型需要)
            action_is_pad: 动作padding标记
            training: 训练模式 (决定gate和WM是否激活)
        """
        device = state.device
        B = state.shape[0]
        hdim = self.config.hybrid_hidden_size

        # ━━ Step 1: SigLIP 编码 ━━
        vlm_features = self._encode_vlm(images, instructions)  # [B, patches, 768]

        # 取平均作为全局特征 + 状态投影
        vlm_global = vlm_features.mean(dim=1)  # [B, 768]
        x = self.vlm_to_hybrid(vlm_global).unsqueeze(1)  # [B, 1, hdim]

        # 确保state是2D: [B, state_dim]
        state = state.reshape(B, -1)  # [B, state_dim] (修复: 处理多帧/多维度情况)
        state_emb = self.state_proj(state).unsqueeze(1)   # [B, 1, hdim]
        x = torch.cat([x, state_emb], dim=1)               # [B, 2, hdim]

        # ━━ Step 2: 世界模型 前向 (训练时) ━━
        z_list = None
        wm_energy_loss = torch.tensor(0.0, device=device)

        if self.world_model is not None and training and actions is not None:
            # 构建观测序列: [state, action] 拼接
            if videos is not None and videos.ndim == 5:
                T_video = videos.shape[2]
            else:
                # 无视频时用action chunk构造伪序列 (state重复, action不同)
                T_video = min(actions.shape[1], self.config.num_video_frames)
            
            obs_seq_list = []
            for t in range(T_video):
                act_t = actions[:, min(t, actions.shape[1]-1), :]
                obs_t = torch.cat([state, act_t], dim=-1)
                obs_seq_list.append(obs_t)
            obs_seq = torch.stack(obs_seq_list, dim=1)  # [B, T, obs_dim]

            ctx = x.mean(dim=1)  # [B, hdim]
            z_list, wm_energy_loss = self.world_model(obs_seq, ctx)

        # ━━ Step 3: 三层VLA混合层 ━━
        # 推理时: enable_wm_inference=True → gate保留; 否则→gate归零
        use_wm = training or (self.config.enable_wm_inference and self.world_model is not None)
        for i, layer in enumerate(self.hybrid_layers):
            z = z_list[i] if z_list is not None else None
            gate = self.config.hybrid_gates[i] if use_wm else 0.0
            x = layer(x, z, gate)

        # ━━ Step 4: 特征聚合 ━━
        fused_features = x.mean(dim=1)  # [B, hdim]

        # ━━ Step 5: DiT 动作头 ━━
        if actions is not None:
            action_loss = self.action_head(
                fused_features.unsqueeze(1),
                actions,
                state.unsqueeze(1) if state is not None else None,
                action_is_pad,
            )
        else:
            action_loss = torch.tensor(0.0, device=device)

        return {
            "action_loss": action_loss,
            "wm_energy_loss": wm_energy_loss,
            "z_list": z_list,
            "fused_features": fused_features,
        }

    @torch.no_grad()
    def predict_action(
        self,
        images: list,
        instructions: list[str],
        state: Tensor,
    ) -> Tensor:
        """推理: 支持WM自回归 (enable_wm_inference=True时)
        
        WM自回归流程:
          用预测动作逐步喂GRU → z随步数更新 → 每步gate全开
        """
        B = state.shape[0]
        hdim = self.config.hybrid_hidden_size
        
        use_wm = (self.config.enable_wm_inference and self.world_model is not None)
        
        # ━━ 编码图像 ━━
        vlm_features = self._encode_vlm(images, instructions)
        vlm_global = vlm_features.mean(dim=1)
        x_base = self.vlm_to_hybrid(vlm_global).unsqueeze(1)
        state_emb = self.state_proj(state).unsqueeze(1)
        x = torch.cat([x_base, state_emb], dim=1)  # [B, 2, hdim]
        
        if not use_wm:
            for layer in self.hybrid_layers:
                x = layer(x, None, gate=0.0)
            return x.mean(dim=1)
        
        # ━━ WM自回归 ━━
        chunk = self.config.chunk_size
        action_dim = self.config.action_dim
        
        # 初始用零动作启动GRU
        z_list = None
        pred_actions = torch.zeros(B, 1, action_dim, device=state.device)
        
        for step in range(min(chunk, 4)):  # 最多4步自回归(避免太慢)
            # 构建obs_seq: state + 累积预测动作
            if step > 0:
                obs_parts = [state]
                for t in range(min(step, pred_actions.shape[1])):
                    obs_parts.append(pred_actions[:, t, :])
                obs_seq = torch.stack([
                    torch.cat(obs_parts[:t+2], dim=-1)
                    for t in range(step)
                ], dim=1) if step > 0 else None
                
                if obs_seq is not None and obs_seq.shape[1] >= 1:
                    ctx = x.mean(dim=1)
                    z_list, _ = self.world_model(obs_seq, ctx)
            
            # VLA处理 (gate保留)
            x_step = x.clone()
            for i, layer in enumerate(self.hybrid_layers):
                z = z_list[i] if z_list is not None else None
                gate = self.config.hybrid_gates[i]
                x_step = layer(x_step, z, gate)
            
            # 简单预测: 从特征中提取动作方向
            step_action = x_step[:, 0, :action_dim]  # [B, act_dim]
            pred_actions = torch.cat([pred_actions, step_action.unsqueeze(1)], dim=1)
        
        # 最终融合 (WM模式也做一次无WM的最终融合)
        for layer in self.hybrid_layers:
            x = layer(x, None, gate=0.0)
        return x.mean(dim=1)


# ═══════════════════════════════════════════════════════════════
# ZmaxHybridPolicy — LeRobot 策略接口
# ═══════════════════════════════════════════════════════════════


class ZmaxHybridPolicy(PreTrainedPolicy):
    """Z-MAX Hybrid · LeRobot策略包装器"""

    config_class = ZmaxHybridConfig
    name = "zmax_hybrid"

    def __init__(self, config: ZmaxHybridConfig, dataset_stats=None, pretrained_vla=None, **kwargs):
        super().__init__(config)
        config.validate_features()
        self.config = config
        self.model = ZmaxHybridModel(config, pretrained_vla=config.pretrained_vla_path if hasattr(config, 'pretrained_vla_path') else pretrained_vla)
        self._queues = {ACTION: deque(maxlen=config.n_action_steps)}
        self.reset()

    def reset(self):
        self._queues = {ACTION: deque(maxlen=self.config.n_action_steps)}

    def get_optim_params(self):
        return self.parameters()

    def _save_pretrained(self, save_directory, state_dict=None):
        """保存双格式 (.bin for GRU safety, .safetensors for loading)"""
        import os
        os.makedirs(save_directory, exist_ok=True)
        self.config.save_pretrained(save_directory)
        if state_dict is None:
            state_dict = self.state_dict()
        # Clone避免GRU共享权重问题
        sd = {k: v.clone() for k, v in state_dict.items()}
        torch.save(sd, os.path.join(save_directory, "pytorch_model.bin"))
        # 同时保存safetensors (clone后GRU不再共享)
        from safetensors.torch import save_file
        save_file(sd, os.path.join(save_directory, "model.safetensors"))

    def _prepare_images(self, batch: dict) -> list:
        """从LeRobot batch提取图片tensor → list of [C, H, W] per batch element"""
        img_keys = [k for k in self.config.image_features if k in batch]
        if not img_keys:
            return [torch.randn(3, 64, 64)]

        # 取第一个camera的batch图片
        img_tensor = batch[img_keys[0]]
        if img_tensor.ndim == 5:  # [B, T, C, H, W]
            img_tensor = img_tensor[:, -1]  # 取最后一帧 → [B, C, H, W]
        # img_tensor: [B, C, H, W]
        B = img_tensor.shape[0]
        images = [img_tensor[i].cpu() for i in range(B)]  # list of [C, H, W]
        return images

    def forward(self, batch: dict[str, Tensor]) -> tuple[Tensor, dict]:
        """训练前向"""
        B = batch[OBS_STATE].shape[0] if batch[OBS_STATE].ndim >= 2 else 1

        # 提取输入
        state = batch[OBS_STATE]
        if state.ndim == 3:
            state = state[:, -1, :]
        if state.ndim == 1:
            state = state.unsqueeze(0)

        actions = batch.get(ACTION)
        if actions is not None and actions.ndim == 2:
            actions = actions.unsqueeze(0)

        # 图片
        images = self._prepare_images(batch)

        # 语言指令 (Multi-task: 用task描述或通用指令)
        task = batch.get("task", batch.get("task_id", None))
        if task is not None:
            instructions = [f"complete task {int(t.item()) if hasattr(t, 'item') else t}" for t in task]
        else:
            instructions = ["manipulate objects to complete the task"] * B

        # 视频 (从连续帧构建)
        videos = None

        action_is_pad = batch.get("action_is_pad")

        out = self.model.forward(
            images=images,
            instructions=instructions,
            state=state,
            actions=actions,
            videos=videos,
            action_is_pad=action_is_pad,
            training=True,
        )

        loss = (
            out["action_loss"]
            + self.config.wm_energy_loss_weight * out["wm_energy_loss"]
        )

        loss_dict = {
            "action_loss": out["action_loss"].item()
            if isinstance(out["action_loss"], Tensor)
            else out["action_loss"],
            "wm_energy_loss": out["wm_energy_loss"].item()
            if isinstance(out["wm_energy_loss"], Tensor)
            else out["wm_energy_loss"],
            "total_loss": loss.item() if isinstance(loss, Tensor) else loss,
        }

        return loss, loss_dict

    @torch.no_grad()
    def predict_action_chunk(self, batch: dict[str, Tensor]) -> Tensor:
        """推理: 返回动作chunk"""
        self.eval()
        B = batch[OBS_STATE].shape[0] if batch[OBS_STATE].ndim >= 2 else 1
        state = batch[OBS_STATE]
        if state.ndim == 3:
            state = state[:, -1, :]
        if state.ndim == 1:
            state = state.unsqueeze(0)

        images = self._prepare_images(batch)
        instructions = ["push the T block to target"] * B

        features = self.model.predict_action(images, instructions, state)

        # 用action head的最后层做预测 (简化版)
        return features[:, : self.config.chunk_size * self.config.action_dim].reshape(
            B, self.config.chunk_size, self.config.action_dim
        )

    @torch.no_grad()
    def select_action(self, batch: dict[str, Tensor]) -> Tensor:
        self.eval()
        actions = self.predict_action_chunk(batch)
        self._queues[ACTION].extend(actions.transpose(0, 1))
        return self._queues[ACTION].popleft()

    def _check_get_actions_condition(self) -> bool:
        return len(self._queues[ACTION]) == 0

    def state_dict(self, *args, **kwargs):
        """Override to clone GRU weights (avoid safetensors shared tensor issue)"""
        sd = super().state_dict(*args, **kwargs)
        return {k: v.clone() if 'gru' in k else v for k, v in sd.items()}
