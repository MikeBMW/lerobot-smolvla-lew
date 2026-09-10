#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""恰当动作似然头 (Proper Action Likelihood Head) — INTACT ① 的落地

词源启示(paste_15/16 老倪提供):
  Likelihood = Lik-(形状/形式) + Likely(相似) + -hood(状态)
  古人识别脚印: 在记忆中找"形状最相似"的模型 → 相似度高即似然高
  → 动作似然 = "当前状态下, 哪一动作的**形状**与专家演示最相似"

因此本实现的三个要点(与论文三要素一一对应):
  ① 共享恰当动作似然: **两态走同一个 forward、同一套参数** (结构共享)
     - 输出**分布**(混合高斯)而非确定性动作 —— 分布天然容纳多解 ↔ 等价类
  ② 非对称梯度(训练侧实现, 见 train 脚本): m_local 全梯度 / m_goal detach
  ③ 无逐点损失:
     - 似然是**恰当归一化**的概率(NLL), 不是 MSE
     - 对齐用**行为一致性**(行为空间分布距离), 不是 ‖z_t − z_g‖²
     - 🚫 本模块**不提供**任何坐标 L2 / 动作逐点 L2 接口(从结构上杜绝犯错)

用法(训练循环):
    head = ActionLikelihoodHead()
    loss_local = head.nll(z, m_local, a_expert)              # 全梯度 (attached)
    loss_goal  = head.nll(z, m_goal.detach(), a_expert)      # 锚 (stop-gradient)
    loss_align = behavior_align_loss(head, z, m_local, m_goal)   # 行为对齐
    loss = loss_local + loss_goal + lam * loss_align
