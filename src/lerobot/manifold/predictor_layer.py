"""🧠 predictor_layer.py — JEPA 潜空间预测器 (流形层, 与 Contact/PerformanceManifold 同域)

位置: src/lerobot/manifold/ (与 manifold_layer.py 同目录, 同 calibration/datasets/
policies 平级) — 老倪: predictor 预测的是接触/性能流形, 属于流形域, 不在 policies。
接触流形/性能流形 = 潜空间上的导航地图 (manifold_layer.py, 解析几何层);
本文件 = JEPA predictor (世界模型): 根据潜空间 z + 动作 a 预测**未来流形坐标**,
decoder 按预测流形解动作 (状态空间 ActionHead)。

链路 (2026-09-08 老倪 L4 专家模型架构):
    z_t ──┐                        ┌─> ManifoldReadout ─> 接触流形 [progress, risk, V]
          ├─ LatentPredictor ─ z'_t+1                      └─> 性能流形 [eta, rem, d_perp]
    a_t ──┘   (z+a → z')

  · LatentPredictor:  JEPA predictor — 动作条件预测未来潜状态 z' (轻量 MLP;
    完整大版本 = smolvla_lew/world_model_le.py LeWorldModel.ARPredictor, AdaLN Transformer)
  · ManifoldReadout:  z' → 流形坐标 (6 维, 与引擎真值列一一对齐可监督训练:
    mani_progress / mani_risk / mani_V / mani_eta / mani_rem / mani_dperp)
  · 下游 decoder = smolvla_lew/state_space_action_head.py StateSpaceActionHead

训练态: 标准 nn.Module 随机初始化; 真实推理需训练 (数据管道已通: sim_real 每帧有
z/动作/流形真值)。GUI node 经 exec(compile(真实路径)) 加载 (断点可进)。
"""
from __future__ import annotations

import torch
from torch import nn


class LatentPredictor(nn.Module):
    """JEPA predictor — 动作条件潜空间预测: (z_t, a_t) → z'_{t+1}

    LeWorldModel.ARPredictor 的轻量状态空间变体 (完整版见 world_model_le.py);
    输出 z 维 = 输入 z 维 (VLM 池化 R⁹⁶⁰ / 几何 R⁷ / 融合 R⁹⁶⁷ 由调用侧定)。
    """

    def __init__(self, z_dim: int = 960, act_dim: int = 4,
                 hidden_dim: int = 256, num_layers: int = 2) -> None:
        super().__init__()
        self.z_dim = int(z_dim)
        self.act_dim = int(act_dim)
        layers: list[nn.Module] = [nn.Linear(z_dim + act_dim, hidden_dim), nn.SiLU()]
        for _ in range(num_layers - 1):
            layers += [nn.Linear(hidden_dim, hidden_dim), nn.SiLU()]
        layers.append(nn.Linear(hidden_dim, z_dim))
        self.mlp = nn.Sequential(*layers)

    def forward(self, z: torch.Tensor, a: torch.Tensor) -> torch.Tensor:
        """z: [B, z_dim], a: [B, act_dim] → z_pred: [B, z_dim]"""
        return self.mlp(torch.cat([z, a], dim=-1))


class ManifoldReadout(nn.Module):
    """z' → 流形坐标 readout (6 维, 与引擎真值列对齐, 可监督训练)

    [0] contact progress (切向进度, m)     — tr.mani_progress
    [1] contact risk     (法向偏离, m)     — tr.mani_risk
    [2] contact V        (李雅普诺夫势)    — tr.mani_V
    [3] perf eta         (估计耦合效率)    — tr.mani_eta
    [4] perf rem         (轴向插入余量, m) — tr.mani_rem  (=-d_axial)
    [5] perf d_perp      (横向模场错位, m) — tr.mani_dperp
    """

    def __init__(self, z_dim: int = 960, manifold_dim: int = 6,
                 hidden_dim: int = 128) -> None:
        super().__init__()
        self.manifold_dim = int(manifold_dim)
        self.mlp = nn.Sequential(
            nn.Linear(z_dim, hidden_dim), nn.SiLU(),
            nn.Linear(hidden_dim, hidden_dim), nn.SiLU(),
            nn.Linear(hidden_dim, self.manifold_dim),
        )

    def forward(self, z_pred: torch.Tensor) -> torch.Tensor:
        """z_pred: [B, z_dim] → manifold: [B, manifold_dim] (真实坐标回归)"""
        return self.mlp(z_pred)


