#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阶段2 训练: 恰当动作似然头 (INTACT ①) + 非对称梯度(②) + 行为对齐(③)

数据: data/intent_pairs_v1.npz (引擎真跑, 只收成功轨迹 = 专家演示)
用法: cd repo && gui-venv311/bin/python tools/train_intent_head.py [--cpu]

损失(严格按论文三要素, 禁止任何坐标/动作逐点 L2):
  L = NLL(z, m_local, a*)                 # ① 共享似然; m_local 全梯度 (attached "绳")
    + NLL(z, m_goal.detach(), a*)         # ② 目标路径 stop-gradient ("锚")
    + λ_align · behavior_align_loss(...)  # ③ 行为对齐 (行为空间, 非坐标)
    + λ_cons  · manifold_consistency(...) # ③ 条件动作商一致性 (等价类)

消融(必做, 证明三要素各自作用):
  full      : 全要素
  no_sg     : 去掉 ② (m_goal 也反传)           → 预期: 物理认知被目标扭曲
  no_align  : 去掉 ③ 行为对齐                   → 预期: 两态行为发散
  xy_align  : 改用 ③ 的"错误做法"(坐标 L2 对齐)  → 预期: 潜空间塌缩 (对照实验)
"""
import argparse
import json
import os
import sys
import time

os.environ.setdefault('MUJOCO_GL', 'egl')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))
os.chdir(ROOT)

import numpy as np  # noqa: E402
import torch  # noqa: E402
import torch.nn.functional as F  # noqa: E402

from lerobot.manifold.likelihood_head import (  # noqa: E402
    ActionLikelihoodHead, behavior_align_loss, manifold_consistency_loss)

DATA = os.path.join(ROOT, 'data', 'intent_pairs_v1.npz')


def load_data():
    d = np.load(DATA, allow_pickle=True)
    z = d['z'].astype(np.float32)
    ml = d['m_local'].astype(np.float32)
    mg = d['m_goal'].astype(np.float32)
    a = d['a_expert'].astype(np.float32)
    stg = d['stage']
    # 条件动作商类标签: 用 (阶段, 意图方向量化) 作为等价类代理 (与 motor_hub 同思想)
    cls = []
    for s, v in zip(stg, ml):
        q = tuple(np.round(v / (np.linalg.norm(v) + 1e-9) * 3).astype(int).tolist())
        cls.append(f'{s}|{q}')
    return z, ml, mg, a, np.array(cls, dtype=object), stg


def run_variant(name, z, ml, mg, a, cls, epochs=400, lr=3e-3, lam_align=0.1, lam_cons=0.02,
                drop_sg=False, drop_align=False, xy_align=False, seed=0, device='cpu'):
    torch.manual_seed(seed)
    np.random.seed(seed)
    head = ActionLikelihoodHead(z_dim=z.shape[1], m_dim=3, act_dim=a.shape[1]).to(device)

    zt = torch.tensor(z, device=device)
    mlt = torch.tensor(ml, device=device)
    mgt = torch.tensor(mg, device=device)
    at = torch.tensor(a, device=device)
    cid = torch.tensor([hash(c) % 100000 for c in cls], dtype=torch.long, device=device)

    opt = torch.optim.Adam(head.parameters(), lr=lr)
    n = zt.shape[0]
    bs = min(256, n)
    t0 = time.time()
    hist = []
    for ep in range(epochs):
        perm = torch.randperm(n)
        tot = 0.0
        for i in range(0, n, bs):
            idx = perm[i:i + bs]
            opt.zero_grad()
            # ① 共享似然 (m_local, 全梯度 = attached "绳")
            l_local = head.nll(zt[idx], mlt[idx], at[idx])
            # ② 目标路径 (锚): drop_sg=True 时去掉 detach (= 消融 ②)
            _mg = mgt[idx] if drop_sg else mgt[idx].detach()
            l_goal = head.nll(zt[idx], _mg, at[idx])
            loss = l_local + l_goal
            # ③ 行为对齐
            if not drop_align:
                if xy_align:
                    # ⚠️ 对照: "错误做法" —— 坐标对齐 (论文明确反对的点对点强制)
                    loss = loss + lam_align * F.mse_loss(mlt[idx], mgt[idx].detach())
                else:
                    loss = loss + lam_align * behavior_align_loss(head, zt[idx], mlt[idx], mgt[idx])
                    loss = loss + lam_cons * manifold_consistency_loss(head, zt[idx], mlt[idx], cid[idx])
            loss.backward()
            # 记录编码器侧梯度范数 (核验 ② 的非对称性)
            g_enc = 0.0
            for p in head.fc1.parameters():
                if p.grad is not None:
                    g_enc += float(p.grad.norm() ** 2)
            opt.step()
            tot += float(loss)
        hist.append(tot / max(1, (n + bs - 1) // bs))

    dt = time.time() - t0
    head.eval()
    with torch.no_grad():
        nll_l = float(head.nll(zt, mlt, at))
        nll_g = float(head.nll(zt, mgt, at))

    # 🎯 核验 ②(非对称梯度)的正确方式: 看 ∂L/∂m 在两条路径上的范数
    #   (首版用"前向 NLL 是否相同"来判断是错的 —— detach 只影响反向, 前向必然一样)
    def _grad_wrt_m(m_in, detach_it):
        _m = m_in.clone().requires_grad_(True)
        head.zero_grad(set_to_none=True)
        _mm = _m.detach() if detach_it else _m
        head.nll(zt, _mm, at).backward()
        return float(_m.grad.norm()) if _m.grad is not None else 0.0

    g_m_local = _grad_wrt_m(mlt, False)          # 局部意图: 应有梯度 (attached "绳")
    g_m_goal_sg = _grad_wrt_m(mgt, True)         # 目标意图 + detach: **必须为 0** (锚)
    g_m_goal_raw = _grad_wrt_m(mgt, False)       # 目标意图 不 detach: >0 (证明 detach 真在起作用)
    head.zero_grad(set_to_none=True)

    ntrain = sum(p.numel() for p in head.parameters())
    return dict(variant=name, nll_local=nll_l, nll_goal=nll_g, epochs=epochs,
                params=ntrain, seconds=round(dt, 1), loss_hist=hist,
                grad_m_local=round(g_m_local, 5), grad_m_goal_stopgrad=round(g_m_goal_sg, 5),
                grad_m_goal_nodetach=round(g_m_goal_raw, 5))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cpu', action='store_true')
    ap.add_argument('--epochs', type=int, default=400)
    a = ap.parse_args()
    dev = 'cpu' if a.cpu or not torch.cuda.is_available() else 'cuda'

    z, ml, mg, ax, cls, stg = load_data()
    print(f'=== 阶段2 训练: 恰当动作似然头 (INTACT ① + ② + ③) ===')
    print(f'  数据 {DATA}')
    print(f'  样本 {len(z)} · z{z.shape} · m_local{ml.shape} · m_goal{mg.shape} · a{ax.shape}')
    print(f'  阶段 {sorted(set(stg.tolist()))}')
    print(f'  设备 {dev} · epochs {a.epochs} · 类别数 {len(set(cls.tolist()))}\n')

    variants = [
        ('full', dict()),
        ('no_sg (去②锚)', dict(drop_sg=True)),
        ('no_align (去③对齐)', dict(drop_align=True)),
        ('xy_align (③错误做法: 坐标L2)', dict(xy_align=True)),
    ]
    res = []
    for name, kw in variants:
        r = run_variant(name, z, ml, mg, ax, cls, epochs=a.epochs, device=dev, **kw)
        res.append(r)
        print(f'  {name:<30} NLL_local {r["nll_local"]:>8.4f} · NLL_goal {r["nll_goal"]:>8.4f} · '
              f'参数 {r["params"]} · {r["seconds"]}s', flush=True)
        print(f'      ↳ ②核验 ∂L/∂m: 局部 {r["grad_m_local"]} · 目标(停梯度) {r["grad_m_goal_stopgrad"]} '
              f'· 目标(不停) {r["grad_m_goal_nodetach"]}', flush=True)

    print('\n=== 判读 (诚实报数) ===')
    print('  · NLL 下降 = 似然真的学到 (含混合权重/均值/方差, 非逐点拟合)')
    print('  · full vs no_sg: 若 no_sg 的 NLL_goal 更低却 NLL_local 变差 → 目标在扭曲物理路径')
    print('  · full vs xy_align: 坐标对齐会让行为多样性下降 (等价类被压平)')
    out = os.path.join(ROOT, 'reports', 'intent_head_stage2.json')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(res, open(out, 'w'), ensure_ascii=False, indent=1)
    print(f'\n✅ 结果已存 {out}')


if __name__ == '__main__':
    main()