"""
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F


class ActionLikelihoodHead(nn.Module):
    """混合高斯动作似然: p(a | z, m), 两态**共享**同一套参数 (INTACT ①)。"""

    def __init__(self, z_dim=7, m_dim=3, act_dim=3, n_modes=4, hidden=128, min_sigma=0.01):
        super().__init__()
        self.z_dim, self.m_dim, self.act_dim = int(z_dim), int(m_dim), int(act_dim)
        self.n_modes = int(n_modes)
        self.min_sigma = float(min_sigma)
        self.fc1 = nn.Linear(self.z_dim + self.m_dim, hidden)
        self.fc2 = nn.Linear(hidden, hidden)
        # 共享输出头: 权重(混合系数) / 均值 / 对数标准差
        self.head_pi = nn.Linear(hidden, self.n_modes)
        self.head_mu = nn.Linear(hidden, self.n_modes * self.act_dim)
        self.head_ls = nn.Linear(hidden, self.n_modes * self.act_dim)
        # 记录梯度流(用于核验 ② 非对称性是否真的生效)
        self.last_grad_norms = {}

    def forward(self, z, m):
        """**两态唯一入口** (结构共享的工程含义: 不存在第二条路径)。"""
        z = torch.as_tensor(z, dtype=torch.float32)
        m = torch.as_tensor(m, dtype=torch.float32)
        if z.dim() == 1:
            z, m = z.unsqueeze(0), m.unsqueeze(0)
        h = F.relu(self.fc1(torch.cat([z, m], dim=-1)))
        h = F.relu(self.fc2(h))
        pi = F.softmax(self.head_pi(h), dim=-1)                                   # (B,K)
        mu = self.head_mu(h).view(-1, self.n_modes, self.act_dim)                 # (B,K,D)
        ls = self.head_ls(h).clamp(-6.0, 2.0).view(-1, self.n_modes, self.act_dim)
        sigma = F.softplus(ls) + self.min_sigma                                    # (B,K,D)
        return pi, mu, sigma

    # ── 恰当似然 (NLL): 概率的负对数, 非 MSE ────────────────────────────
    def nll(self, z, m, a_exp):
        """−log p(a* | z, m)。两态同路; 是否 detach 由调用方决定 (② 的落点)。"""
        a_exp = torch.as_tensor(a_exp, dtype=torch.float32)
        if a_exp.dim() == 1:
            a_exp = a_exp.unsqueeze(0)
        pi, mu, sigma = self(z, m)
        a = a_exp.unsqueeze(1)                                     # (B,1,D)
        log_n = (-0.5 * ((a - mu) / sigma) ** 2
                 - torch.log(sigma) - 0.5 * np.log(2 * np.pi))     # (B,K,D)
        log_n = log_n.sum(-1)                                      # (B,K)
        log_pi = torch.log(pi + 1e-12)                             # (B,K)
        logp = torch.logsumexp(log_pi + log_n, dim=-1)             # (B,)
        return -logp.mean()

    # ── 行为分布参数 (供 ③ 行为对齐使用) ────────────────────────────────
    def behavior_stats(self, z, m, n_samples=8, seed=0):
        """从 p(a|z,m) 采样 → 行为空间的统计量 (均值/标准差)。

        ⚠️ 注意: 这里返回的是**行为空间**的统计, 用于比较"诱发行为是否一致",
           而**不是**潜坐标 z 本身 (INTACT ③: 拒绝坐标对齐)。
        """
        g = torch.Generator().manual_seed(seed)
        pi, mu, sigma = self(z, m)
        B, K, D = mu.shape
        idx = torch.multinomial(pi, n_samples, replacement=True, generator=g)   # (B,S)
        eps = torch.randn(B, n_samples, D, generator=g)
        mu_s = torch.gather(mu, 1, idx.unsqueeze(-1).expand(-1, -1, D))          # (B,S,D)
        sg_s = torch.gather(sigma, 1, idx.unsqueeze(-1).expand(-1, -1, D))
        samples = mu_s + sg_s * eps                                              # (B,S,D)
        return samples.mean(1), samples.std(1) + 1e-6

    def behavior_stats_diff(self, z, m):
        """🐛 2026-09-11 修正: **可微**的行为统计 (解析式, 不用采样)。

        首版用采样版 (@torch.no_grad) → 对齐项**完全没有梯度** → 形同虚设
        (实测 xy_align 与 no_align 结果一字不差, 就是这个 bug)。
        解析式: 混合高斯的均值 = Σ π_k μ_k; 方差 = Σ π_k (σ_k² + μ_k²) − 均值²
        → 完全可微, 且比采样更稳 (无随机性)。
        """
        pi, mu, sigma = self(z, m)                          # (B,K), (B,K,D), (B,K,D)
        mean = (pi.unsqueeze(-1) * mu).sum(1)                # (B,D) 可微
        var = (pi.unsqueeze(-1) * (sigma ** 2 + mu ** 2)).sum(1) - mean ** 2
        return mean, torch.sqrt(var.clamp_min(1e-12))


def behavior_align_loss(head, z, m_a, m_b, n_samples=8):
    """③ 行为对齐 (Align through behavior) —— INTACT 的核心破局点。

    论文原话: "通过两种意图族在同一个条件动作算子下所**诱发的行为**来实现对齐,
              而不是通过使它们的潜在坐标相等来实现"。

    实现:
      · 把 m_a / m_b 分别喂给**同一个** head → 得两组行为分布
      · 用行为空间上的分布距离 (此处: 均值距离 + 方差相对差) 度量是否"诱发相同行为"
      · 🚫 绝不出现 ‖z_t − z_g‖² / ‖a_a − a_b‖² 这类逐点坐标项

    语义: 自由空间里 m_local 与 m_goal 指向同一目标 → 诱导行为应一致(此 loss → 0);
          接触约束下两者分工 → 允许分歧(用 stage 掩码控制, 见训练脚本)。
    """
    mu_a, sd_a = head.behavior_stats_diff(z, m_a)     # 🐛 可微版 (原采样版 no_grad → 无梯度形同虚设)
    mu_b, sd_b = head.behavior_stats_diff(z, m_b)
    d_mean = F.smooth_l1_loss(mu_a, mu_b)                       # 行为均值一致
    d_var = ((sd_a - sd_b) ** 2).mean()                         # 行为离散度一致
    return d_mean + d_var


def manifold_consistency_loss(head, z, m, class_id):
    """条件动作商一致性 (与 motor_hub.build_quotient 复用同一套类标签)。

    同类(同一"动作等价类")→ 诱导行为应接近; 异类 → 应可分。
    这是 ③ 的原话: "只要两个目标在当前状态下能触发相同的动作规律, 它们就是等价的"。
    """
    pi, mu, sigma = head(z, m)
    mu_flat = mu.reshape(mu.shape[0], -1)
    cid = torch.as_tensor(class_id, dtype=torch.long).reshape(-1)
    if cid.numel() != mu_flat.shape[0]:
        return torch.tensor(0.0, requires_grad=True)
    uniq = torch.unique(cid)
    if uniq.numel() < 2:
        return torch.tensor(0.0, requires_grad=True)
    # 类内紧致
    intra = mu_flat.new_zeros(())
    for c in uniq:
        sel = mu_flat[cid == c]
        if sel.shape[0] > 1:
            intra = intra + ((sel - sel.mean(0)) ** 2).mean()
    intra = intra / max(1, uniq.numel())
    # 类间可分 (负)
    cent = torch.stack([mu_flat[cid == c].mean(0) for c in uniq])
    if cent.shape[0] > 1:
        d = torch.cdist(cent, cent)
        m = ~torch.eye(cent.shape[0], dtype=torch.bool, device=cent.device)
        inter = d[m].mean()
    else:
        inter = mu_flat.new_zeros(())
    return intra - 0.5 * inter
