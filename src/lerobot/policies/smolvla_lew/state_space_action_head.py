"""🎯 StateSpaceActionHead — 状态空间 ActionHead (smolvla_lew 标准算法包内, 2026-09-08)

老倪: "这个也应该在标准 smolvla 算法里, 可以增加针对状态空间的 action head" —
官方 action_head.py (SmolVLALewActionHead, DiT 流匹配 z→动作块) 在 lerobot 框架层;
本文件在其同目录增加**针对 Z-MAX 状态空间的动作头变体**:

- 输入: 状态空间潜空间特征 z — 几何潜空间 (R⁷: 手→目标 / 手→工件 / 夹持)
        或 VLM 池化特征 (R⁹⁶⁰, vlm_encoder) 或二者 concat (R⁹⁶⁷)
- 输出: 动作 (默认 4D = xyz+gripper, metaworld/sawyer; 真机 Orin 珞石 6D 可配),
        支持官方 chunk_size 语义 (一次预测 chunk 步动作块)
- 结构: 与官方 SmolVLALewActionHead.action_decoder 同构的 MLP 投影 (Linear→SiLU→Linear),
        区别于官方 DiT 的是**无跨模态条件流匹配**, 直接 z→动作 (状态空间端到端 BC/蒸馏)
- 训练状态: 标准 nn.Module, 随机初始化; 真实推理需 smolvla_lew 训练加载权重 (DiT 主链),
        本头也可独立蒸馏 (潜空间→动作 BC)。GUI node_ss_dec 经 exec(compile(真实路径))
        加载本文件 (断点可进, 架构同 node_metaworld_data/vlm_encoder 归位铁律)
- 无 GUI/lerobot 依赖 (纯 torch) — 框架层纯净, 自测 __main__

2026-09-08 静静: 高级层解码侧真实化第一步 (encoder=VLM 已归位 → decoder=本文件)
"""
from __future__ import annotations

import torch
from torch import nn


class StateSpaceActionHead(nn.Module):
    """状态空间 ActionHead — 潜空间/状态特征 → 4D 动作 (支持 chunk)

    Args:
        input_dim:   输入特征维 — 几何 z R⁷ / VLM 池化 R⁹⁶⁰ / 融合 R⁹⁶⁷ (按接入侧配置)
        action_dim:  动作维 — 4=状态空间 xyz+gripper (默认), 6=真机 Orin
        chunk_size:  动作块步数 (官方 chunk_size 语义; 1=单步)
        hidden_dim:  MLP 隐层宽 (默认 256)
        num_layers:  隐层数 (默认 2)
    """

    def __init__(self, input_dim: int = 7, action_dim: int = 4, chunk_size: int = 7,
                 hidden_dim: int = 256, num_layers: int = 2) -> None:
        super().__init__()
        if num_layers < 1:
            raise ValueError("num_layers >= 1")
        self.input_dim = int(input_dim)
        self.action_dim = int(action_dim)
        self.chunk_size = int(chunk_size)
        # 官方 action_decoder 同构: Linear→SiLU→...→Linear(action_dim)
        layers: list[nn.Module] = [nn.Linear(self.input_dim, hidden_dim), nn.SiLU()]
        for _ in range(num_layers - 1):
            layers += [nn.Linear(hidden_dim, hidden_dim), nn.SiLU()]
        layers.append(nn.Linear(hidden_dim, self.action_dim * self.chunk_size))
        self.mlp = nn.Sequential(*layers)

    def forward(self, z: torch.Tensor) -> torch.Tensor:
        """z: [B, input_dim] (潜空间特征) → [B, chunk_size, action_dim] 动作块"""
        b = z.shape[0]
        out = self.mlp(z)                       # [B, chunk*action_dim]
        return out.view(b, self.chunk_size, self.action_dim)


if __name__ == "__main__":
    # CLI 自测: 结构 + 前向维度 (随机权重 — 真实权重待 smolvla_lew 训练)
    import numpy as np
    head = StateSpaceActionHead(input_dim=7, action_dim=4, chunk_size=7)
    n_params = sum(p.numel() for p in head.parameters())
    print(f"StateSpaceActionHead: {n_params:,} 参数 | input R{head.input_dim} → "
          f"[B, chunk {head.chunk_size}, action {head.action_dim}]")
    z = torch.from_numpy(np.random.randn(1, 7).astype(np.float32))
    out = head(z)
    print(f"前向自检: z{z.shape} → {tuple(out.shape)} ✓ (随机初始化, 训练后启用)")
    # 组合输入自检 (几何 R7 + VLM R960 融合)
    head2 = StateSpaceActionHead(input_dim=967, action_dim=4, chunk_size=1)
    z2 = torch.from_numpy(np.random.randn(2, 967).astype(np.float32))
    print(f"融合自检 (R7+R960): {tuple(head2(z2).shape)} ✓")