class WorldModelPredictor(nn.Module):
    """🧠 L4 世界模型预测器 — JEPA 链路: (z, a) → z' → 接触/性能流形坐标

    组装 LatentPredictor + ManifoldReadout (decoder = StateSpaceActionHead 独立,
    吃流形坐标解动作 — 见 state_space_action_head.py)。真机同构: predictor 只吃
    潜空间 (JEPA 原则), 流形坐标 = 导航地图读数。
    """

    def __init__(self, z_dim: int = 960, act_dim: int = 4, manifold_dim: int = 6,
                 hidden_dim: int = 256, num_layers: int = 2) -> None:
        super().__init__()
        self.z_dim = int(z_dim)
        self.predictor = LatentPredictor(z_dim, act_dim, hidden_dim, num_layers)
        self.readout = ManifoldReadout(z_dim, manifold_dim, max(128, hidden_dim // 2))
        self.manifold_dim = int(manifold_dim)

    def forward(self, z: torch.Tensor, a: torch.Tensor) -> dict[str, torch.Tensor]:
        """→ {"z_pred": [B, z_dim], "manifold": [B, manifold_dim]}"""
        z_pred = self.predictor(z, a)
        manifold = self.readout(z_pred)
        return {"z_pred": z_pred, "manifold": manifold}


if __name__ == "__main__":
    # CLI 自检: 链路真实结构 + 维度 (随机权重 — 训练后启用; 同目录可拼 decoder)
    import numpy as np
    print("═══ WorldModelPredictor (JEPA: z+a → z' → 流形坐标) ═══")
    for zd, tag in ((960, "VLM z R960 (潜空)"), (7, "几何 z R7 (对照)")):
        wm = WorldModelPredictor(z_dim=zd)
        n = sum(p.numel() for p in wm.parameters())
        z = torch.from_numpy(np.random.randn(1, zd).astype(np.float32))
        a = torch.from_numpy(np.random.randn(1, 4).astype(np.float32))
        with torch.no_grad():
            out = wm(z, a)
        print(f"  [{tag}] 参数 {n:,} | z{z.shape} + a{a.shape} → "
              f"z_pred{tuple(out['z_pred'].shape)} → 流形{tuple(out['manifold'].shape)} ✓")
    # decoder 拼接自检: 流形坐标(6) → StateSpaceActionHead (smolvla_lew 包) → 4D 动作块
    import os as _os, sys as _sys
    _lew = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                         "policies", "smolvla_lew")
    if _lew not in _sys.path:
        _sys.path.insert(0, _lew)
    from state_space_action_head import StateSpaceActionHead
    head = StateSpaceActionHead(input_dim=6, action_dim=4, chunk_size=7)
    wm = WorldModelPredictor(z_dim=7)
    z = torch.from_numpy(np.random.randn(2, 7).astype(np.float32))
    a = torch.from_numpy(np.random.randn(2, 4).astype(np.float32))
    with torch.no_grad():
        m = wm(z, a)["manifold"]
        acts = head(m)
    print(f"  链路自检: z R7 → 流形 {tuple(m.shape)} → decoder → 动作块 {tuple(acts.shape)} ✓ "
          f"(decoder {sum(p.numel() for p in head.parameters()):,} 参数)")
    print("  真值对齐: readout 6 维 = mani_progress/mani_risk/mani_V/mani_eta/mani_rem/mani_dperp (sim_real 逐帧发布)")
