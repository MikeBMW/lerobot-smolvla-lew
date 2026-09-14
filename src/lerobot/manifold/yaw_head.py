# -*- coding: utf-8 -*-
"""🎯 yaw_head.py — yaw 条件"试抓头" (2026-09-11 老倪: 让 φ* 成为真正的最优对准角)

问题 (v5.5.21 实测): 旧 v5 世界模型输入 **无 yaw 维** (act_dim=4) → 让它在候选偏航角上打分
代价单调退化 (argmin 恒落候选边界), 选出来的角没有对准信息。

本模块: 输入 = 几何潜向量 z7 + 4D 动作 + **候选偏航角 yaw_norm** (act_dim 4→5 语义),
监督 = `tools/yaw_grasp_probe.py` 的**真实试抓** (摩擦夹持 + 抬升试探, 无刚性锁):
  · head_dz  回归抬升高度 Δz (主打分 — 连续信号, 数据效率高)
  · head_ok  成功概率 logit (辅助, 可解释/可看 P(成功))
φ* = argmax_候选 预测 Δz (并列时看 P(成功)) → 真正由"真实试抓成败"监督出来的对准角。

诚实标注: 训练数据来自仿真真实试抓 (非真机); 泛化边界 = 训练覆盖的布局/候选角范围。
"""
from __future__ import annotations

import torch
from torch import nn


class YawGraspHead(nn.Module):
    def __init__(self, z_dim: int = 7, act_dim: int = 4, hidden: int = 256,
                 num_layers: int = 2) -> None:
        super().__init__()
        self.z_dim = int(z_dim)
        self.act_dim = int(act_dim)
        in_dim = z_dim + act_dim + 1          # +1 = yaw_norm (act_dim 4→5 的语义扩展)
        layers: list[nn.Module] = [nn.Linear(in_dim, hidden), nn.SiLU()]
        for _ in range(num_layers - 1):
            layers += [nn.Linear(hidden, hidden), nn.SiLU()]
        self.trunk = nn.Sequential(*layers)
        self.head_dz = nn.Linear(hidden, 1)   # 预测抬升 Δz (归一化)
        self.head_ok = nn.Linear(hidden, 1)   # 成功 logit

    def forward(self, z, a, yaw_norm):
        if yaw_norm.dim() == 1:
            yaw_norm = yaw_norm.unsqueeze(-1)
        h = self.trunk(torch.cat([z, a, yaw_norm], dim=-1))
        return {"dz": self.head_dz(h).squeeze(-1), "ok_logit": self.head_ok(h).squeeze(-1)}

    @torch.no_grad()
    def score(self, z7, a4, phi_deg):
        """单点打分 (执行器用): 返回 (dẑ, p_ok)"""
        import numpy as np
        z = torch.from_numpy(np.asarray(z7, dtype="float32")).reshape(1, -1)
        a = torch.from_numpy(np.asarray(a4, dtype="float32").ravel()[:4]
                             .astype("float32")).reshape(1, -1)
        y = torch.tensor([[float(phi_deg) / 90.0]], dtype=torch.float32)
        o = self.forward(z, a, y)
        return float(o["dz"][0]), float(torch.sigmoid(o["ok_logit"])[0])

    if __name__ == "__main__":     # 结构自检 (随机权重)
        pass
